from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Batch, Segment, Topology
from app.schemas import BatchIn, BatchOut

router = APIRouter(prefix="/api/batches", tags=["batches"])


@router.post("", response_model=BatchOut, status_code=201)
def create_batch(body: BatchIn, db: Session = Depends(get_db)):
    if db.get(Topology, body.topology_id) is None:
        raise HTTPException(404, "topology not found")
    if db.query(Batch).filter_by(code=body.code).first():
        raise HTTPException(409, f"batch {body.code} exists")
    seqs = [s.seq for s in body.segments]
    if len(seqs) != len(set(seqs)):
        raise HTTPException(422, "duplicate segment seq")
    b = Batch(topology_id=body.topology_id, code=body.code, note=body.note)
    db.add(b)
    db.flush()
    for s in body.segments:
        if s.end_ts <= s.start_ts:
            raise HTTPException(422, f"segment {s.code} end<=start")
        db.add(Segment(batch_id=b.id, seq=s.seq, code=s.code,
                       start_ts=s.start_ts, end_ts=s.end_ts,
                       boundary_note=s.boundary_note))
    db.commit()
    db.refresh(b)
    return b


@router.get("", response_model=list[BatchOut])
def list_batches(db: Session = Depends(get_db)):
    return db.query(Batch).order_by(Batch.id).all()


@router.get("/{bid}", response_model=BatchOut)
def get_batch(bid: int, db: Session = Depends(get_db)):
    b = db.get(Batch, bid)
    if b is None:
        raise HTTPException(404, "batch not found")
    return b
