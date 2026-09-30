from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AuditEvent, Batch, Edge, Node, Segment
from app.db.session import get_db
from app.schemas import EdgeCreate, EdgeRead, NodeCreate, NodeRead

router = APIRouter(prefix="/api/segments/{segment_id}", tags=["topology"])


def _segment_or_404(db: Session, segment_id: int) -> Segment:
    seg = db.get(Segment, segment_id)
    if not seg:
        raise HTTPException(404, "segment not found")
    return seg


@router.post("/nodes", response_model=NodeRead, status_code=201)
def create_node(segment_id: int, body: NodeCreate, db: Session = Depends(get_db)):
    seg = _segment_or_404(db, segment_id)
    if db.scalar(select(Node).where(Node.segment_id == segment_id, Node.code == body.code)):
        raise HTTPException(409, "node code already exists in segment")
    node = Node(segment_id=segment_id, **body.model_dump())
    db.add(node)
    seg.version += 1
    db.get(Batch, seg.batch_id).current_version += 1
    db.add(AuditEvent(entity_type="segment", entity_id=segment_id, action="create_node", detail={"node": body.code}))
    db.commit()
    db.refresh(node)
    return node


@router.get("/nodes", response_model=list[NodeRead])
def list_nodes(segment_id: int, db: Session = Depends(get_db)):
    _segment_or_404(db, segment_id)
    local = db.scalars(select(Node).where(Node.segment_id == segment_id)).all()
    local_ids = {n.id for n in local}
    edges = db.scalars(select(Edge).where(Edge.source_node_id.in_(local_ids) | Edge.target_node_id.in_(local_ids))).all()
    ids = local_ids | {x for e in edges for x in (e.source_node_id, e.target_node_id)}
    if not ids:
        return []
    return db.scalars(select(Node).where(Node.id.in_(ids)).order_by(Node.id)).all()


@router.post("/edges", response_model=EdgeRead, status_code=201)
def create_edge(segment_id: int, body: EdgeCreate, db: Session = Depends(get_db)):
    seg = _segment_or_404(db, segment_id)
    if db.scalar(select(Edge).where(Edge.code == body.code)):
        raise HTTPException(409, "edge code already exists")
    source = db.get(Node, body.source_node_id)
    target = db.get(Node, body.target_node_id)
    if not source or not target:
        raise HTTPException(404, "source or target node not found")
    edge = Edge(**body.model_dump())
    db.add(edge)
    seg.version += 1
    db.get(Batch, seg.batch_id).current_version += 1
    db.add(AuditEvent(entity_type="segment", entity_id=segment_id, action="create_edge",
                      detail={"edge": body.code, "source": source.code, "target": target.code}))
    db.commit()
    db.refresh(edge)
    return edge


@router.get("/edges", response_model=list[EdgeRead])
def list_edges(segment_id: int, db: Session = Depends(get_db)):
    _segment_or_404(db, segment_id)
    local_ids = {n.id for n in db.scalars(select(Node).where(Node.segment_id == segment_id)).all()}
    if not local_ids:
        return []
    return db.scalars(
        select(Edge).where(Edge.source_node_id.in_(local_ids) | Edge.target_node_id.in_(local_ids)).order_by(Edge.id)
    ).all()
