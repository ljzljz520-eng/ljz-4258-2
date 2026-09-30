"""迟到样不得覆盖当前图；窗口调整使依赖结果过期；旧任务晚到。"""
from datetime import timedelta

import pytest

from app.database import SessionLocal
from app.models import Job, Result, Sample, Window
from app.services import (build_snapshot, digest_for, enqueue_job)
from seed_data import T0
from worker.compute_worker import _claim_one, process_job


def _run_current(code):
    db = SessionLocal()
    from app.models import Batch
    bid = db.query(Batch).filter_by(code=code).first().id
    w = db.query(Window).filter_by(batch_id=bid).first()
    wid = w.id
    job = enqueue_job(db, w)
    db.close()
    db = SessionLocal()
    claimed = _claim_one(db)
    claimed_id = claimed.id
    process_job(claimed_id)
    db.close()
    db = SessionLocal()
    r = (db.query(Result).filter_by(job_id=claimed_id,
                                    is_current=True).first())
    return db, wid, claimed_id, r


def test_late_sample_marks_job_stale_and_keeps_graph(seeded):
    from app.models import Batch
    db, wid, jid, r = _run_current("A")
    assert r is not None and r.status == "identified"
    old_digest = r.digest
    old_result_id = r.id
    batch_id = db.query(Batch).filter_by(code="A").first().id

    # 工程师调整窗口后，一个迟到样到达（received_at 在冻结之后）
    late = Sample(batch_id=batch_id,
                  stream_id="F1", segment_id=None,
                  ts=T0 + timedelta(minutes=30), metric="density",
                  value=1.05, unit="kg/L", rel_uc=0.002,
                  received_at=T0 + timedelta(hours=5))
    db.add(late)
    db.commit()

    # 新入队作业：旧结果被标记为非当前（即使旧作业晚到完成也不覆盖）
    w = db.get(Window, wid)
    new_job = enqueue_job(db, w)
    new_job_id = new_job.id
    db.commit()
    db.close()

    # 旧作业（已完成）的结果仍然存在但 is_current=False
    db = SessionLocal()
    old = db.get(Result, old_result_id)
    assert old.is_current is False
    cur = db.query(Result).filter(Result.window_id == wid,
                                  Result.is_current.is_(True)).all()
    # 新作业还没跑，当前图仍为空（不会被旧数据冒充）
    assert cur == []
    db.close()


def test_worker_rejects_digest_drift(seeded):
    """作业入队后输入变化，worker 检测摘要漂移 -> stale，不写结果。"""
    from app.models import Batch
    db = SessionLocal()
    bid = db.query(Batch).filter_by(code="B").first().id
    w = db.query(Window).filter_by(batch_id=bid).first()
    job = enqueue_job(db, w)
    job_id = job.id
    db.close()

    # 在 worker 运行前插入一条“及时”的新 REC 样本（改变摘要）
    db = SessionLocal()
    db.add(Sample(batch_id=bid, stream_id="REC",
                  ts=T0 + timedelta(minutes=20), metric="density",
                  value=1.0, unit="kg/L", rel_uc=0.002,
                  received_at=T0 + timedelta(minutes=20)))
    db.commit()
    db.close()

    db = SessionLocal()
    claimed = _claim_one(db)
    status = process_job(claimed.id)
    db.close()
    assert status == "stale"
    db = SessionLocal()
    r = db.query(Result).filter_by(job_id=job_id).first()
    assert r is None
    j = db.get(Job, job_id)
    assert "input changed" in j.error
    db.close()


def test_superseded_job_not_current(seeded):
    from app.models import Batch
    db = SessionLocal()
    bid = db.query(Batch).filter_by(code="A").first().id
    w = db.query(Window).filter_by(batch_id=bid).first()
    j1 = enqueue_job(db, w)
    j1_id = j1.id
    j2 = enqueue_job(db, w)   # 立即重新入队
    j2_id = j2.id
    db.close()
    db = SessionLocal()
    assert db.get(Job, j1_id).is_current is False
    assert db.get(Job, j2_id).is_current is True
    # 旧 queued 作业被置 superseded，claim 不会再取它
    claimed = _claim_one(db)
    assert claimed.id == j2_id
    db.close()


def test_late_sample_excluded_from_frozen_snapshot(seeded):
    """迟到样进入数据库，但冻结快照不纳入；audit 列出其 id。"""
    from app.models import Batch
    db = SessionLocal()
    bid = db.query(Batch).filter_by(code="A").first().id
    late = Sample(batch_id=bid, stream_id="F2",
                  ts=T0 + timedelta(minutes=10), metric="density",
                  value=1.0, unit="kg/L",
                  received_at=T0 + timedelta(hours=24))
    db.add(late); db.commit()
    sid = late.id
    w = db.query(Window).filter_by(batch_id=bid).first()
    snap = build_snapshot(db, w, freeze_ts=T0 + timedelta(hours=3))
    payload_snap = dict(snap)
    from app.core.engine import compute
    res = compute(payload_snap, digest=digest_for(snap))
    assert sid in res["audit"]["late_excluded_sample_ids"]
    db.close()
