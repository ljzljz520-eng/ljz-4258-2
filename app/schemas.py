"""Pydantic v2 API 模式。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- 拓扑 ----------
class Node(BaseModel):
    id: str
    type: str = Field(pattern="^(source|separator|tank|blender|sink)$")
    name: str = ""


class Stream(BaseModel):
    id: str
    source: str
    sink: str
    name: str = ""
    carries_fat: bool = True


class TopologyIn(BaseModel):
    code: str
    name: str
    nodes: list[Node]
    streams: list[Stream]


class TopologyOut(ORMModel):
    id: int
    code: str
    name: str
    definition: dict


# ---------- 批 / 段 ----------
class SegmentIn(BaseModel):
    seq: int
    code: str
    start_ts: datetime
    end_ts: datetime
    boundary_note: str = ""


class SegmentOut(ORMModel):
    id: int
    seq: int
    code: str
    start_ts: datetime
    end_ts: datetime
    boundary_note: str = ""


class BatchIn(BaseModel):
    topology_id: int
    code: str
    note: str = ""
    segments: list[SegmentIn]


class BatchOut(ORMModel):
    id: int
    topology_id: int
    code: str
    note: str
    segments: list[SegmentOut]


# ---------- 量程 ----------
class RangeIn(BaseModel):
    stream_id: str
    metric: str = Field(pattern="^(flow|density|fat)$")
    unit: str
    low: float
    high: float
    active_from: datetime | None = None
    active_to: datetime | None = None
    label: str = ""


class RangeOut(ORMModel):
    id: int
    stream_id: str
    metric: str
    unit: str
    low: float
    high: float
    label: str


# ---------- 样品 ----------
class SampleIn(BaseModel):
    stream_id: str
    ts: datetime
    metric: str = Field(pattern="^(flow|density|fat)$")
    value: float
    unit: str
    abs_uc: float | None = None
    rel_uc: float | None = None
    range_id: int | None = None
    segment_id: int | None = None
    solids_fraction_wet: float | None = None
    superseded_sample_id: int | None = None


class SampleOut(ORMModel):
    id: int
    stream_id: str
    segment_id: int | None
    ts: datetime
    metric: str
    value: float
    unit: str
    abs_uc: float | None
    rel_uc: float | None
    range_id: int | None
    solids_fraction_wet: float | None
    superseded_sample_id: int | None
    received_at: datetime


# ---------- 罐存量 ----------
class InventoryIn(BaseModel):
    node_id: str
    kind: str = Field(pattern="^(opening|closing|middle)$")
    mass_kg: float
    fat_fraction_wet: float
    fat_mass_kg: float | None = None
    abs_uc_mass: float | None = None
    rel_uc_mass: float | None = None
    ts: datetime
    segment_id: int | None = None
    cross_batch: bool = False
    note: str = ""


class InventoryOut(ORMModel):
    id: int
    node_id: str
    batch_id: int
    segment_id: int | None
    kind: str
    mass_kg: float
    fat_fraction_wet: float
    fat_mass_kg: float | None
    abs_uc_mass: float | None
    rel_uc_mass: float | None
    ts: datetime
    cross_batch: bool
    note: str


# ---------- 窗口 ----------
class WindowIn(BaseModel):
    label: str
    segment_ids: list[int]
    max_gap_s: float = 900.0
    extrap_tolerance_s: float = 30.0


class WindowOut(ORMModel):
    id: int
    batch_id: int
    label: str
    segment_ids: list[int]
    max_gap_s: float
    extrap_tolerance_s: float
    superseded_by: int | None


# ---------- 作业 / 结果 ----------
class JobOut(ORMModel):
    id: int
    window_id: int
    status: str
    input_digest: str
    algorithm_version: str
    is_current: bool
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: str


class SignoffIn(BaseModel):
    engineer: str
    note: str = ""


class SignoffOut(ORMModel):
    id: int
    window_id: int
    result_id: int
    engineer: str
    input_digest: str
    algorithm_version: str
    input_summary: dict
    note: str
    revoked: bool
    created_at: datetime


class Message(BaseModel):
    detail: str
