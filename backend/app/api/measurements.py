from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AuditEvent, Batch, Edge, Measurement, Node, Segment
from app.db.session import get_db
from app.schemas import MeasurementCreate, MeasurementRead
from app.services.alignment import build_intervals
from app.services.units import factor

router = APIRouter(prefix="/api/segments/{segment_id}", tags=["measurements"])
POINT_METRICS = {"density", "fat_fraction", "solids_fraction"}


def _seg(db, segment_id):
    seg = db.get(Segment, segment_id)
    if not seg:
        raise HTTPException(404, "segment not found")
    return seg


def _bump(seg: Segment, db: Session):
    seg.version += 1
    db.get(Batch, seg.batch_id).current_version += 1


def _validate_target(db: Session, seg: Segment, body: MeasurementCreate):
    try:
        factor(body.unit)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if body.target_type == "edge":
        edge = db.get(Edge, body.target_id)
        if not edge:
            raise HTTPException(404, "edge not found")
        nodes = [edge.source_node_id, edge.target_node_id]
        if not db.scalar(select(Node).where(Node.segment_id == seg.id, Node.id.in_(nodes))):
            raise HTTPException(422, "edge is not connected to this segment")
    else:
        node = db.get(Node, body.target_id)
        if not node or node.segment_id != seg.id:
            raise HTTPException(404, "node not found in this segment")
    if body.basis == "dry" and body.metric != "fat_fraction":
        raise HTTPException(422, "only fat_fraction supports dry basis")
    if body.period_end and body.period_end <= body.period_start:
        raise HTTPException(422, "period_end must be after period_start")
    if body.metric in POINT_METRICS and body.period_end is not None:
        # Point instruments can explicitly be point records; end is assigned by
        # successor during alignment.
        raise HTTPException(422, "point metrics must omit period_end")
    needs_interval = body.target_type == "edge" and body.metric in {"mass", "fat_mass"}
    if body.metric not in POINT_METRICS and needs_interval and body.period_end is None:
        raise HTTPException(422, f"{body.metric} requires period_end")
    if body.target_type == "node" and body.metric in {"mass", "fat_mass"} and body.period_end is not None:
        raise HTTPException(422, "node inventory observations are boundary points; omit period_end")


def _check_overlap(db: Session, seg: Segment, body: MeasurementCreate):
    rows = db.scalars(select(Measurement).where(
        Measurement.segment_id == seg.id,
        Measurement.target_type == body.target_type,
        Measurement.target_id == body.target_id,
        Measurement.metric == body.metric,
    )).all()
    # Persist a transient row into the ORM-independent list to test new interval.
    class Row:
        def __init__(self, id, start, end):
            self.id=id; self.metric=body.metric; self.period_start=start; self.period_end=end
    start = body.period_start
    point_metrics = POINT_METRICS | ({"mass", "fat_mass"} if body.target_type == "node" else set())
    if body.metric in point_metrics:
        timestamps = sorted([r.period_start for r in rows] + [start])
        if len(timestamps) != len(set(timestamps)):
            raise HTTPException(409, "duplicate point timestamp for same target and metric")
        return
    for r in rows:
        if start < r.period_end and r.period_start < body.period_end:
            raise HTTPException(409, f"overlaps measurement {r.id}")


@router.post("/measurements", response_model=MeasurementRead, status_code=201)
def create_measurement(segment_id: int, body: MeasurementCreate, db: Session = Depends(get_db)):
    seg = _seg(db, segment_id)
    _validate_target(db, seg, body)
    _check_overlap(db, seg, body)
    m = Measurement(segment_id=segment_id, **body.model_dump())
    db.add(m)
    _bump(seg, db)
    db.add(AuditEvent(entity_type="segment", entity_id=segment_id, action="add_measurement",
                      detail={"target": f"{body.target_type}:{body.target_id}", "metric": body.metric}))
    db.commit()
    db.refresh(m)
    return m


@router.get("/measurements", response_model=list[MeasurementRead])
def list_measurements(segment_id: int, db: Session = Depends(get_db)):
    _seg(db, segment_id)
    local_nodes = [n.id for n in db.scalars(select(Node).where(Node.segment_id == segment_id)).all()]
    edge_ids = [e.id for e in db.scalars(select(Edge).where(
        Edge.source_node_id.in_(local_nodes) | Edge.target_node_id.in_(local_nodes)
    )).all()] if local_nodes else []
    stmt = select(Measurement).where(Measurement.segment_id == segment_id)
    rows = list(db.scalars(stmt).all())
    # Include cross-batch edge measurements owned by neighboring segments but
    # connected to this segment.
    if edge_ids:
        rows += list(db.scalars(select(Measurement).where(
            Measurement.target_type == "edge", Measurement.target_id.in_(edge_ids),
            Measurement.segment_id != segment_id
        )).all())
    return sorted(rows, key=lambda m: (m.target_type, m.target_id, m.metric, m.period_start))
