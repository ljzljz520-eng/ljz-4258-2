import hmac
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import AuditEvent, CalcVersion, Job, Segment, Signoff
from app.db.session import get_db
from app.schemas import JobRead, SignoffCreate, SignoffRead
from app.services.topology import input_signature, make_snapshot, problem_from_snapshot

router = APIRouter(prefix="/api", tags=["jobs"])


def _job_or_404(db: Session, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job


@router.post("/segments/{segment_id}/precheck")
def precheck(segment_id: int, db: Session = Depends(get_db)):
    seg = db.get(Segment, segment_id)
    if not seg:
        raise HTTPException(404, "segment not found")
    settings = get_settings()
    snapshot = make_snapshot(db, seg, settings.algorithm_version)
    try:
        problem, aggregates = problem_from_snapshot(snapshot)
        from app.services.reconciliation import identifiability_report
        report = identifiability_report(problem)
    except Exception as exc:
        raise HTTPException(422, f"model construction failed: {exc}") from exc
    return {"segment_id": segment_id, "version": seg.version, "aggregates": aggregates,
            "identifiability": report, "input_summary": snapshot["input_summary"]}


@router.post("/segments/{segment_id}/jobs", response_model=JobRead, status_code=201)
def enqueue_job(segment_id: int, db: Session = Depends(get_db)):
    seg = db.get(Segment, segment_id)
    if not seg:
        raise HTTPException(404, "segment not found")
    settings = get_settings()
    snapshot = make_snapshot(db, seg, settings.algorithm_version)
    # Validate constructability before accepting work, but do not reject for
    # underdetermination: worker persists that report without inventing results.
    problem_from_snapshot(snapshot)
    job = Job(segment_id=segment_id, status="queued", input_version=seg.version,
              algorithm_version=settings.algorithm_version,
              input_summary=snapshot["input_summary"], input_snapshot=snapshot)
    db.add(job)
    db.add(AuditEvent(entity_type="segment", entity_id=segment_id, action="enqueue_job",
                      detail={"input_summary": snapshot["input_summary"], "version": seg.version}))
    db.commit()
    db.refresh(job)
    return job


@router.get("/segments/{segment_id}/jobs", response_model=list[JobRead])
def list_jobs(segment_id: int, db: Session = Depends(get_db)):
    return db.scalars(select(Job).where(Job.segment_id == segment_id).order_by(Job.id.desc())).all()


@router.get("/segments/{segment_id}/current-result")
def current_result(segment_id: int, db: Session = Depends(get_db)):
    seg = db.get(Segment, segment_id)
    if not seg:
        raise HTTPException(404, "segment not found")
    job = db.scalar(
        select(Job).join(Segment, Segment.id == Job.segment_id)
        .where(Job.segment_id == segment_id, Job.status == "succeeded",
               Job.input_version == Segment.version)
        .order_by(Job.id.desc())
    )
    if not job:
        raise HTTPException(404, "no current succeeded job for segment version")
    return {"job_id": job.id, "input_version": job.input_version,
            "algorithm_version": job.algorithm_version, "input_summary": job.input_summary,
            "result": job.result, "signoff": _signoff_for_job(db, job.id)}


@router.get("/jobs/{job_id}", response_model=JobRead)
def get_job(job_id: int, db: Session = Depends(get_db)):
    return _job_or_404(db, job_id)


def _signoff_for_job(db: Session, job_id: int):
    s = db.scalar(select(Signoff).where(Signoff.job_id == job_id))
    if not s:
        return None
    return {"engineer": s.engineer, "signature": s.signature, "created_at": s.created_at,
            "algorithm_version": s.algorithm_version, "input_summary": s.input_summary}


@router.post("/jobs/{job_id}/signoff", response_model=SignoffRead, status_code=201)
def signoff(job_id: int, body: SignoffCreate, db: Session = Depends(get_db)):
    job = _job_or_404(db, job_id)
    if job.status != "succeeded":
        raise HTTPException(409, "only succeeded jobs can be signed")
    if job.input_version != db.get(Segment, job.segment_id).version:
        raise HTTPException(409, "job is stale; sign the latest result or create a new job")
    if db.scalar(select(Signoff).where(Signoff.job_id == job_id)):
        raise HTTPException(409, "job already signed")
    expected = input_signature(job.input_snapshot, get_settings().signing_secret)
    row = Signoff(job_id=job_id, engineer=body.engineer, note=body.note,
                  input_summary=job.input_summary, algorithm_version=job.algorithm_version,
                  signature=expected)
    db.add(row)
    db.add(AuditEvent(entity_type="job", entity_id=job_id, action="signoff",
                      detail={"engineer": body.engineer, "input_summary": job.input_summary}))
    db.commit()
    db.refresh(row)
    return row
