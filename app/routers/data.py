"""样品 / 罐存量 / 量程录入。迟到样本与普通样本走同一端点，
由 received_at（服务端时间）在冻结/失配逻辑中区分，禁止回填历史时间戳冒充及时测量。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.units import (
    DENSITY_TO_KG_L,
    FAT_FRACTION,
    FLOW_TO_LPS,
    convert_fat_sample,
)
from app.database import get_db
from app.models import MeasurementRange, Sample, TankInventory
from app.schemas import InventoryIn, InventoryOut, RangeIn, RangeOut, SampleIn, SampleOut

router = APIRouter(prefix="/api", tags=["data"])

_ALLOWED_UNITS = {
    "flow": set(FLOW_TO_LPS),
    "density": set(DENSITY_TO_KG_L),
    "fat": set(FAT_FRACTION) | {"fraction_dry", "percent_dry", "g_per_100g_dry"},
}


@router.post("/samples", response_model=SampleOut, status_code=201)
def add_sample(body: SampleIn, db: Session = Depends(get_db)):
    if body.unit not in _ALLOWED_UNITS[body.metric]:
        raise HTTPException(422, f"unit {body.unit} invalid for {body.metric}")
    if body.metric == "fat" and body.unit in (
            "fraction_dry", "percent_dry", "g_per_100g_dry"):
        try:
            convert_fat_sample(body.value, body.unit, body.solids_fraction_wet)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
    if body.range_id and db.get(MeasurementRange, body.range_id) is None:
        raise HTTPException(404, "range_id not found")
    s = Sample(**body.model_dump())
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@router.get("/samples", response_model=list[SampleOut])
def list_samples(stream_id: str | None = None,
                 segment_id: int | None = None,
                 batch_id: int | None = None,
                 db: Session = Depends(get_db)):
    q = db.query(Sample)
    if stream_id:
        q = q.filter(Sample.stream_id == stream_id)
    if segment_id:
        q = q.filter(Sample.segment_id == segment_id)
    if batch_id:
        q = q.filter(Sample.batch_id == batch_id)
    return q.order_by(Sample.ts, Sample.id).all()


@router.post("/ranges", response_model=RangeOut, status_code=201)
def add_range(body: RangeIn, db: Session = Depends(get_db)):
    if body.high <= body.low:
        raise HTTPException(422, "range high must exceed low")
    r = MeasurementRange(**body.model_dump())
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


@router.get("/ranges", response_model=list[RangeOut])
def list_ranges(stream_id: str | None = None, db: Session = Depends(get_db)):
    q = db.query(MeasurementRange)
    if stream_id:
        q = q.filter(MeasurementRange.stream_id == stream_id)
    return q.order_by(MeasurementRange.stream_id, MeasurementRange.metric).all()


@router.post("/batches/{batch_id}/inventories",
             response_model=InventoryOut, status_code=201)
def add_inventory(batch_id: int, body: InventoryIn, db: Session = Depends(get_db)):
    if not (0.0 <= body.fat_fraction_wet <= 1.0):
        raise HTTPException(422, "fat_fraction_wet must be within [0,1]")
    inv = TankInventory(batch_id=batch_id, **body.model_dump())
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return inv


@router.get("/batches/{batch_id}/inventories",
            response_model=list[InventoryOut])
def list_inventories(batch_id: int, db: Session = Depends(get_db)):
    return (db.query(TankInventory)
              .filter_by(batch_id=batch_id)
              .order_by(TankInventory.ts).all())
