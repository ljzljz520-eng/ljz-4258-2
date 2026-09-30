"""手算可核对的质量/脂肪闭合（种子算例 A）。"""
import pytest
from app.core.engine import compute
from app.services import build_snapshot, digest_for


def _run(seeded, db_path):
    database, _ = db_path
    from app.database import SessionLocal
    from app.models import Window
    db = SessionLocal()
    w = db.get(Window, seeded["A"]["window"])
    snap = build_snapshot(db, w)
    digest = digest_for(snap)
    payload = compute(snap, digest=digest)
    db.close()
    return payload


def test_identified_full_rank(seeded, db_path):
    p = _run(seeded, db_path)
    assert p["status"] == "identified"
    assert p["nullity"] == 0
    assert p["rank"] == p["unknowns"]


def test_window_mass_totals_handcheck(seeded, db_path):
    p = _run(seeded, db_path)
    m = p["window_totals"]["mass_kg"]
    assert m["F1"] == 1800.0
    assert m["F2"] == 200.0
    assert m["CREAM"] == 240.0
    assert m["SKIM"] == 1560.0
    assert m["CREAM_OUT"] == 240.0
    assert m["PRODUCT"] == 1760.0
    # 全局：进料 = 成品（罐净变化为 0）
    assert m["F1"] + m["F2"] == m["PRODUCT"] + m["CREAM_OUT"]


def test_window_fat_totals_handcheck(seeded, db_path):
    p = _run(seeded, db_path)
    f = p["window_totals"]["fat_kg"]
    assert f["F1"] == 72.0
    assert f["F2"] == 8.0
    assert f["CREAM"] == 72.0
    assert f["SKIM"] == 0.0
    assert f["CREAM_OUT"] == 72.0
    assert f["PRODUCT"] == 8.0
    assert f["F1"] + f["F2"] == f["PRODUCT"] + f["CREAM_OUT"] == 80.0


def test_all_reconciled_closures_zero(seeded, db_path):
    p = _run(seeded, db_path)
    for r in p["closure"]["reconciled"]:
        assert abs(r["residual_kg"]) < 1e-6, r


def test_tank_heels_preserved(seeded, db_path):
    p = _run(seeded, db_path)
    inv = {(r["kind"], r["segment_seq"]): r
           for r in p["inventory_reconciled"]}
    # 跨批旧料 40 kg / 12 kg 脂肪在段间保持，期末仍为 40
    assert inv[("middle", 1)]["mass_kg"] == 40.0
    assert inv[("middle", 1)]["fat_kg"] == 12.0
    assert inv[("closing", 2)]["mass_kg"] == 40.0
    assert inv[("closing", 2)]["fat_kg"] == 12.0


def test_per_segment_balances(seeded, db_path):
    p = _run(seeded, db_path)
    rows = p["stream_segments"]
    for seg in ("seg1", "seg2"):
        sr = [r for r in rows if r["segment"] == seg]
        d = {r["stream_id"]: r for r in sr}
        # SEP: F1 = CREAM + SKIM
        assert d["F1"]["mass_reconciled_kg"] == pytest.approx(
            d["CREAM"]["mass_reconciled_kg"]
            + d["SKIM"]["mass_reconciled_kg"])
        # BLEND: F2 + SKIM = PRODUCT
        assert d["PRODUCT"]["mass_reconciled_kg"] == pytest.approx(
            d["F2"]["mass_reconciled_kg"]
            + d["SKIM"]["mass_reconciled_kg"])
        # T_CREAM: CREAM = CREAM_OUT（罐存量恒定）
        assert d["CREAM"]["mass_reconciled_kg"] == pytest.approx(
            d["CREAM_OUT"]["mass_reconciled_kg"])
        assert d["CREAM"]["fat_reconciled_kg"] == pytest.approx(
            d["CREAM_OUT"]["fat_reconciled_kg"])


def test_platform_does_not_recommend(seeded, db_path):
    p = _run(seeded, db_path)
    blob = str(p)
    assert "推荐回配" in p["platform_notice"]
    for forbidden in ("reblend_ratio_recommendation", "setpoint",
                      "control_command", "recommended_ratio"):
        assert forbidden not in blob



