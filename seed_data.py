"""种子算例数据（脚本与测试共用）。

算例 A「reblend_handcheck」——所有数设计成可手算：
  每段 1 小时，共 2 段；每段速率相同，故段总量 = 速率 × 1h。
  进料 FEED 1000 kg/h（脂肪 4%，40 kg/h）
    ├─ F1 900 kg/h → 分离机
    │     ├─ CREAM 120 kg/h（脂肪 30%，36 kg/h）→ 奶油罐 T_CREAM
    │     └─ SKIM  780 kg/h（脂肪 0%，0  kg/h）→ 调配机
    └─ F2 100 kg/h（脂肪 4%）→ 调配机
  奶油罐（含罐底旧料 40 kg，脂肪 30%，跨批残留）：
     每段进 120 kg、出 120 kg（CREAM_OUT 成品），期末存量恒为 40 kg
  调配机：SKIM 780 + F2 100 = PRODUCT 880 kg/h（脂肪 4 kg/h，0.4545%）
  出口：PRODUCT 880 + CREAM_OUT 120 = 1000 kg/h；窗口两段合计 2000 kg

  全局核对（两段）：
     进料总质量 2000 kg、脂肪 80 kg；罐存量 opening=closing（40 kg/12 kg）
     sink 收 PRODUCT 1760 kg（脂肪 8 kg）+ CREAM_OUT 240 kg（脂肪 72 kg）
       = 2000 kg 质量、80 kg 脂肪，全局质量/脂肪均闭合。
  逐节点质量/脂肪在测试中断言残差为 0（数值容差）。

算例 B「reflux_loop」：在 A 的拓扑上增加 BLENDER→SEPARATOR 的回流 R 且不装流量计，
  形成测量环，矩阵秩亏 -> 欠定诊断、给出缺失测量与允许区间，不产出唯一结果。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

# 速率常数（体积 L/h、密度 kg/L 按选取使质量速率恰为整数 kg/h）
RATES = {
    # stream: (flow_L_h, density_kg_L, fat_wet_fraction)
    "F1": (873.786407766990, 1.030, 0.04),      # 900 kg/h
    "F2": (97.087378640777, 1.030, 0.04),       # 100 kg/h
    "CREAM": (120.0, 1.000, 0.30),              # 120 kg/h
    "SKIM": (780.0, 1.000, 0.00),               # 780 kg/h
    "CREAM_OUT": (120.0, 1.000, 0.30),          # 120 kg/h（罐进出平衡）
    "PRODUCT": (846.153846153846, 1.040, 4.0 / 880.0),  # 880 kg/h
}
# 进料量程切换：seg1 用高量程表，seg2 切到低量程表
# ---- 算例 B 速率：未测回流环物理一致解（环内 CREAM/REC 不提供测量）----
# 分离机: 1020+120=240+780=1140 质量；脂肪 40.8+40.8=81.6（CREAM 34%）
# 奶油罐: 每段净增 120 kg/40.8 kg 脂肪（opening 40 -> middle 160 -> closing 280）
# 分离机: 900+120 = 240+780 = 1020 质量平衡
# 脂肪: F1 40.8 + REC 40.8 = CREAM 81.6（CREAM/REC 均 34%）
# 奶油罐: 每段净增 120 kg/40.8 kg 脂肪；opening 40 -> closing 280，均 34%
RATES_B = {
    "F1": (873.786407766990, 1.030, 0.0453333333333),  # 900 kg/h, 4.533%
    "F2": (97.087378640777, 1.030, 0.04),              # 100 kg/h
    "SKIM": (780.0, 1.000, 0.00),
    "PRODUCT": (846.153846153846, 1.040, 4.0 / 880.0), # 880 kg/h
}
CREAM_B = dict(flow=240.0, density=1.0, fat=0.34)
REC_B = dict(flow=120.0, density=1.0, fat=0.34)

FLOW_REL_UC = {"F1": 0.004, "F2": 0.004}
DENSITY_REL_UC = 0.002
FAT_REL_UC = {"F1": 0.02, "F2": 0.02, "CREAM": 0.015,
              "CREAM_OUT": 0.015, "PRODUCT": 0.03}

T0 = datetime(2026, 9, 30, 0, 0, tzinfo=timezone.utc)
SEG_HOURS = 1


def topology_a() -> dict:
    return {
        "code": "plant-reblend",
        "name": "乳脂分离-回配核算演示拓扑（手算算例）",
        "nodes": [
            {"id": "RAW", "type": "source", "name": "原料乳入口"},
            {"id": "SEP", "type": "separator", "name": "离心分离机"},
            {"id": "T_CREAM", "type": "tank", "name": "稀奶油罐（含罐底旧料）"},
            {"id": "BLEND", "type": "blender", "name": "回配/标准化调配机"},
            {"id": "OUT", "type": "sink", "name": "成品计量出口"},
        ],
        "streams": [
            {"id": "F1", "source": "RAW", "sink": "SEP",
             "name": "原料→分离机"},
            {"id": "F2", "source": "RAW", "sink": "BLEND",
             "name": "原料旁通→调配机"},
            {"id": "CREAM", "source": "SEP", "sink": "T_CREAM",
             "name": "稀奶油→罐"},
            {"id": "SKIM", "source": "SEP", "sink": "BLEND",
             "name": "脱脂乳→调配机"},
            {"id": "CREAM_OUT", "source": "T_CREAM", "sink": "OUT",
             "name": "罐出稀奶油成品"},
            {"id": "PRODUCT", "source": "BLEND", "sink": "OUT",
             "name": "标准化乳成品"},
        ],
    }


def topology_b() -> dict:
    t = topology_a()
    t["code"] = "plant-reflux"
    t["name"] = "带未测回流成环的欠定拓扑"
    # 用回流替代成品稀奶油出口：CREAM 与 REC 均不提供测量，
    # SEP <-> T_CREAM 形成无测量环
    t["streams"] = [x for x in t["streams"] if x["id"] != "CREAM_OUT"]
    t["streams"].append({"id": "REC", "source": "T_CREAM", "sink": "SEP",
                         "name": "罐→分离机跨批回流（未装流量计）"})
    t["nodes"] = [n for n in t["nodes"]]
    return t


def samples_b():
    """B：只对 F1/F2/SKIM/PRODUCT 采样；CREAM、REC 无任何测量。"""
    out = []
    sid = 0
    segs = segments()
    for seg in segs:
        for stream, (q_h, rho, w) in RATES_B.items():
            q_s = q_h / 3600.0
            for off in (0, 1800, 3600):
                sid += 1
                out.append({"id": sid, "stream_id": stream, "metric": "flow",
                            "ts": seg["start"] + timedelta(seconds=off),
                            "value": q_s, "unit": "L/s",
                            "rel_uc": FLOW_REL_UC.get(stream, 0.005)})
            for off in (0, 1800, 3600):
                sid += 1
                out.append({"id": sid, "stream_id": stream,
                            "metric": "density",
                            "ts": seg["start"] + timedelta(seconds=off),
                            "value": rho, "unit": "kg/L",
                            "rel_uc": DENSITY_REL_UC})
            for off in (0, 1800, 3600):
                sid += 1
                out.append({"id": sid, "stream_id": stream, "metric": "fat",
                            "ts": seg["start"] + timedelta(seconds=off),
                            "value": w, "unit": "fraction_wet",
                            "rel_uc": FAT_REL_UC.get(stream, 0.03)})
    return out


def segments(n: int = 2):
    return [
        {"seq": i + 1,
         "code": f"seg{i+1}",
         "start": T0 + timedelta(hours=i * SEG_HOURS),
         "end": T0 + timedelta(hours=(i + 1) * SEG_HOURS),
         "boundary_note": (
             "seg1 期初包含奶油罐跨批旧料 40 kg（脂肪 30%）" if i == 0
             else "段间罐存量连续，进入同一守恒方程")}
        for i in range(n)
    ]


def ranges_a():
    """F1 两台量程表：seg1 高量程、seg2 低量程，演示量程切换。"""
    return [
        {"stream_id": "F1", "metric": "flow", "unit": "L/h",
         "low": 800, "high": 1200, "label": "F1 高量程表",
         "active_from": T0 - timedelta(days=1),
         "active_to": T0 + timedelta(hours=1)},
        {"stream_id": "F1", "metric": "flow", "unit": "L/h",
         "low": 400, "high": 1050, "label": "F1 低量程表",
         "active_from": T0 + timedelta(hours=1),
         "active_to": None},
        {"stream_id": "F2", "metric": "flow", "unit": "L/h",
         "low": 0, "high": 300, "label": "F2 流量计"},
        {"stream_id": "CREAM", "metric": "flow", "unit": "L/h",
         "low": 0, "high": 400, "label": "CREAM 流量计"},
        {"stream_id": "SKIM", "metric": "flow", "unit": "L/h",
         "low": 0, "high": 1200, "label": "SKIM 流量计"},
        {"stream_id": "CREAM_OUT", "metric": "flow", "unit": "L/h",
         "low": 0, "high": 400, "label": "CREAM_OUT 流量计"},
        {"stream_id": "PRODUCT", "metric": "flow", "unit": "L/h",
         "low": 400, "high": 1200, "label": "PRODUCT 流量计"},
    ]


def samples_a(include_r: bool = False):
    """每条流每段 3 个流量点、2 个密度点、2 个脂肪点（不同粒度）。"""
    out = []
    sid = 0
    segs = segments()
    for seg in segs:
        for stream, (q_h, rho, w) in RATES.items():
            q_s = q_h / 3600.0
            offsets = [0, 1800, 3600]
            for off in offsets:
                sid += 1
                out.append({
                    "id": sid, "stream_id": stream, "metric": "flow",
                    "ts": seg["start"] + timedelta(seconds=off),
                    "value": q_s, "unit": "L/s",
                    "rel_uc": FLOW_REL_UC.get(stream, 0.005),
                })
            for frac_off in (0, 1800, 3600):
                sid += 1
                out.append({
                    "id": sid, "stream_id": stream, "metric": "density",
                    "ts": seg["start"] + timedelta(seconds=frac_off),
                    "value": rho, "unit": "kg/L",
                    "rel_uc": DENSITY_REL_UC})
            for frac_off in (0, 1800, 3600):
                sid += 1
                out.append({
                    "id": sid, "stream_id": stream, "metric": "fat",
                    "ts": seg["start"] + timedelta(seconds=frac_off),
                    "value": w, "unit": "fraction_wet",
                    "rel_uc": FAT_REL_UC.get(stream, 0.03)})
    if include_r:
        # R 不提供任何流量/脂肪测量，仅占位（无样品）
        pass
    return out


def ranges_b():
    return [
        {"stream_id": "F1", "metric": "flow", "unit": "L/h", "low": 600,
         "high": 1400, "label": "F1 流量计", "active_from": T0 - timedelta(days=1),
         "active_to": None},
        {"stream_id": "F2", "metric": "flow", "unit": "L/h", "low": 0,
         "high": 300, "label": "F2 流量计"},
        {"stream_id": "SKIM", "metric": "flow", "unit": "L/h", "low": 0,
         "high": 1200, "label": "SKIM 流量计"},
        {"stream_id": "PRODUCT", "metric": "flow", "unit": "L/h", "low": 400,
         "high": 1200, "label": "PRODUCT 流量计"},
        {"stream_id": "CREAM", "metric": "flow", "unit": "L/h", "low": 0,
         "high": 400, "label": "CREAM 流量计（已装，当前无读数）"},
        {"stream_id": "REC", "metric": "flow", "unit": "L/h", "low": 0,
         "high": 400, "label": "REC 回流流量计（已装，当前无读数）"},
    ]


def inventories_b():
    """奶油罐：opening 40kg@34%（跨批），closing 280kg@34%；middle 不测。"""
    return [
        {"node_id": "T_CREAM", "kind": "opening", "segment_seq": None,
         "mass_kg": 40.0, "fat_fraction_wet": 0.34,
         "abs_uc_mass": 0.2, "cross_batch": True, "ts": T0,
         "note": "上一批遗留罐底旧料"},
        {"node_id": "T_CREAM", "kind": "closing", "segment_seq": 2,
         "mass_kg": 280.0, "fat_fraction_wet": 0.34,
         "abs_uc_mass": 0.5, "cross_batch": False,
         "ts": T0 + timedelta(hours=2),
         "note": "窗口末实测罐存量"},
    ]


def inventories_a():
    """奶油罐：opening 跨批旧料，两段后 closing（无中间测量，作为变量求）。"""
    return [
        {"node_id": "T_CREAM", "kind": "opening", "segment_seq": None,
         "mass_kg": 40.0, "fat_fraction_wet": 0.30,
         "abs_uc_mass": 0.2, "cross_batch": True,
         "ts": T0, "note": "上一批遗留罐底旧料"},
        {"node_id": "T_CREAM", "kind": "closing", "segment_seq": 2,
         "mass_kg": 40.0, "fat_fraction_wet": 0.30,
         "abs_uc_mass": 0.2, "cross_batch": False,
         "ts": T0 + timedelta(hours=2),
         "note": "窗口末实测罐存量（与期初相同）"},
    ]
