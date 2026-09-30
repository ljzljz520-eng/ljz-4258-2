"""计算编排：冻结快照 -> 时间对齐积分 -> 守恒核算 -> 结果载荷。

Worker 与 API 预览都调用 compute(snapshot)，保证「试算」与「正式作业」同一代码路径。
平台不输出回配比例/控制建议；载荷中的 platform_notice 明示该边界。
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.core.alignment import Point, integrate_window
from app.core.balance import (
    InvPoint,
    Problem,
    StreamTotal,
    find_cycles,
    allowed_intervals,
    solve,
    suggest_missing_measurements,
    validate_topology,
)
from app.core.units import (
    convert_density,
    convert_fat_sample,
    convert_flow,
)
from app.core.version import ALGORITHM_VERSION, PLATFORM_NOTICE

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _ts(s: str | datetime) -> float:
    if isinstance(s, str):
        s = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if s.tzinfo is None:
        s = s.replace(tzinfo=timezone.utc)
    return (s - _EPOCH).total_seconds()


def _iso(s) -> str:
    if isinstance(s, str):
        return s
    return s.astimezone(timezone.utc).isoformat()


def _points(samples, stream_id, metric, t0, t1, freeze_ts):
    pts, excluded = [], []
    freeze = _ts(freeze_ts)
    for s in samples:
        if s["stream_id"] != stream_id or s["metric"] != metric:
            continue
        t = _ts(s["ts"])
        if t < t0 - 7200 or t > t1 + 7200:
            continue
        recv = _ts(s.get("received_at") or s["ts"])
        if recv > freeze:
            excluded.append(s["id"])
            continue
        if metric == "flow":
            v = convert_flow(s["value"], s["unit"])
        elif metric == "density":
            v = convert_density(s["value"], s["unit"])
        else:
            cv = convert_fat_sample(
                s["value"], s["unit"],
                solids_fraction_wet=s.get("solids_fraction_wet"))
            v = cv.converted
        pts.append(Point(t=t, v=v, abs_uc=s.get("abs_uc"),
                         rel_uc=s.get("rel_uc"),
                         range_id=s.get("range_id"), sample_id=s["id"]))
    return pts, excluded


def build_problem(snapshot: dict) -> tuple[Problem, dict]:
    topo = snapshot["topology"]
    nodes = topo["nodes"]
    streams = topo["streams"]
    segs = sorted(snapshot["segments"], key=lambda z: z["seq"])
    win = snapshot["window"]
    samples = snapshot.get("samples", [])
    freeze_ts = snapshot.get("freeze_ts") or datetime.now(timezone.utc).isoformat()

    totals: dict = {}
    coverage_notes: list[dict] = []
    late_excluded: set[int] = set()
    range_switches: set[str] = set()

    for seg in segs:
        t0, t1 = _ts(seg["start_ts"]), _ts(seg["end_ts"])
        for st in streams:
            sid = st["id"]
            flow, ex1 = _points(samples, sid, "flow", t0, t1, freeze_ts)
            dens, ex2 = _points(samples, sid, "density", t0, t1, freeze_ts)
            fat, ex3 = _points(samples, sid, "fat", t0, t1, freeze_ts)
            late_excluded.update(ex1 + ex2 + ex3)
            rids = {p.range_id for p in flow if p.range_id is not None}
            if len(rids) > 1:
                range_switches.add(f"{sid}:flow:{sorted(rids)}")

            mt = integrate_window(t0, t1, flow, dens, None,
                                  win["max_gap_s"], win["extrap_tolerance_s"])
            ft = integrate_window(t0, t1, flow, dens, fat,
                                  win["max_gap_s"], win["extrap_tolerance_s"])
            # 若根本没有脂肪样本，fat total 缺测而非 0
            fat_present = bool(fat) and ft.present
            totals[(sid, seg["seq"])] = StreamTotal(
                mass_present=mt.present, mass_kg=mt.total, mass_uc=mt.abs_uc,
                fat_present=fat_present, fat_kg=ft.total, fat_uc=ft.abs_uc,
                mass_reasons=mt.reasons, fat_reasons=ft.reasons,
                source_samples=sorted(set(mt.source_samples + ft.source_samples)))
            for why in mt.reasons + ([] if fat_present else ft.reasons):
                coverage_notes.append({"stream_id": sid,
                                       "segment": seg["code"], "reason": why})

    # 罐存量
    seg_id_to_seq = {g["id"]: g["seq"] for g in segs}
    inv: dict = {}
    for q in snapshot.get("inventories", []):
        seg_seq = seg_id_to_seq.get(q.get("segment_id"))
        if seg_seq is None and q.get("segment_seq") is not None:
            seg_seq = q["segment_seq"]
        fat_mass = q.get("fat_mass_kg")
        if fat_mass is None:
            fat_mass = q["mass_kg"] * q["fat_fraction_wet"]
        uc = q.get("abs_uc_mass")
        rel = q.get("rel_uc_mass")
        if uc is None and rel is not None:
            uc = rel * q["mass_kg"]
        inv.setdefault(q["node_id"], []).append(InvPoint(
            kind=q["kind"], segment_seq=seg_seq,
            mass_kg=q["mass_kg"], fat_kg=fat_mass, mass_uc=uc or 0.0))
    for pts in inv.values():
        pts.sort(key=lambda z: (z.segment_seq is None, z.segment_seq or 0))

    p = Problem(nodes=nodes, streams=streams,
                segments=[{"seq": g["seq"], "code": g["code"]} for g in segs],
                stream_totals=totals, inventories=inv,
                ranges=snapshot.get("ranges", []))
    audit = {
        "late_excluded_sample_ids": sorted(late_excluded),
        "coverage_notes": coverage_notes,
        "range_switches": sorted(range_switches),
    }
    return p, audit


def _window_totals(p: Problem, x, idx, dim):
    out = {}
    for st in p.streams:
        s = 0.0
        for seg in p.segments:
            j = idx[f"{dim}:{seg['seq']}:{st['id']}"]
            s += float(x[j])
        out[st["id"]] = s
    return out


def _node_closure(p: Problem, x, idx, built, reconciled: bool, dim: str):
    """每个内部节点每段的闭合残差 (kg)。"""
    seqs = [g["seq"] for g in p.segments]
    rows = []
    for seg in p.segments:
        seq = seg["seq"]
        for nd in p.nodes:
            if nd["type"] in ("source", "sink"):
                continue
            node = nd["id"]
            inflow = outflow = 0.0
            complete = True
            for st in p.streams:
                tot = p.stream_totals.get((st["id"], seq))
                if reconciled:
                    v = float(x[idx[f"{dim}:{seq}:{st['id']}"]])
                else:
                    ok = tot and (tot.mass_present if dim == "M"
                                  else tot.fat_present)
                    if not ok:
                        complete = False
                        continue
                    v = tot.mass_kg if dim == "M" else tot.fat_kg
                if st["sink"] == node:
                    inflow += v
                elif st["source"] == node:
                    outflow += v
            residual = inflow - outflow
            if nd["type"] == "tank":
                k = seqs.index(seq)
                if reconciled:
                    after_kind = "middle" if k < len(seqs) - 1 else "closing"
                    va = idx[f"V{dim}:{node}:{after_kind}:{seq}"]
                    v_after = float(x[va])
                    if k == 0:
                        pts = p.inventories.get(node, [])
                        op = next((q for q in pts if q.kind == "opening"), None)
                        v_before = ((op.mass_kg if dim == "M" else op.fat_kg)
                                    if op else 0.0)
                    else:
                        vb = idx[f"V{dim}:{node}:middle:{seqs[k-1]}"]
                        v_before = float(x[vb])
                else:
                    pts = p.inventories.get(node, [])
                    if k == 0:
                        op = next((q for q in pts if q.kind == "opening"), None)
                        v_before = ((op.mass_kg if dim == "M" else op.fat_kg)
                                    if op else 0.0)
                    else:
                        mid = next((q for q in pts
                                    if q.kind == "middle"
                                    and q.segment_seq == seqs[k - 1]), None)
                        if mid is None or mid.mass_kg is None:
                            complete = False
                            v_before = 0.0
                        else:
                            v_before = (mid.mass_kg if dim == "M"
                                        else mid.fat_kg)
                    aft = next((q for q in pts
                                if q.kind in ("middle", "closing")
                                and q.segment_seq == seq), None)
                    if aft is None or aft.mass_kg is None:
                        complete = False
                        v_after = 0.0
                    else:
                        v_after = aft.mass_kg if dim == "M" else aft.fat_kg
                residual = v_before + inflow - outflow - v_after
            rows.append({"segment_seq": seq, "segment": seg["code"],
                         "node": node,
                         "metric": "mass" if dim == "M" else "fat",
                         "residual_kg": round(residual, 9),
                         "basis": "reconciled" if reconciled else "measured",
                         "complete": True if reconciled else complete})
    return rows


def compute(snapshot: dict, digest: str = "") -> dict:
    p, audit = build_problem(snapshot)
    errs = validate_topology(p.nodes, p.streams)
    if errs:
        return {"status": "error", "errors": errs,
                "algorithm_version": ALGORITHM_VERSION, "digest": digest}

    cycles = find_cycles(p.streams)
    cycle_info = []
    for ring in cycles:
        unmeasured = all(
            (not p.stream_totals.get((sid, seg["seq"])) or
             not p.stream_totals[(sid, seg["seq"])].mass_present)
            for sid in ring for seg in p.segments)
        cycle_info.append({"streams": ring,
                           "unmeasured_cycle": unmeasured,
                           "consequence":
                           "回路上所有流量均无测量时，沿环整体增减不影响守恒，"
                           "方程欠定，不会给出唯一结果" if unmeasured else
                           "回路存在流量测量，可辨识"})

    sol = solve(p)
    idx, labels, built = sol["built"]["idx"], sol["built"]["labels"], sol["built"]

    payload: dict = {
        "digest": digest,
        "algorithm_version": ALGORITHM_VERSION,
        "status": sol["status"],
        "rank": sol["rank"], "unknowns": sol["n"], "nullity": sol["nullity"],
        "topology_code": snapshot["topology"].get("code"),
        "window": {"id": snapshot["window"]["id"],
                   "label": snapshot["window"]["label"]},
        "cycles": cycle_info,
        "audit": audit,
        "platform_notice": PLATFORM_NOTICE,
        "singular_values": [round(float(v), 9) for v in sol["sv"]],
    }

    # 段/流层面结果
    seg_rows = []
    for seg in p.segments:
        for st in p.streams:
            tot = p.stream_totals.get((st["id"], seg["seq"]))
            row = {"segment": seg["code"], "segment_seq": seg["seq"],
                   "stream_id": st["id"],
                   "mass_measured_kg": (round(tot.mass_kg, 6)
                                        if tot and tot.mass_present else None),
                   "mass_uc_kg": (round(tot.mass_uc, 6)
                                  if tot and tot.mass_present else None),
                   "fat_measured_kg": (round(tot.fat_kg, 6)
                                       if tot and tot.fat_present else None),
                   "fat_uc_kg": (round(tot.fat_uc, 6)
                                 if tot and tot.fat_present else None)}
            if sol["status"] == "identified":
                jm = idx[f"M:{seg['seq']}:{st['id']}"]
                jf = idx[f"F:{seg['seq']}:{st['id']}"]
                row["mass_reconciled_kg"] = round(float(sol["x"][jm]), 6)
                row["fat_reconciled_kg"] = round(float(sol["x"][jf]), 6)
            seg_rows.append(row)
    payload["stream_segments"] = seg_rows

    # 罐存量（调和值）
    inv_rows = []
    if sol["status"] == "identified":
        for node, slots in built["inv_slots"].items():
            for (kind, sseq), (mi, fi) in slots.items():
                inv_rows.append({
                    "node": node, "kind": kind, "segment_seq": sseq,
                    "mass_kg": round(float(sol["x"][mi]), 6),
                    "fat_kg": round(float(sol["x"][fi]), 6)})
    payload["inventory_reconciled"] = inv_rows

    # 闭合残差：测量原样 与 守恒调和后
    if sol["status"] == "identified":
        payload["closure"] = {
            "reconciled": (_node_closure(p, sol["x"], idx, built, True, "M")
                           + _node_closure(p, sol["x"], idx, built, True, "F")),
            "measured": (_node_closure(p, None, idx, built, False, "M")
                         + _node_closure(p, None, idx, built, False, "F")),
        }
        # 窗口级总量（手算核对入口）
        wm = _window_totals(p, sol["x"], idx, "M")
        wf = _window_totals(p, sol["x"], idx, "F")
        payload["window_totals"] = {
            "mass_kg": {k: round(v, 6) for k, v in wm.items()},
            "fat_kg": {k: round(v, 6) for k, v in wf.items()},
        }
        # 调和值不确定度（线性化后验协方差对角）
        import numpy as np
        G, h = built["G"], built["h"]
        n = sol["n"]
        meas = built["meas"]
        measured = {j: (v, sig) for j, v, sig in meas}
        C = np.zeros((G.shape[0] + n, n))
        d = np.zeros(G.shape[0] + n)
        Wd = np.zeros(G.shape[0] + n)
        C[:G.shape[0]] = G; d[:G.shape[0]] = h; Wd[:G.shape[0]] = 1e6
        for j in range(n):
            C[G.shape[0] + j, j] = 1.0
            if j in measured:
                d[G.shape[0] + j] = measured[j][0]
                Wd[G.shape[0] + j] = 1.0 / measured[j][1]
        Cw = C * Wd[:, None]
        cov = np.linalg.pinv(Cw.T @ Cw)
        diag = np.sqrt(np.clip(np.diag(cov), 0, None))
        payload["reconciled_uc_kg"] = {
            labels[j]: round(float(diag[j]), 9) for j in range(n)}
    else:
        payload["missing_measurements"] = suggest_missing_measurements(sol, p)
        payload["allowed_intervals"] = allowed_intervals(sol)
        payload["closure"] = {
            "measured": (_node_closure(p, None, idx, built, False, "M")
                         + _node_closure(p, None, idx, built, False, "F"))}
    return payload
