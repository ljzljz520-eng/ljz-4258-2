#!/usr/bin/env python3
"""写入两个种子算例：

  A reblend_handcheck：手算可核对的质量/脂肪完全闭合（含罐底旧料、量程切换、
    不同粒度、跨段存量连续）。
  B reflux_loop：未测回流成环 -> 欠定诊断 + 缺失测量 + 允许区间。

幂等：按 code 检测已存在则跳过。需要先运行迁移（或直接 create_all）。
用法：python -m scripts.seed [--enqueue]
"""
from __future__ import annotations

import sys

from app.database import Base, SessionLocal, engine
from app.models import (
    Batch,
    Job,
    MeasurementRange,
    Sample,
    Segment,
    TankInventory,
    Topology,
    Window,
)
from app.services import enqueue_job, ensure_calc_version
from seed_data import (
    inventories_a,
    inventories_b,
    ranges_a,
    ranges_b,
    samples_a,
    samples_b,
    segments,
    topology_a,
    topology_b,
)

GAP_S = 2000.0
EXTRAP_S = 700.0


def _range_id_map(db, ranges, stream_range_ids: dict) -> dict:
    """返回 (stream,metric,label)->id。"""
    out = {}
    for r in ranges:
        row = MeasurementRange(
            stream_id=r["stream_id"], metric=r["metric"], unit=r["unit"],
            low=r["low"], high=r["high"], label=r["label"],
            active_from=r.get("active_from"), active_to=r.get("active_to"))
        db.add(row)
        db.flush()
        out[(r["stream_id"], r["metric"], r["label"])] = row.id
    return out


def _add_samples(db, rows, stream_range_ids, high_first: bool, segs, batch_id):
    """为 F1 流量样本在 seg1 挂高量程表、seg2 挂低量程表（量程切换）。"""
    for s in rows:
        rid = s.get("range_id")
        if rid is None and s["stream_id"] == "F1" and s["metric"] == "flow":
            if s["ts"] < segs[1]["start"]:
                rid = stream_range_ids.get(("F1", "flow", "F1 高量程表"))
            else:
                rid = next((v for k, v in stream_range_ids.items()
                            if k[0] == "F1" and k[1] == "flow"
                            and k[2] == "F1 低量程表"), None)
        seg = next((g for g in segs
                    if g["start"] <= s["ts"] <= g["end"]), None)
        db.add(Sample(
            batch_id=batch_id,
            stream_id=s["stream_id"],
            segment_id=seg["id"] if seg else None,
            ts=s["ts"], metric=s["metric"], value=s["value"], unit=s["unit"],
            abs_uc=s.get("abs_uc"), rel_uc=s.get("rel_uc"),
            range_id=rid, received_at=s["ts"],
            solids_fraction_wet=s.get("solids_fraction_wet")))


def _load_case(db, topo_def, batch_code, samples, ranges, inventories,
               attach_ranges_switch, label):
    if db.query(Topology).filter_by(code=topo_def["code"]).first():
        print(f"skip {topo_def['code']} (exists)")
        return None
    t = Topology(code=topo_def["code"], name=topo_def["name"],
                 definition={"nodes": topo_def["nodes"],
                             "streams": topo_def["streams"]})
    db.add(t)
    db.flush()
    b = Batch(topology_id=t.id, code=batch_code,
              note=f"种子算例：{label}")
    db.add(b)
    db.flush()
    seg_rows = []
    for g in segments():
        row = Segment(batch_id=b.id, seq=g["seq"], code=g["code"],
                      start_ts=g["start"], end_ts=g["end"],
                      boundary_note=g["boundary_note"])
        db.add(row)
        db.flush()
        seg_rows.append({"id": row.id, "seq": row.seq, "code": row.code,
                         "start": row.start_ts, "end": row.end_ts})

    rid_map = _range_id_map(db, ranges, {})
    _add_samples(db, samples, rid_map, attach_ranges_switch, seg_rows, b.id)

    for q in inventories:
        seg_id = None
        if q.get("segment_seq") is not None:
            seg_id = next(g["id"] for g in seg_rows
                          if g["seq"] == q["segment_seq"])
        db.add(TankInventory(
            node_id=q["node_id"], batch_id=b.id, segment_id=seg_id,
            kind=q["kind"], mass_kg=q["mass_kg"],
            fat_fraction_wet=q["fat_fraction_wet"],
            fat_mass_kg=q["mass_kg"] * q["fat_fraction_wet"],
            abs_uc_mass=q.get("abs_uc_mass"),
            rel_uc_mass=q.get("rel_uc_mass"), ts=q["ts"],
            cross_batch=q.get("cross_batch", False), note=q.get("note", "")))

    w = Window(batch_id=b.id, label=f"{label}稳定窗口（两段）",
               segment_ids=[g["id"] for g in seg_rows],
               max_gap_s=GAP_S, extrap_tolerance_s=EXTRAP_S)
    db.add(w)
    db.flush()
    return w


def main(enqueue: bool = False) -> int:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        ensure_calc_version(db)
        w1 = _load_case(db, topology_a(), "B-HANDCHECK", samples_a(),
                        ranges_a(), inventories_a(), True,
                        "手算闭合")
        w2 = _load_case(db, topology_b(), "B-REFLUX", samples_b(),
                        ranges_b(), inventories_b(), False,
                        "未测回流欠定")
        db.commit()
        if enqueue:
            for w in (w1, w2):
                if w is not None:
                    enqueue_job(db, w)
            print("jobs enqueued")
        print("seed complete: B-HANDCHECK (identified), B-REFLUX (underdetermined)")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(enqueue="--enqueue" in sys.argv))
