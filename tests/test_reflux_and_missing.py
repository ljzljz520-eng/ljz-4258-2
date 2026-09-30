"""回流成环、跨批回流、缺测诊断与允许区间（种子算例 B）。"""
import pytest

from app.core.engine import compute
from app.services import build_snapshot, digest_for


def _run_b(seeded, db_path):
    database, _ = db_path
    from app.database import SessionLocal
    from app.models import Window
    db = SessionLocal()
    w = db.get(Window, seeded["B"]["window"])
    snap = build_snapshot(db, w)
    p = compute(snap, digest=digest_for(snap))
    db.close()
    return p


def test_underdetermined_when_cycle_unmeasured(seeded, db_path):
    p = _run_b(seeded, db_path)
    assert p["status"] == "underdetermined"
    assert p["nullity"] == 4
    ring = next(c for c in p["cycles"]
                if set(c["streams"]) == {"CREAM", "REC"})
    assert ring["unmeasured_cycle"] is True


def test_no_unique_result_forced(seeded, db_path):
    p = _run_b(seeded, db_path)
    # 欠定时不得出现调和结果字段
    assert "stream_segments" in p
    for r in p["stream_segments"]:
        assert "mass_reconciled_kg" not in r
    assert "window_totals" not in p


def test_missing_measurements_pinpoint_streams(seeded, db_path):
    p = _run_b(seeded, db_path)
    mm = p["missing_measurements"]
    pairs = {(m["stream_id"], m["metric"], m["segment_seq"]) for m in mm}
    assert ("CREAM", "flow", 1) in pairs
    assert ("REC", "flow", 1) in pairs
    assert ("CREAM", "flow", 2) in pairs
    # 已装流量计量程随建议给出
    flow_sugg = [m for m in mm if m["metric"] == "flow"]
    assert all(m["meter_installed"] for m in flow_sugg)
    assert flow_sugg[0]["allowed_range"]["high"] == 400


def test_allowed_intervals_unbounded_ring(seeded, db_path):
    p = _run_b(seeded, db_path)
    intervals = {x["variable"]: x
                 for x in p["allowed_intervals"]["intervals"]}
    cream = next(x for x in intervals.values()
                 if x["variable"] == "seg1.CREAM.mass[kg]")
    rec = next(x for x in intervals.values()
               if x["variable"] == "seg1.REC.mass[kg]")
    assert cream["min_kg"] == pytest.approx(120.0)
    assert cream["max_kg"] is None       # 环流量无上界
    assert rec["min_kg"] == pytest.approx(0.0)
    assert rec["max_kg"] is None


def test_cross_batch_heel_enters_same_equation(seeded, db_path):
    """跨批旧料在审计中可见，且作为 opening 进入方程（欠定时仍限定下界）。"""
    p = _run_b(seeded, db_path)
    # 若 opening 没进入方程，CREAM 下界不会是 120（=40 opening + 160 罐增量推导）
    intervals = {x["variable"]: x
                 for x in p["allowed_intervals"]["intervals"]}
    cream = next(x for x in intervals.values()
                 if x["variable"] == "seg1.CREAM.mass[kg]")
    assert cream["min_kg"] >= 40.0


def test_adding_ream_measurement_resolves(seeded, db_path):
    """给 REC 补测后系统可辨识（诊断而非结果的正确性验证）。"""
    database, _ = db_path
    from app.database import SessionLocal
    from app.models import Sample, Window
    from seed_data import T0, RATES_B, REC_B
    from datetime import timedelta
    db = SessionLocal()
    w = db.get(Window, seeded["B"]["window"])
    # 在两段补 REC 流量/密度/脂肪
    for seg_i in (0, 1):
        for off in (0, 1800, 3600):
            ts = T0 + timedelta(hours=seg_i, seconds=off)
            db.add(Sample(batch_id=seeded["B"]["batch"], stream_id="REC",
                          segment_id=seeded["B"]["segments"][seg_i], ts=ts,
                          metric="flow",
                          value=REC_B["flow"] / 3600.0, unit="L/s",
                          rel_uc=0.005, received_at=ts))
            db.add(Sample(batch_id=seeded["B"]["batch"], stream_id="REC",
                          segment_id=seeded["B"]["segments"][seg_i], ts=ts,
                          metric="density", value=REC_B["density"],
                          unit="kg/L", rel_uc=0.002, received_at=ts))
            db.add(Sample(batch_id=seeded["B"]["batch"], stream_id="REC",
                          segment_id=seeded["B"]["segments"][seg_i], ts=ts,
                          metric="fat", value=REC_B["fat"],
                          unit="fraction_wet", rel_uc=0.02, received_at=ts))
    db.commit()
    snap = build_snapshot(db, w)
    p = compute(snap, digest=digest_for(snap))
    # 环上一条流（REC）可由守恒推出另一条 CREAM：质量+脂肪自由度同时消除
    assert p["status"] == "identified"
    assert p["nullity"] == 0
    # （额外补 CREAM 形成冗余/超定测量，系统仍可解）
    for seg_i in (0, 1):
        for off in (0, 1800, 3600):
            ts = T0 + timedelta(hours=seg_i, seconds=off)
            db.add(Sample(batch_id=seeded["B"]["batch"], stream_id="CREAM",
                          segment_id=seeded["B"]["segments"][seg_i], ts=ts,
                          metric="flow",
                          value=240.0 / 3600.0, unit="L/s",
                          rel_uc=0.005, received_at=ts))
            db.add(Sample(batch_id=seeded["B"]["batch"], stream_id="CREAM",
                          segment_id=seeded["B"]["segments"][seg_i], ts=ts,
                          metric="density", value=1.0, unit="kg/L",
                          rel_uc=0.002, received_at=ts))
            db.add(Sample(batch_id=seeded["B"]["batch"], stream_id="CREAM",
                          segment_id=seeded["B"]["segments"][seg_i], ts=ts,
                          metric="fat", value=0.34, unit="fraction_wet",
                          rel_uc=0.02, received_at=ts))
    db.commit()
    snap = build_snapshot(db, w)
    p2 = compute(snap, digest=digest_for(snap))
    assert p2["status"] == "identified"
    db.close()
