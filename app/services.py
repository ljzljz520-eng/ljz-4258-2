"""领域服务：构建冻结快照、摘要校验、作业入队与失配处理。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.digest import input_digest
from app.core.version import ALGORITHM_VERSION
from app.models import (
    Batch,
    Job,
    MeasurementRange,
    Result,
    Sample,
    Segment,
    Signoff,
    TankInventory,
    Topology,
    Window,
)


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _serialize_sample(s: Sample) -> dict:
    return {
        "id": s.id, "batch_id": s.batch_id,
        "stream_id": s.stream_id, "metric": s.metric,
        "ts": _iso(s.ts), "value": s.value, "unit": s.unit,
        "abs_uc": s.abs_uc, "rel_uc": s.rel_uc,
        "range_id": s.range_id, "segment_id": s.segment_id,
        "solids_fraction_wet": s.solids_fraction_wet,
        "superseded_sample_id": s.superseded_sample_id,
        "received_at": _iso(s.received_at),
    }


def build_snapshot(db: Session, window: Window,
                   freeze_ts: datetime | None = None) -> dict:
    """读取构造一次计算所需的全部输入；freeze_ts 之后到达的样品不进入冻结集。"""
    freeze = freeze_ts or datetime.now(timezone.utc)
    batch = db.get(Batch, window.batch_id)
    topology = db.get(Topology, batch.topology_id)
    segs = (db.query(Segment)
              .filter(Segment.id.in_(window.segment_ids))
              .order_by(Segment.seq).all())
    segs = sorted(segs, key=lambda z: z.seq)
    stream_ids = [st["id"] for st in topology.definition["streams"]]
    t0 = min(s.start_ts for s in segs) - timedelta(hours=2)
    t1 = max(s.end_ts for s in segs) + timedelta(hours=2)

    samples_q = (db.query(Sample)
                   .filter(Sample.batch_id == batch.id,
                           Sample.stream_id.in_(stream_ids),
                           Sample.ts >= t0, Sample.ts <= t1)
                   .order_by(Sample.ts).all())
    samples = [_serialize_sample(s) for s in samples_q]

    inv_q = db.query(TankInventory).filter(
        TankInventory.batch_id == batch.id).all()
    inventories = [{
        "id": q.id, "node_id": q.node_id, "kind": q.kind,
        "segment_id": q.segment_id, "mass_kg": q.mass_kg,
        "fat_fraction_wet": q.fat_fraction_wet,
        "fat_mass_kg": q.fat_mass_kg,
        "abs_uc_mass": q.abs_uc_mass, "rel_uc_mass": q.rel_uc_mass,
        "ts": _iso(q.ts), "cross_batch": q.cross_batch, "note": q.note,
    } for q in inv_q]

    ranges = [{
        "id": r.id, "stream_id": r.stream_id, "metric": r.metric,
        "unit": r.unit, "low": r.low, "high": r.high,
        "label": r.label,
        "active_from": _iso(r.active_from) if r.active_from else None,
        "active_to": _iso(r.active_to) if r.active_to else None,
    } for r in db.query(MeasurementRange)
                 .filter(MeasurementRange.stream_id.in_(stream_ids)).all()]

    return {
        "freeze_ts": _iso(freeze),
        "topology": {
            "code": topology.code,
            "nodes": topology.definition["nodes"],
            "streams": topology.definition["streams"],
        },
        "batch": {"id": batch.id, "code": batch.code},
        "window": {"id": window.id, "label": window.label,
                   "max_gap_s": window.max_gap_s,
                   "extrap_tolerance_s": window.extrap_tolerance_s},
        "segments": [{"id": s.id, "seq": s.seq, "code": s.code,
                      "start_ts": _iso(s.start_ts), "end_ts": _iso(s.end_ts),
                      "boundary_note": s.boundary_note} for s in segs],
        "samples": samples,
        "inventories": inventories,
        "ranges": ranges,
    }


def digest_for(snapshot: dict) -> str:
    """摘要纳入拓扑、段、窗口参数以及冻结时刻前的样品/存量/量程。"""
    frozen_samples = [s for s in snapshot["samples"]
                      if s["received_at"] <= snapshot["freeze_ts"]]
    canonical = {
        "algorithm_version": ALGORITHM_VERSION,
        "topology": snapshot["topology"],
        "segments": snapshot["segments"],
        "window": {k: snapshot["window"][k]
                   for k in ("id", "max_gap_s", "extrap_tolerance_s")},
        "samples": frozen_samples,
        "inventories": sorted(snapshot["inventories"],
                              key=lambda z: (z["node_id"], z["kind"],
                                             z["ts"])),
        "ranges": sorted(snapshot["ranges"],
                         key=lambda z: (z["stream_id"], z["metric"],
                                        z["active_from"] or "")),
    }
    return input_digest(canonical)


def supersede_window_jobs(db: Session, window_id: int) -> None:
    """窗口调整 / 重新入队：旧作业与旧结果立即失去 current 资格。"""
    jobs = db.query(Job).filter(Job.window_id == window_id,
                                Job.is_current.is_(True)).all()
    for j in jobs:
        j.is_current = False
        if j.status in ("queued", "running"):
            j.status = "superseded"
    db.query(Result).filter(Result.window_id == window_id,
                            Result.is_current.is_(True)).update(
        {"is_current": False})


def enqueue_job(db: Session, window: Window) -> Job:
    snapshot = build_snapshot(db, window)
    digest = digest_for(snapshot)
    snapshot_for_job = dict(snapshot)
    snapshot_for_job["samples"] = [s for s in snapshot["samples"]
                                   if s["received_at"] <= snapshot["freeze_ts"]]
    supersede_window_jobs(db, window.id)
    job = Job(window_id=window.id, status="queued", input_digest=digest,
              input_snapshot=snapshot_for_job,
              algorithm_version=ALGORITHM_VERSION, is_current=True)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def input_summary(db: Session, window: Window, result: Result) -> dict:
    """签署用输入摘要（人类可读 + 机器摘要）。"""
    snap = result.payload  # payload 保留了 digest/版本；摘要快照取自 job
    job = db.get(Job, result.job_id)
    s = job.input_snapshot
    return {
        "window_id": window.id, "window_label": window.label,
        "batch_code": s["batch"]["code"], "topology_code": s["topology"]["code"],
        "segments": [g["code"] for g in s["segments"]],
        "n_samples": len(s["samples"]),
        "n_inventories": len(s["inventories"]),
        "max_gap_s": window.max_gap_s,
        "extrap_tolerance_s": window.extrap_tolerance_s,
        "freeze_ts": s["freeze_ts"],
        "input_digest": result.digest,
        "algorithm_version": result.algorithm_version,
        "late_excluded_sample_ids":
            snap.get("audit", {}).get("late_excluded_sample_ids", []),
    }


def current_result(db: Session, window_id: int) -> Result | None:
    return (db.query(Result)
              .filter(Result.window_id == window_id,
                      Result.is_current.is_(True))
              .order_by(Result.id.desc()).first())


def ensure_calc_version(db: Session) -> None:
    from app.core.version import ALGORITHM_NOTES
    from app.models import CalcVersion
    if not db.query(CalcVersion).filter_by(version=ALGORITHM_VERSION).first():
        db.add(CalcVersion(version=ALGORITHM_VERSION, notes=ALGORITHM_NOTES))
        db.commit()
