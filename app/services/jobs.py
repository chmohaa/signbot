from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlmodel import Session, func, select

from app.config import settings
from app.models import JobState, JobStateTransition, UploadJob, ttl_expires
from app.schemas import CreateJobRequest


class JobService:
    def __init__(self, session: Session):
        self.session = session

    def create_or_get_job(self, payload: CreateJobRequest) -> UploadJob:
        existing = self.session.exec(select(UploadJob).where(UploadJob.job_id == payload.job_id)).first()
        if existing:
            return existing

        active = self.session.exec(
            select(UploadJob).where(
                UploadJob.telegram_user_id == payload.telegram_user_id,
                UploadJob.state.notin_([JobState.COMPLETED, JobState.FAILED, JobState.DELETED, JobState.EXPIRED]),
            )
        ).first()
        if active:
            return active

        now = datetime.now(timezone.utc)
        public_id = secrets.token_urlsafe(24)
        app_slug = "".join(ch for ch in payload.app_name.lower().replace(" ", "-") if ch.isalnum() or ch == "-")[:40] or "app"

        job = UploadJob(
            job_id=payload.job_id,
            public_id=public_id,
            public_slug=f"{public_id}-{app_slug}",
            app_name=payload.app_name,
            bundle_id=payload.bundle_id,
            telegram_user_id=payload.telegram_user_id,
            mode=payload.mode,
            expires_at=ttl_expires(now, settings.ttl_hours),
            manifest_token=secrets.token_urlsafe(32),
        )
        self.session.add(job)
        self._transition(job.job_id, None, JobState.UPLOADED, "job created")
        self.session.commit()
        self.session.refresh(job)
        return job

    def set_state(self, job: UploadJob, to_state: JobState, reason: str | None = None) -> None:
        from_state = job.state
        job.state = to_state
        self.session.add(job)
        self._transition(job.job_id, from_state, to_state, reason)
        self.session.commit()

    def mark_expired_jobs(self) -> int:
        now = datetime.now(timezone.utc)
        jobs = self.session.exec(
            select(UploadJob).where(
                UploadJob.expires_at < now,
                UploadJob.state.notin_([JobState.EXPIRED, JobState.DELETED]),
            )
        ).all()

        for job in jobs:
            self.set_state(job, JobState.EXPIRED, "TTL reached")
        return len(jobs)

    def stats(self) -> dict:
        total = self.session.exec(select(func.count()).select_from(UploadJob)).one()
        active = self.session.exec(
            select(func.count()).select_from(UploadJob).where(
                UploadJob.state.notin_([JobState.EXPIRED, JobState.DELETED, JobState.FAILED])
            )
        ).one()
        deleted = self.session.exec(select(func.count()).select_from(UploadJob).where(UploadJob.state == JobState.DELETED)).one()
        failed = self.session.exec(select(func.count()).select_from(UploadJob).where(UploadJob.state == JobState.FAILED)).one()
        return {
            "total_jobs": int(total),
            "active_jobs": int(active),
            "deleted_jobs": int(deleted),
            "failed_jobs": int(failed),
        }

    def _transition(self, job_id: str, from_state: JobState | None, to_state: JobState, reason: str | None) -> None:
        self.session.add(
            JobStateTransition(job_id=job_id, from_state=from_state, to_state=to_state, reason=reason)
        )
