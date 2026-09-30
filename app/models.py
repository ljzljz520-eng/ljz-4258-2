"""ORM 模型：拓扑、批段、样品、存量、量程、稳定窗口、作业、结果、签署。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Topology(Base):
    __tablename__ = "topologies"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    # {"nodes":[{"id","type","name"}], "streams":[{"id","source","sink",
    #   "carries_fat":bool, "name"}]}
    definition: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=utcnow)
    batches: Mapped[list[Batch]] = relationship(back_populates="topology")


class Batch(Base):
    __tablename__ = "batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    topology_id: Mapped[int] = mapped_column(ForeignKey("topologies.id"))
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=utcnow)
    topology: Mapped[Topology] = relationship(back_populates="batches")
    segments: Mapped[list[Segment]] = relationship(
        back_populates="batch", order_by="Segment.seq")


class Segment(Base):
    __tablename__ = "segments"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(String(64))
    start_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # 跨批回流/旧料的边界说明，仅作元数据；守恒通过 opening inventories 进入
    boundary_note: Mapped[str] = mapped_column(Text, default="")
    batch: Mapped[Batch] = relationship(back_populates="segments")
    __table_args__ = (UniqueConstraint("batch_id", "code", name="uq_segment_code"),)


class Window(Base):
    """工程师选定的稳定窗口（一组段）。调整窗口即作废依赖它的结果。"""
    __tablename__ = "windows"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"), index=True)
    label: Mapped[str] = mapped_column(String(120))
    segment_ids: Mapped[list] = mapped_column(JSON, default=list)
    max_gap_s: Mapped[float] = mapped_column(Float, default=900.0)
    extrap_tolerance_s: Mapped[float] = mapped_column(Float, default=30.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=utcnow)
    superseded_by: Mapped[int | None] = mapped_column(
        ForeignKey("windows.id"), nullable=True)


class Sample(Base):
    __tablename__ = "samples"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("batches.id"), index=True, nullable=True)
    stream_id: Mapped[str] = mapped_column(String(64), index=True)
    segment_id: Mapped[int] = mapped_column(ForeignKey("segments.id"),
                                            index=True, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    metric: Mapped[str] = mapped_column(String(32))  # flow|density|fat
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(32))
    abs_uc: Mapped[float | None] = mapped_column(Float, nullable=True)
    rel_uc: Mapped[float | None] = mapped_column(Float, nullable=True)
    range_id: Mapped[int | None] = mapped_column(
        ForeignKey("measurement_ranges.id"), nullable=True)
    # 干基脂肪样品记录总固形物湿基分数（fraction）
    solids_fraction_wet: Mapped[float | None] = mapped_column(Float,
                                                               nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                   default=utcnow)
    superseded_sample_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True)  # 迟到更正样本所替代的样本


class MeasurementRange(Base):
    """量程/计量通道：可辨识性诊断用它给出「允许区间」建议。"""
    __tablename__ = "measurement_ranges"
    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[str] = mapped_column(String(64), index=True)
    metric: Mapped[str] = mapped_column(String(32))
    unit: Mapped[str] = mapped_column(String(32))
    low: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    active_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    active_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    label: Mapped[str] = mapped_column(String(120), default="")


class TankInventory(Base):
    """罐底旧料 / 罐存量。opening 进入守恒方程的已知 RHS。"""
    __tablename__ = "tank_inventories"
    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[str] = mapped_column(String(64), index=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"), index=True)
    segment_id: Mapped[int | None] = mapped_column(
        ForeignKey("segments.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(16))  # opening|closing|middle
    mass_kg: Mapped[float] = mapped_column(Float)
    fat_fraction_wet: Mapped[float] = mapped_column(Float)
    fat_mass_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    abs_uc_mass: Mapped[float | None] = mapped_column(Float, nullable=True)
    rel_uc_mass: Mapped[float | None] = mapped_column(Float, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cross_batch: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(Text, default="")


class CalcVersion(Base):
    __tablename__ = "calc_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=utcnow)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    window_id: Mapped[int] = mapped_column(ForeignKey("windows.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    # queued|running|done|error|stale|superseded
    input_digest: Mapped[str] = mapped_column(String(64), index=True)
    input_snapshot: Mapped[dict] = mapped_column(JSON)
    algorithm_version: Mapped[str] = mapped_column(String(32), index=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class Result(Base):
    __tablename__ = "results"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    window_id: Mapped[int] = mapped_column(ForeignKey("windows.id"), index=True)
    digest: Mapped[str] = mapped_column(String(64), index=True)
    algorithm_version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24))  # identified|underdetermined|error
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=utcnow)


class Signoff(Base):
    """签署：冻结输入摘要 + 算法版本 + 结果，不允许原地修改。"""
    __tablename__ = "signoffs"
    id: Mapped[int] = mapped_column(primary_key=True)
    window_id: Mapped[int] = mapped_column(ForeignKey("windows.id"), index=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("results.id"))
    engineer: Mapped[str] = mapped_column(String(120))
    input_digest: Mapped[str] = mapped_column(String(64))
    algorithm_version: Mapped[str] = mapped_column(String(32))
    input_summary: Mapped[dict] = mapped_column(JSON)
    note: Mapped[str] = mapped_column(Text, default="")
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=utcnow)


class SignoffEvent(Base):
    """签署审计事件：签署后只允许追加（如撤销），签署本体不可原地修改。"""
    __tablename__ = "signoff_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    signoff_id: Mapped[int] = mapped_column(ForeignKey("signoffs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # created|revoked
    actor: Mapped[str] = mapped_column(String(120))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=utcnow)
