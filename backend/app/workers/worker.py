import socket
import time

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.jobs import claim_next_job, execute_job


def main():
    settings = get_settings()
    worker_id = f"{socket.gethostname()}-{socket.getpid()}"
    while True:
        db = SessionLocal()
        try:
            job = claim_next_job(db, worker_id)
            if job:
                execute_job(db, job.id)
        finally:
            db.close()
        time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
