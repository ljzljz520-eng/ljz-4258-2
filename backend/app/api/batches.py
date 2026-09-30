from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AuditEvent, Batch, Segment
from app.db.session import get_db
from app.schemas import BatchCreate, BatchRead, SegmentCreate, SegmentRead, SegmentUpdate

router = APIRouter(prefix="/api/batches", tags=["batches"])


@router.post("", response_model=BatchRead, status_code=201)
def create_batch(body: BatchCreate, db: Session = Depends(get_db)):
    if db.scalar(select(Batch).where(Batch.code == body.code)):
        raise HTTPException(409, "batch code already exists")
    batch = Batch(**body.model_dump())
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return batch


@router.get("", response_model=list[BatchRead])
def list_batches(db: Session = Depends(get_db)):
    return db.scalars(select(Batch).order_by(Batch.id)).all()


@router.get("/{batch_id}", response_model=BatchRead)
def get_batch(batch_id: int, db: Session = Depends(get_db)):
    b = db.get(Batch, batch_id)
    if not b:
        raise HTTPException(404, "batch not found")
    return b


@router.post("/{batch_id}/segments", response_model=SegmentRead, status_code=201)
def create_segment(batch_id: int, body: SegmentCreate, db: Session = Depends(get_db)):
    batch = db.get(Batch, batch_id)
    if not batch:
        raise HTTPException(404, "batch not found")
    exists = db.scalar(select(Segment).where(Segment.batch_id == batch_id, Segment.code == body.code))
    if exists:
        raise HTTPException(409, "segment code already exists in batch")
    seg = Segment(batch_id=batch_id, **body.model_dump())
    db.add(seg)
    batch.current_version += 1
    db.add(AuditEvent(entity_type="batch", entity_id=batch_id, action="create_segment",
                      detail={"segment": body.code}))
    db.commit()
    db.refresh(seg)
    return seg


@router.get("/{batch_id}/segments", response_model=list[SegmentRead])
def list_segments(batch_id: int, db: Session = Depends(get_db)):
    return db.scalars(select(Segment).where(Segment.batch_id == batch_id).order_by(Segment.id)).all()


@router.patch("/segments/{segment_id}", response_model=SegmentRead)
def update_segment(segment_id: int, body: SegmentUpdate, db: Session = Depends(get_db)):
    seg = db.get(Segment, segment_id)
    if not seg:
        raise HTTPException(404, "segment not found")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(seg, k, v)
    if seg.window_end <= seg.window_start:
        raise HTTPException(422, "window_end must be after window_start")
    seg.version += 1
    batch = db.get(Batch, seg.batch_id)
    batch.current_version += 1
    db.add(AuditEvent(entity_type="segment", entity_id=seg.id, action="update_stable_window",
                      detail={"version": seg.version, "changes": data}))
    db.commit()
    db.refresh(seg)
    return seg
