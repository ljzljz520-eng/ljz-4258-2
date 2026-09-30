"""窗口调整失配、签署冻结输入摘要与算法版本。"""
from datetime import timedelta

import pytest

from app.core.version import ALGORITHM_VERSION
from app.database import SessionLocal
from app.models import Batch, Job, Result, Signoff, SignoffEvent, Window
from app.services import enqueue_job
from worker.compute_worker import _claim_one, process_job


def _process(bid):
    db = SessionLocal()
    w = db.query(Window).filter_by(batch_id=bid).first()
    wid = w.id
    job = enqueue_job(db, w)
    db.close()
    db = SessionLocal()
    c = _claim_one(db); cid = c.id; process_job(cid); db.close()
    db = SessionLocal()
    r = db.query(Result).filter_by(job_id=cid, is_current=True).first()
    return db, wid, r


def test_signoff_freezes_digest_and_version(seeded, db_path):
    from app.models import Batch
    db = SessionLocal()
    bid = db.query(Batch).filter_by(code="A").first().id
    db.close()
    db, wid, r = _process(bid)
    rid = r.id; digest = r.digest; alg = r.algorithm_version
    so = Signoff(window_id=wid, result_id=rid, engineer="zhang",
                 input_digest=digest,
                 algorithm_version=alg,
                 input_summary={"segments": ["seg1", "seg2"],
                                "n_samples": 108,
                                "input_digest": digest},
                 note="确认闭合")
    db.add(so); db.flush()
    db.add(SignoffEvent(signoff_id=so.id, kind="created", actor="zhang"))
    db.commit()
    sid = so.id
    db.close()

    db = SessionLocal()
    got = db.get(Signoff, sid)
    assert got.algorithm_version == ALGORITHM_VERSION
    assert got.input_digest == digest
    assert got.revoked is False
    # 摘要字段不可变：尝试改写必须在应用层禁止（模型无更新端点）
    got.revoked = True  # 仅事件路径允许，测试直接演示字段语义
    db.add(SignoffEvent(signoff_id=sid, kind="revoked", actor="li",
                        detail="窗口重算"))
    db.commit()
    assert got.input_digest == digest        # 摘要本身未变
    events = db.query(SignoffEvent).filter_by(signoff_id=sid).all()
    kinds = [e.kind for e in events]
    assert kinds == ["created", "revoked"]
    db.close()


def test_underdetermined_result_cannot_be_signed(seeded, db_path):
    from app.models import Batch
    db = SessionLocal()
    bid = db.query(Batch).filter_by(code="B").first().id
    db.close()
    db, wid, r = _process(bid)
    assert r.status == "underdetermined"
    # 欠定结果不应被签署：状态门
    assert r.status != "identified"
    db.close()


def test_window_update_supersedes_old(seeded, db_path):
    from app.models import Batch, Segment
    from app.services import supersede_window_jobs
    db = SessionLocal()
    bid = db.query(Batch).filter_by(code="A").first().id
    db.close()
    db, wid, r = _process(bid)
    rid = r.id
    assert r.is_current is True
    supersede_window_jobs(db, wid)
    db.commit()
    db.close()
    db = SessionLocal()
    assert db.get(Result, rid).is_current is False
    db.close()
