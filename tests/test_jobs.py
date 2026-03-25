from datetime import datetime, timezone

from sqlmodel import Session, SQLModel, create_engine

from app.models import JobState
from app.schemas import CreateJobRequest
from app.services.jobs import JobService


def build_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_idempotent_job_creation():
    with build_session() as session:
        svc = JobService(session)
        payload = CreateJobRequest(job_id="idempotent-12345", telegram_user_id=1, app_name="Test App", bundle_id="com.t.app")
        first = svc.create_or_get_job(payload)
        second = svc.create_or_get_job(payload)
        assert first.job_id == second.job_id


def test_expiration_transition():
    with build_session() as session:
        svc = JobService(session)
        payload = CreateJobRequest(job_id="expire-12345", telegram_user_id=2, app_name="Test App", bundle_id="com.t.app")
        job = svc.create_or_get_job(payload)
        job.expires_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
        session.add(job)
        session.commit()
        count = svc.mark_expired_jobs()
        assert count == 1
        session.refresh(job)
        assert job.state == JobState.EXPIRED
