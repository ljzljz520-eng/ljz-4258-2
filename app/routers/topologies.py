from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.balance import validate_topology
from app.database import get_db
from app.models import Batch, Topology
from app.schemas import TopologyIn, TopologyOut

router = APIRouter(prefix="/api/topologies", tags=["topologies"])


@router.post("", response_model=TopologyOut, status_code=201)
def create_topology(body: TopologyIn, db: Session = Depends(get_db)):
    if db.query(Topology).filter_by(code=body.code).first():
        raise HTTPException(409, f"topology {body.code} exists")
    definition = {
        "nodes": [n.model_dump() for n in body.nodes],
        "streams": [s.model_dump() for s in body.streams],
    }
    errs = validate_topology(definition["nodes"], definition["streams"])
    if errs:
        raise HTTPException(422, {"errors": errs})
    t = Topology(code=body.code, name=body.name, definition=definition)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@router.get("", response_model=list[TopologyOut])
def list_topologies(db: Session = Depends(get_db)):
    return db.query(Topology).order_by(Topology.id).all()


@router.get("/{tid}", response_model=TopologyOut)
def get_topology(tid: int, db: Session = Depends(get_db)):
    t = db.get(Topology, tid)
    if t is None:
        raise HTTPException(404, "topology not found")
    return t
