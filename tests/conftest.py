"""全局：在导入应用代码前为每个测试会话配置临时 SQLite 数据库。"""
from __future__ import annotations

import os
import pathlib
import tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(ROOT))

_TMP = tempfile.mkdtemp(prefix="milkfat-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ.setdefault("CORS_ORIGINS", "http://testserver")

from app.database import Base, SessionLocal, engine  # noqa: E402
import app.models  # noqa: E402,F401  (register mappers)


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def db_path():
    # 每个测试前清空，保证隔离
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    from app.services import ensure_calc_version
    db = SessionLocal()
    ensure_calc_version(db)
    db.close()
    yield None, None


@pytest.fixture()
def seeded(db_path):
    from seed_data import (inventories_a, inventories_b, ranges_a, ranges_b,
                           samples_a, samples_b, segments as seed_segments,
                           topology_a, topology_b)
    from app.models import (Batch, MeasurementRange, Sample, Segment,
                            TankInventory, Topology, Window)

    def load(topo_def, code, sample_rows, range_rows, inv_rows, switch):
        db = SessionLocal()
        t = Topology(code=topo_def["code"], name=topo_def["name"],
                     definition={"nodes": topo_def["nodes"],
                                 "streams": topo_def["streams"]})
        db.add(t); db.flush()
        b = Batch(topology_id=t.id, code=code)
        db.add(b); db.flush()
        seg_rows = []
        for g in seed_segments():
            r = Segment(batch_id=b.id, seq=g["seq"], code=g["code"],
                        start_ts=g["start"], end_ts=g["end"],
                        boundary_note=g["boundary_note"])
            db.add(r); db.flush()
            seg_rows.append(r)
        rid_f1 = {}
        for rr in range_rows:
            row = MeasurementRange(**rr)
            db.add(row); db.flush()
            if rr["stream_id"] == "F1" and rr["metric"] == "flow":
                rid_f1[rr["label"]] = row.id
        for s in sample_rows:
            rid = None
            if s["stream_id"] == "F1" and s["metric"] == "flow" and switch:
                rid = (rid_f1.get("F1 高量程表")
                       if s["ts"] < seg_rows[1].start_ts
                       else rid_f1.get("F1 低量程表"))
            seg = next((g for g in seg_rows
                        if g.start_ts <= s["ts"] <= g.end_ts), None)
            db.add(Sample(batch_id=b.id, stream_id=s["stream_id"],
                          segment_id=seg.id if seg else None, ts=s["ts"],
                          metric=s["metric"], value=s["value"], unit=s["unit"],
                          abs_uc=s.get("abs_uc"), rel_uc=s.get("rel_uc"),
                          range_id=rid, received_at=s["ts"]))
        for q in inv_rows:
            sid = None
            if q.get("segment_seq") is not None:
                sid = next(g.id for g in seg_rows
                           if g.seq == q["segment_seq"])
            db.add(TankInventory(
                node_id=q["node_id"], batch_id=b.id, segment_id=sid,
                kind=q["kind"], mass_kg=q["mass_kg"],
                fat_fraction_wet=q["fat_fraction_wet"],
                fat_mass_kg=q["mass_kg"] * q["fat_fraction_wet"],
                abs_uc_mass=q.get("abs_uc_mass"), ts=q["ts"],
                cross_batch=q.get("cross_batch", False), note=q.get("note", "")))
        w = Window(batch_id=b.id, label="w",
                   segment_ids=[g.id for g in seg_rows],
                   max_gap_s=2000, extrap_tolerance_s=700)
        db.add(w); db.commit()
        ids = {"batch": b.id, "window": w.id,
               "segments": [g.id for g in seg_rows]}
        db.close()
        return ids

    a = load(topology_a(), "A", samples_a(), ranges_a(), inventories_a(), True)
    b = load(topology_b(), "B", samples_b(), ranges_b(), inventories_b(), False)
    return {"A": a, "B": b}
