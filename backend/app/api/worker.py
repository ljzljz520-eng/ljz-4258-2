from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas import ClaimJob
from app.schemas import JobRead
from app.services.jobs import claim_next_job, execute_job

router = APIRouter(prefix="/api/worker", tags=["worker"])


@router.post("/claim", response_model=JobRead | None)
def claim(body: ClaimJob, db: Session = Depends(get_db)):
    return claim_next_job(db, body.worker_id)


@router.post("/jobs/{job_id}/complete", response_model=JobRead)
def complete(job_id: int, db: Session = Depends(get_db)):
    return execute_job(db, job_id)
