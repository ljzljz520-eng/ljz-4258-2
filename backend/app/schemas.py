from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator


class ORMModel(BaseModel):
    model_config = {"from_attributes": True}


class BatchCreate(BaseModel):
    code: str
    name: str
    status: str = "draft"


class BatchRead(ORMModel):
    id: int
    code: str
    name: str
    status: str
    current_version: int


class SegmentCreate(BaseModel):
    code: str
    kind: str = "other"
    window_start: datetime
    window_end: datetime

    @field_validator("window_end")
    @classmethod
    def end_after_start(cls, v, info):
        start = info.data.get("window_start")
        if start and v <= start:
            raise ValueError("window_end must be after window_start")
        return v


class SegmentUpdate(BaseModel):
    kind: str | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None


class SegmentRead(ORMModel):
    id: int
    batch_id: int
    code: str
    kind: str
    window_start: datetime
    window_end: datetime
    version: int


class NodeCreate(BaseModel):
    code: str
    name: str
    node_type: Literal["process", "tank", "source", "sink"]
    include_inventory: bool = False


class NodeRead(ORMModel):
    id: int
    segment_id: int
    code: str
    name: str
    node_type: str
    include_inventory: bool


class EdgeCreate(BaseModel):
    code: str
    name: str = ""
    source_node_id: int
    target_node_id: int
    cross_batch: bool = False


class EdgeRead(ORMModel):
    id: int
    code: str
    name: str
    source_node_id: int
    target_node_id: int
    cross_batch: bool


class MeasurementCreate(BaseModel):
    target_type: Literal["edge", "node"]
    target_id: int
    metric: Literal[
        "volume_flow", "mass_flow", "density", "fat_fraction",
        "solids_fraction", "mass", "fat_mass"
    ]
    value: float = Field(ge=0)
    unit: str
    basis: Literal["wet", "dry"] = "wet"
    uncertainty_type: Literal["absolute", "relative", "stddev", "expanded_95"] = "stddev"
    uncertainty_value: float = Field(ge=0)
    period_start: datetime
    period_end: datetime | None = None
    range_code: str | None = None
    note: str | None = None


class MeasurementRead(ORMModel):
    id: int
    segment_id: int
    target_type: str
    target_id: int
    metric: str
    value: float
    unit: str
    basis: str
    uncertainty_type: str
    uncertainty_value: float
    period_start: datetime
    period_end: datetime | None
    observed_at: datetime
    range_code: str | None
    note: str | None


class JobRead(ORMModel):
    id: int
    segment_id: int
    status: str
    input_version: int
    algorithm_version: str
    input_summary: str
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    worker_id: str | None = None


class SignoffCreate(BaseModel):
    engineer: str
    note: str | None = None


class SignoffRead(ORMModel):
    id: int
    job_id: int
    engineer: str
    input_summary: str
    algorithm_version: str
    signature: str
    note: str | None
    created_at: datetime


class ClaimJob(BaseModel):
    worker_id: str
