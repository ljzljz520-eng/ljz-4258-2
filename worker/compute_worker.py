"""独立计算 Worker（与 Web 进程分离运行）。

并发策略：
  * PostgreSQL: SELECT ... FOR UPDATE SKIP LOCKED，多 worker 安全；
  * SQLite/测试: 进程内条件锁（status CASQ），单 worker 足够。
陈旧保护（旧任务晚到不得覆盖当前图）：
  1) 取作业后重新构建快照摘要：与入队时不一致 -> 标记 stale，不写结果；
  2) 作业 is_current=False（被新窗口/新作业取代）-> stale；
  3) 结果只在仍 current 时写入 is_current=True，否则归档为历史。
"""
from __future__ import annotations

import os
import socket
import time
import traceback
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.core.engine import compute
from app.core.version import ALGORITHM_VERSION
from app.database import SessionLocal
from app.models import Job, Result, Window
from app.services import build_snapshot, digest_for

HOST = socket.gethostname()


def _claim_one(db) -> Job | None:
    """认领一个排队作业。

    PostgreSQL 用 SELECT ... FOR UPDATE SKIP LOCKED，多 worker 并发安全；
    SQLite 不支持该子句，退化为条件 UPDATE 的原子 CAS（单 worker 足够）。
    """
    is_pg = db.bind.dialect.name == "postgresql"
    job = None
    if is_pg:
        try:
            job = (db.query(Job)
                     .filter(Job.status == "queued",
                             Job.is_current.is_(True))
                     .order_by(Job.id)
                     .with_for_update(skip_locked=True)
                     .first())
        except OperationalError:
            db.rollback()
            job = None
    if job is None:
        # SQLite / PG 兜底：原子地“抢到 id 再置 running”
        row = db.execute(text(
            "SELECT id FROM jobs WHERE status='queued' AND is_current=1 "
            "ORDER BY id LIMIT 1")).first()
        if row is None:
            return None
        upd = db.execute(text(
            "UPDATE jobs SET status='running', started_at=:ts, locked_by=:h "
            "WHERE id=:id AND status='queued' AND is_current=1"),
            {"ts": datetime.now(timezone.utc), "h": HOST, "id": row[0]})
        if upd.rowcount != 1:
            db.rollback()
            return None
        job = db.get(Job, row[0])
    else:
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        job.locked_by = HOST
    db.commit()
    db.refresh(job)
    return job


def process_job(job_id: int) -> str:
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            return "missing"
        if job.status not in ("running",):
            # 可能已被并发标记 superseded
            return job.status

        window = db.get(Window, job.window_id)
        # 重新构建“当前”快照并比较摘要
        current_snapshot = build_snapshot(
            db, window,
            freeze_ts=datetime.fromisoformat(
                job.input_snapshot["freeze_ts"].replace("Z", "+00:00")))
        fresh_digest = digest_for(current_snapshot)

        if not job.is_current:
            job.status = "stale"
            job.error = "job superseded before computation"
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
            return "stale"

        if fresh_digest != job.input_digest:
            # 冻结后有新样本/窗口被改动：不覆盖当前图，标记 stale
            job.status = "stale"
            job.error = ("input changed between enqueue and run "
                         f"({job.input_digest[:10]} -> {fresh_digest[:10]})")
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
            return "stale"

        try:
            payload = compute(job.input_snapshot, digest=job.input_digest)
        except Exception as exc:  # 求解异常不崩溃 worker
            job.status = "error"
            job.error = f"{type(exc).__name__}: {exc}\n" + traceback.format_exc()
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
            return "error"

        still_current = db.get(Job, job.id).is_current
        result = Result(
            job_id=job.id, window_id=job.window_id,
            digest=job.input_digest,
            algorithm_version=job.algorithm_version,
            status=payload.get("status", "error"),
            is_current=bool(still_current), payload=payload)
        db.add(result)
        job.status = "done"
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        return job.status
    finally:
        db.close()


def run_forever(poll_s: float | None = None) -> None:
    poll = poll_s if poll_s is not None else float(
        os.environ.get("WORKER_POLL_S", "1.0"))
    while True:
        db = SessionLocal()
        try:
            job = _claim_one(db)
        finally:
            db.close()
        if job is not None:
            process_job(job.id)
        else:
            time.sleep(poll)


if __name__ == "__main__":
    run_forever()
