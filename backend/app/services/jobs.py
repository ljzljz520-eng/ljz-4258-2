from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Job, Segment
from app.core.enums import JobStatus
from app.services.reconciliation import solve
from app.services.topology import problem_from_snapshot


def claim_next_job(db: Session, worker_id: str) -> Job | None:
    stmt = select(Job).where(Job.status == JobStatus.QUEUED).order_by(Job.id).limit(1)
    try:
        stmt = stmt.with_for_update(skip_locked=True)
    except Exception:
        pass
    job = db.scalars(stmt).first()
    if not job:
        return None
    job.status = JobStatus.RUNNING
    job.worker_id = worker_id
    job.started_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    return job


def execute_job(db: Session, job_id: int) -> Job:
    """Execute a previously claimed job.

    The segment version is checked at completion. A slow old task may finish, but
    its result is never written when the stable window or dependent topology has
    advanced. The newer job remains the only graph candidate.
    """
    job = db.get(Job, job_id)
    if not job or job.status != JobStatus.RUNNING:
        return job
    segment = db.get(Segment, job.segment_id)
    if not segment or segment.version != job.input_version:
        job.status = JobStatus.SUPERSEDED
        job.error = "stable window or dependent input changed before completion"
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(job)
        return job
    try:
        problem, aggregates = problem_from_snapshot(job.input_snapshot)
        result = solve(problem)
        result["aggregates"] = aggregates
        if result["status"] == "underdetermined":
            job.status = JobStatus.UNDERDETERMINED
        else:
            job.status = JobStatus.SUCCEEDED
        job.result = result
    except Exception as exc:
        job.status = JobStatus.FAILED
        job.error = str(exc)
    finally:
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(job)
    return job
