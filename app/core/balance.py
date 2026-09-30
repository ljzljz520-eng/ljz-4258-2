"""质量/脂肪双守恒核算内核。

建模（取舍见 README）：
  * 一个「窗口」由若干连续段组成；同一拓扑的所有节点在所有段上统一建模，
    罐底旧料 (opening) 与跨段/跨批回流全部进入同一条守恒方程，
    从而暴露回流成环导致的不可辨识。
  * 变量：每段每条流的总质量 M[s,e] 与总脂肪 F[s,e]（单位 kg），
    加上每个罐每段的中间存量 V^M/V^F（仅当需要时）和每罐期末 closing。
  * 守恒行（硬约束）：
      普通内部节点：  Σin M - Σout M = 0（脂肪同理）
      罐：           opening + Σin M - Σout M - closing/middle_next = 0
  * 测量行（软约束，权重 1/σ）：段内积分得到的总量；未测的流不给测量行，
    由此通过 SVD 秩检查自然发现欠定。
  * source/sink 为边界节点，不写守恒行。
输出不包含任何回配比例或控制建议。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.linalg import svd
from scipy.optimize import linprog, lsq_linear

HARD_W = 1.0e6
PRIOR_W = 1.0e-7
RANK_TOL = 1.0e-9


# ---------------------------------------------------------------- 数据结构
@dataclass
class StreamTotal:
    mass_present: bool = False
    mass_kg: float = 0.0
    mass_uc: float = float("inf")
    fat_present: bool = False
    fat_kg: float = 0.0
    fat_uc: float = float("inf")
    mass_reasons: list[str] = field(default_factory=list)
    fat_reasons: list[str] = field(default_factory=list)
    source_samples: list[int] = field(default_factory=list)


@dataclass
class InvPoint:
    kind: str                  # opening|middle|closing
    segment_seq: int | None    # 对应段序号；opening 为段前，closing 为末段后
    mass_kg: float | None      # None => 未测存量（变量）
    fat_kg: float | None
    mass_uc: float = 0.0


@dataclass
class Problem:
    nodes: list[dict]
    streams: list[dict]
    segments: list[dict]       # {seq, code, start, end}
    stream_totals: dict        # (stream_id, seq) -> StreamTotal
    inventories: dict          # node_id -> list[InvPoint], 按时间排序
    ranges: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------- 校验/成环
def validate_topology(nodes: list[dict], streams: list[dict]) -> list[str]:
    errs: list[str] = []
    ids = {n["id"] for n in nodes}
    seen = set()
    for s in streams:
        if s["id"] in seen:
            errs.append(f"duplicate stream id {s['id']}")
        seen.add(s["id"])
        if s["source"] not in ids:
            errs.append(f"stream {s['id']} source {s['source']} missing")
        if s["sink"] not in ids:
            errs.append(f"stream {s['id']} sink {s['sink']} missing")
    return errs


def find_cycles(streams: list[dict]) -> list[list[str]]:
    """有向图基本环检测（三色 DFS），返回各环上的流 id 列表。"""
    adj: dict[str, list[tuple[str, str]]] = {}
    for st in streams:
        adj.setdefault(st["source"], []).append((st["sink"], st["id"]))
    cycles: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {}
    nodes = {st["source"] for st in streams} | {st["sink"] for st in streams}
    for n_ in nodes:
        color[n_] = WHITE

    def dfs(u, path_nodes, path_edges):
        color[u] = GRAY
        for v, eid in adj.get(u, []):
            if color.get(v, WHITE) == GRAY:
                i = path_nodes.index(v)
                ring = path_edges[i:] + [eid]
                key = tuple(sorted(ring))
                if key not in seen:
                    seen.add(key)
                    cycles.append(ring)
            elif color.get(v, WHITE) == WHITE:
                dfs(v, path_nodes + [v], path_edges + [eid])
        color[u] = BLACK

    for root in list(nodes):
        if color[root] == WHITE:
            dfs(root, [root], [])
    return cycles


# ---------------------------------------------------------------- 装配
def _fat_kg(inv: InvPoint) -> float:
    return inv.fat_kg if inv.fat_kg is not None else 0.0


def build_indices(p: Problem):
    """变量索引：x = [每段每流 M, 每段每流 F, 罐存量 V^M, V^F]。"""
    seqs = [s["seq"] for s in p.segments]
    idx: dict[str, int] = {}
    labels: list[str] = {}
    n = 0
    for seq in seqs:
        for st in p.streams:
            idx[f"M:{seq}:{st['id']}"] = n
            labels[n] = f"seg{seq}.{st['id']}.mass[kg]"
            n += 1
    for seq in seqs:
        for st in p.streams:
            idx[f"F:{seq}:{st['id']}"] = n
            labels[n] = f"seg{seq}.{st['id']}.fat[kg]"
            n += 1

    tank_nodes = [nd["id"] for nd in p.nodes if nd["type"] == "tank"]
    inv_slots: dict[str, dict] = {t: {} for t in tank_nodes}
    # 每罐：段间 middle（seq 表示段 k 之后），最后 closing
    for t in tank_nodes:
        for k, seq in enumerate(seqs):
            if k < len(seqs) - 1:
                kind = "middle"
                slot_seq = seq
            else:
                kind = "closing"
                slot_seq = seq
            m_idx = n
            idx[f"VM:{t}:{kind}:{slot_seq}"] = n
            labels[n] = f"{t}.{kind}_after_seg{slot_seq}.M[kg]"
            n += 1
            idx[f"VF:{t}:{kind}:{slot_seq}"] = n
            labels[n] = f"{t}.{kind}_after_seg{slot_seq}.F[kg]"
            n += 1
            inv_slots[t][(kind, slot_seq)] = (m_idx, m_idx + 1)
    return idx, labels, inv_slots


def _inv_lookup(p: Problem):
    """已知存量查询：(node, kind, seq) -> InvPoint。opening 用最小段前。"""
    known: dict[tuple, InvPoint] = {}
    for node, pts in p.inventories.items():
        for q in pts:
            known[(node, q.kind, q.segment_seq)] = q
    return known


def _meas_rows(p: Problem, idx, dim: str):
    """返回 [(row_index, value, sigma)] 的测量行（直接对应变量）。"""
    rows = []
    for seq in [s["seq"] for s in p.segments]:
        for st in p.streams:
            tot = p.stream_totals.get((st["id"], seq))
            if tot is None:
                continue
            if dim == "M" and tot.mass_present:
                rows.append((idx[f"M:{seq}:{st['id']}"], tot.mass_kg,
                             max(tot.mass_uc, 1e-6)))
            if dim == "F" and tot.fat_present:
                rows.append((idx[f"F:{seq}:{st['id']}"], tot.fat_kg,
                             max(tot.fat_uc, 1e-6)))
    return rows


def _opening(p: Problem, known, tank: str, first_seq):
    q = known.get((tank, "opening", None))
    if q is None:
        return 0.0, 0.0
    return (q.mass_kg or 0.0), _fat_kg(q)


def build_system(p: Problem):
    idx, labels, inv_slots = build_indices(p)
    n = len(idx)
    seqs = [s["seq"] for s in p.segments]
    known = _inv_lookup(p)
    tanks = {nd["id"] for nd in p.nodes if nd["type"] == "tank"}
    node_type = {nd["id"]: nd["type"] for nd in p.nodes}
    streams = p.streams

    hard: list[tuple[dict, float]] = []
    balance_meta: list[dict] = []

    def inv_var(tank, kind, seq, dim):
        pair = inv_slots[tank][(kind, seq)]
        return pair[0] if dim == "M" else pair[1]

    for k, seq in enumerate(seqs):
        for nd in p.nodes:
            node = nd["id"]
            if node_type[node] in ("source", "sink"):
                continue
            for dim in ("M", "F"):
                row: dict[int, float] = {}
                for st in streams:
                    coeff = 0.0
                    if st["sink"] == node:
                        coeff += 1.0
                    if st["source"] == node:
                        coeff -= 1.0
                    if coeff:
                        row[idx[f"{dim}:{seq}:{st['id']}"]] = coeff

                rhs = 0.0
                if node in tanks:
                    # - V_after(k) + V_before(k)，其中
                    # V_before(k)=opening(k=0) 或 上一段 middle/closing 变量
                    after_kind = "middle" if k < len(seqs) - 1 else "closing"
                    va = inv_var(node, after_kind, seq, dim)
                    row[va] = row.get(va, 0.0) - 1.0
                    if k == 0:
                        om, of = _opening(p, known, node, seq)
                        rhs = -(om if dim == "M" else of)
                    else:
                        prev_seq = seqs[k - 1]
                        vb = inv_var(node, "middle", prev_seq, dim)
                        row[vb] = row.get(vb, 0.0) + 1.0
                        # 若该 middle 已测，作为已知 RHS 处理：从变量侧剔除
                        q = known.get((node, "middle", prev_seq))
                        if q is not None:
                            val = (q.mass_kg if dim == "M" else _fat_kg(q))
                            if val is not None:
                                rhs -= val
                                row.pop(vb, None)
                hard.append((row, rhs))
                balance_meta.append({"segment_seq": seq, "node": node,
                                     "metric": "mass" if dim == "M" else "fat"})

    # 已知 closing / middle 存量 -> 测量行（带 σ，走软行）
    inv_meas: list[tuple[int, float, float, dict]] = []
    for t in tanks:
        for (kind, slot_seq), (mi, fi) in inv_slots[t].items():
            q = known.get((t, kind, slot_seq))
            if q is None or q.mass_kg is None:
                continue
            for base_i, val, dim in (
                (mi, q.mass_kg, "M"),
                (fi, _fat_kg(q), "F"),
            ):
                inv_meas.append((base_i, val, max(q.mass_uc, 1e-6),
                                 {"node": t, "kind": kind,
                                  "segment_seq": slot_seq, "metric": dim}))

    G = np.zeros((len(hard), n))
    h = np.zeros(len(hard))
    for i, (row, rhs) in enumerate(hard):
        for j, c in row.items():
            G[i, j] = c
        h[i] = rhs

    meas = _meas_rows(p, idx, "M") + _meas_rows(p, idx, "F") + [
        (a, b, c) for a, b, c, _ in inv_meas]
    return {
        "idx": idx, "labels": labels, "n": n, "G": G, "h": h,
        "balance_meta": balance_meta, "meas": meas, "inv_meas": inv_meas,
        "inv_slots": inv_slots, "known": known,
    }


# ---------------------------------------------------------------- 秩/零空间
def rank_nullspace(A: float, tol: float = RANK_TOL):
    u, s, vh = svd(A)
    tol = tol * max(1.0, s[0] if len(s) else 0.0)
    r = int(np.sum(s > tol))
    Z = vh[r:].T
    return r, Z, s


def identifiability(p: Problem):
    errs = validate_topology(p.nodes, p.streams)
    if errs:
        return {"status": "error", "errors": errs}
    built = build_system(p)
    n = built["n"]
    G, h, meas = built["G"], built["h"], built["meas"]

    # 用于秩判的完整有效约束矩阵：硬守恒（归一）+ 测量行
    A = np.zeros((G.shape[0] + len(meas), n))
    A[: G.shape[0], :] = G
    y = np.zeros(A.shape[0])
    y[: G.shape[0]] = h
    for k, (j, v, _sig) in enumerate(meas):
        A[G.shape[0] + k, j] = 1.0
        y[G.shape[0] + k] = v

    rank, Z, sv = rank_nullspace(A)
    nullity = n - rank
    return {"status": "identified" if nullity == 0 else "underdetermined",
            "built": built, "A": A, "y": y, "rank": rank, "n": n,
            "nullity": nullity, "Z": Z, "sv": sv}


# ---------------------------------------------------------------- 求解
def solve(p: Problem):
    ident = identifiability(p)
    if ident["status"] == "error":
        return ident
    built = ident["built"]
    n, G, h = ident["n"], built["G"], built["h"]
    meas = built["meas"]

    # 堆叠：硬守恒高权重 + 测量 1/σ + 未知变量零先验（极小权重，仅数值正则）
    rows = G.shape[0] + n
    C = np.zeros((rows, n))
    d = np.zeros(rows)
    w = np.zeros(rows)
    C[: G.shape[0], :] = G
    d[: G.shape[0]] = h
    w[: G.shape[0]] = HARD_W
    measured = {j: (v, sig) for j, v, sig in meas}
    for j in range(n):
        i = G.shape[0] + j
        C[i, j] = 1.0
        if j in measured:
            d[i] = measured[j][0]
            w[i] = 1.0 / measured[j][1]
        else:
            w[i] = PRIOR_W

    # 显式行加权（lsq_linear 无 W 参数）：求解 min ||W(Cx-d)||
    Cw = C * w[:, None]
    dw = d * w
    lb = np.zeros(n)
    ub = np.full(n, np.inf)
    sol = lsq_linear(Cw, dw, bounds=(lb, ub), method="bvls",
                     max_iter=4000, tol=1e-14)
    x = sol.x
    return {**ident, "x": x}


# ---------------------------------------------------------------- 自由变量区间
def allowed_intervals(ident, p: Problem | None = None,
                      max_vars: int = 60) -> dict:
    """欠定时用 LP 给出每个未知变量的允许区间（绝不输出唯一解）。

    约束：守恒 Gx=h、已知测量 x_j=v（用测量总量，容差取 σ）、x>=0。
    只报告未测量的流段总量与未测存量；可解时返回 min/max（kg）。
    """
    if ident["status"] != "underdetermined":
        return {}
    built = ident["built"]
    G, h = built["G"], built["h"]
    n = ident["n"]
    labels = built["labels"]

    meas = {j: (v, sig) for j, v, sig in built["meas"]}
    eq_rows = [G]
    eq_rhs = [h]
    fixed = set()
    for j, (v, sig) in meas.items():
        row = np.zeros((1, n))
        row[0, j] = 1.0
        eq_rows.append(row)
        eq_rhs.append(np.array([np.clip(v, 0.0, None)]))
        fixed.add(j)
    Aeq = np.vstack(eq_rows)
    beq = np.concatenate(eq_rhs)

    # 边界：非负；量程表换算为窗口允许总质量上界（量程 × 段时长 × 典型密度）。
    # 这里量程 high 以 L/h 表示，段时长秒由 problem 段列表换算（如可得）。
    seqs_meta = [g for g in p.segments] if p is not None else []
    range_map: dict[tuple, dict] = {}
    if p is not None:
        for r in p.ranges:
            range_map[(r["stream_id"], r["metric"])] = r
    seg_span: dict[int, float] = {}
    if p is not None:
        # 段时长未放入 Problem；用 ranges 时按保守 1 小时上限不可行，
        # 因此区间仅标注「受量程约束，需补测」，不强行截断（见下 meter_range）。
        pass
    bounds = [(0.0, None)] * n

    # 可行性检验
    probe = linprog(np.zeros(n), A_eq=Aeq, b_eq=beq,
                    bounds=[(0, None)] * n, method="highs")
    if not probe.success:
        return {"infeasible": True,
                "reason": "守恒与已录测量相互矛盾，请核对测量或存量"}

    # 选择要报告的变量索引
    targets = [j for j in range(n) if j not in fixed]
    if len(targets) > max_vars:
        targets = targets[:max_vars]

    intervals = []
    for j in targets:
        c = np.zeros(n)
        c[j] = 1.0
        lo_r = linprog(c, A_eq=Aeq, b_eq=beq, bounds=bounds, method="highs")
        hi_r = linprog(-c, A_eq=Aeq, b_eq=beq, bounds=bounds, method="highs")
        if not lo_r.success:
            continue
        unbounded = (hi_r.status == 3)
        intervals.append({
            "variable": labels[j],
            "min_kg": round(float(lo_r.fun), 6),
            "max_kg": (None if unbounded
                       else round(float(-hi_r.fun), 6)
                       if hi_r.success else None),
            "interpretation": (
                "无上界：该环上无任何流量测量，需在已装/加装流量计处补测"
                if unbounded else "由守恒与已录测量限定的可行区间"),
        })
    return {"note": "区间为满足全部守恒与已录测量的可行范围；不代表唯一结果",
            "intervals": intervals}


# ---------------------------------------------------------------- 缺失测量建议
def suggest_missing_measurements(ident, p: Problem):
    """枚举加装/补录哪一条测量能提升秩；附带量程允许区间。"""
    if ident["status"] != "underdetermined":
        return []
    A, rank = ident["A"], ident["rank"]
    n = ident["n"]
    seqs = [s["seq"] for s in p.segments]
    range_index = {(r["stream_id"], r["metric"]): r for r in p.ranges}
    suggestions = []
    seen = set()
    for seq in seqs:
        for st in p.streams:
            tot = p.stream_totals.get((st["id"], seq))
            for dim, metric, key in (("M", "flow", f"M:{seq}:{st['id']}"),
                                     ("F", "fat", f"F:{seq}:{st['id']}")):
                present = bool(tot and (tot.mass_present if dim == "M"
                                        else tot.fat_present))
                if present or key in seen:
                    continue
                seen.add(key)
                j = ident["built"]["idx"][key]
                A2 = np.vstack([A, np.eye(1, n, j)])
                r2, *_ = rank_nullspace(A2)
                if r2 > rank:
                    rng = range_index.get((st["id"], metric))
                    suggestions.append({
                        "stream_id": st["id"], "segment_seq": seq,
                        "metric": metric,
                        "rank_gain": r2 - rank,
                        "meter_installed": rng is not None,
                        "allowed_range": None if rng is None else {
                            "unit": rng["unit"], "low": rng["low"],
                            "high": rng["high"]},
                    })
    suggestions.sort(key=lambda s: (-s["rank_gain"],
                                     not s["meter_installed"]))
    return suggestions
