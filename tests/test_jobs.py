from datetime import datetime, timezone

from sqlmodel import Session, SQLModel, create_engine

from app.models import JobState
from app.services.jobs import JobService


def build_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_idempotent_job_creation():
    with build_session() as session:
        svc = JobService(session)
        first = svc.create_or_get_job(
            job_id="idempotent-12345",
            telegram_user_id=1,
            app_name="Test App",
            bundle_id="com.t.app",
            app_version="1.0",
            mode="one_time",
        )
        second = svc.create_or_get_job(
            job_id="idempotent-12345",
            telegram_user_id=1,
            app_name="Test App",
            bundle_id="com.t.app",
            app_version="1.0",
            mode="one_time",
        )
        assert first.job_id == second.job_id


def test_expiration_transition():
    with build_session() as session:
        svc = JobService(session)
        job = svc.create_or_get_job(
            job_id="expire-12345",
            telegram_user_id=2,
            app_name="Test App",
            bundle_id="com.t.app",
            app_version="1.0",
            mode="one_time",
        )
        job.expires_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
        session.add(job)
        session.commit()
        jobs = svc.mark_expired_jobs()
        assert len(jobs) == 1
        session.refresh(job)
        assert job.state == JobState.EXPIRED
