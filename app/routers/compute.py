"""窗口、作业、结果、签署。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.engine import compute
from app.database import get_db
from app.models import Batch, Job, Result, Segment, Signoff, SignoffEvent, Window
from app.schemas import (
    JobOut,
    Message,
    SignoffIn,
    SignoffOut,
    WindowIn,
    WindowOut,
)
from app.services import (
    build_snapshot,
    current_result,
    digest_for,
    enqueue_job,
    input_summary,
    supersede_window_jobs,
)

router = APIRouter(prefix="/api", tags=["compute"])


def _load_window(db: Session, window_id: int) -> Window:
    w = db.get(Window, window_id)
    if w is None:
        raise HTTPException(404, "window not found")
    return w


@router.post("/batches/{batch_id}/windows",
             response_model=WindowOut, status_code=201)
def create_window(batch_id: int, body: WindowIn, db: Session = Depends(get_db)):
    if db.get(Batch, batch_id) is None:
        raise HTTPException(404, "batch not found")
    segs = db.query(Segment).filter(Segment.id.in_(body.segment_ids)).all()
    if len(segs) != len(set(body.segment_ids)):
        raise HTTPException(422, "some segments not found")
    if any(s.batch_id != batch_id for s in segs):
        raise HTTPException(422, "segment belongs to another batch")
    seq = sorted(s.seq for s in segs)
    if seq != list(range(seq[0], seq[-1] + 1)):
        raise HTTPException(422, "segments must be contiguous (no gaps)")
    w = Window(batch_id=batch_id, label=body.label, segment_ids=body.segment_ids,
               max_gap_s=body.max_gap_s,
               extrap_tolerance_s=body.extrap_tolerance_s)
    db.add(w)
    db.commit()
    db.refresh(w)
    return w


@router.get("/batches/{batch_id}/windows", response_model=list[WindowOut])
def list_windows(batch_id: int, db: Session = Depends(get_db)):
    return db.query(Window).filter_by(batch_id=batch_id).order_by(Window.id).all()


@router.put("/windows/{window_id}", response_model=WindowOut)
def update_window(window_id: int, body: WindowIn, db: Session = Depends(get_db)):
    """工程师调整稳定窗口：旧窗口/作业/结果立即失去 current（依赖计算过期）。"""
    w = _load_window(db, window_id)
    segs = db.query(Segment).filter(Segment.id.in_(body.segment_ids)).all()
    if len(segs) != len(set(body.segment_ids)) or any(
            s.batch_id != w.batch_id for s in segs):
        raise HTTPException(422, "invalid segment selection")
    new = Window(batch_id=w.batch_id, label=body.label,
                 segment_ids=body.segment_ids, max_gap_s=body.max_gap_s,
                 extrap_tolerance_s=body.extrap_tolerance_s,
                 superseded_by=w.id)
    db.add(new)
    supersede_window_jobs(db, w.id)
    db.flush()
    db.commit()
    db.refresh(new)
    return new


@router.post("/windows/{window_id}/preview")
def preview(window_id: int, db: Session = Depends(get_db)):
    """不入队的试算（与 worker 同一路径），用于编辑流程即时反馈。"""
    w = _load_window(db, window_id)
    snap = build_snapshot(db, w)
    digest = digest_for(snap)
    return compute(snap, digest=digest)


@router.post("/windows/{window_id}/jobs", response_model=JobOut, status_code=202)
def create_job(window_id: int, db: Session = Depends(get_db)):
    w = _load_window(db, window_id)
    return enqueue_job(db, w)


@router.get("/windows/{window_id}/jobs", response_model=list[JobOut])
def list_jobs(window_id: int, db: Session = Depends(get_db)):
    return (db.query(Job).filter_by(window_id=window_id)
              .order_by(Job.id.desc()).all())


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: Session = Depends(get_db)):
    j = db.get(Job, job_id)
    if j is None:
        raise HTTPException(404, "job not found")
    return j


@router.get("/windows/{window_id}/result")
def get_result(window_id: int, db: Session = Depends(get_db)):
    _load_window(db, window_id)
    r = current_result(db, window_id)
    if r is None:
        raise HTTPException(404, "no current result yet")
    return {"id": r.id, "job_id": r.job_id, "window_id": r.window_id,
            "digest": r.digest, "algorithm_version": r.algorithm_version,
            "status": r.status, "created_at": r.created_at,
            "payload": r.payload}


@router.get("/results/{result_id}")
def get_result_by_id(result_id: int, db: Session = Depends(get_db)):
    r = db.get(Result, result_id)
    if r is None:
        raise HTTPException(404, "result not found")
    return {"id": r.id, "job_id": r.job_id, "window_id": r.window_id,
            "digest": r.digest, "algorithm_version": r.algorithm_version,
            "status": r.status, "is_current": r.is_current,
            "created_at": r.created_at, "payload": r.payload}


@router.post("/results/{result_id}/signoff",
             response_model=SignoffOut, status_code=201)
def signoff(result_id: int, body: SignoffIn, db: Session = Depends(get_db)):
    r = db.get(Result, result_id)
    if r is None:
        raise HTTPException(404, "result not found")
    if r.status != "identified":
        raise HTTPException(409, "only identified (fully determined) results "
                                 "can be signed off")
    w = db.get(Window, r.window_id)
    # 必须是当前结果才可签署；历史结果仅供查看
    if not r.is_current or current_result(db, w.id) is None or \
            current_result(db, w.id).id != r.id:
        raise HTTPException(409, "result is not current; sign off on the "
                                 "latest result instead")
    so = Signoff(window_id=w.id, result_id=r.id, engineer=_engineer_check(body.engineer),
                 input_digest=r.digest, algorithm_version=r.algorithm_version,
                 input_summary=input_summary(db, w, r), note=body.note)
    db.add(so)
    db.flush()
    db.add(SignoffEvent(signoff_id=so.id, kind="created",
                        actor=body.engineer, detail="signed off"))
    db.commit()
    db.refresh(so)
    return so


def _engineer_check(v: str) -> str:
    if not v or not v.strip():
        raise HTTPException(422, "engineer required")
    return v.strip()


@router.get("/windows/{window_id}/signoffs",
            response_model=list[SignoffOut])
def list_signoffs(window_id: int, db: Session = Depends(get_db)):
    _load_window(db, window_id)
    return (db.query(Signoff).filter_by(window_id=window_id)
              .order_by(Signoff.id.desc()).all())


@router.post("/signoffs/{signoff_id}/revoke",
             response_model=SignoffOut)
def revoke_signoff(signoff_id: int, body: SignoffIn,
                   db: Session = Depends(get_db)):
    so = db.get(Signoff, signoff_id)
    if so is None:
        raise HTTPException(404, "signoff not found")
    if so.revoked:
        raise HTTPException(409, "already revoked")
    # 只追加事件 + 翻转 revoked；摘要与版本字段永不改写
    so.revoked = True
    db.add(SignoffEvent(signoff_id=so.id, kind="revoked",
                        actor=_engineer_check(body.engineer),
                        detail=body.note or "revoked"))
    db.commit()
    db.refresh(so)
    return so
