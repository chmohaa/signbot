from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlmodel import Session, func, select

from app.config import settings
from app.models import JobFile, JobState, JobStateTransition, UploadJob, WalletCertificate, ttl_expires


class JobService:
    def __init__(self, session: Session):
        self.session = session

    def create_or_get_job(self, job_id: str, telegram_user_id: int, app_name: str, bundle_id: str, app_version: str, mode: str) -> UploadJob:
        existing = self.session.exec(select(UploadJob).where(UploadJob.job_id == job_id)).first()
        if existing:
            return existing

        active = self.session.exec(
            select(UploadJob).where(
                UploadJob.telegram_user_id == telegram_user_id,
                UploadJob.state.notin_([JobState.COMPLETED, JobState.FAILED, JobState.DELETED, JobState.EXPIRED]),
            )
        ).first()
        if active:
            return active

        now = datetime.now(timezone.utc)
        public_id = secrets.token_urlsafe(24)
        app_slug = "".join(ch for ch in app_name.lower().replace(" ", "-") if ch.isalnum() or ch == "-")[:40] or "app"

        job = UploadJob(
            job_id=job_id,
            public_id=public_id,
            public_slug=f"{public_id}-{app_slug}",
            app_name=app_name,
            bundle_id=bundle_id,
            app_version=app_version,
            telegram_user_id=telegram_user_id,
            mode=mode,
            expires_at=ttl_expires(now, settings.ttl_hours),
            manifest_token=secrets.token_urlsafe(32),
            state=JobState.QUEUED,
        )
        self.session.add(job)
        self._transition(job.job_id, None, JobState.QUEUED, "job created")
        self.session.commit()
        self.session.refresh(job)
        return job

    def get_job(self, job_id: str) -> UploadJob | None:
        return self.session.exec(select(UploadJob).where(UploadJob.job_id == job_id)).first()

    def set_state(self, job: UploadJob, to_state: JobState, reason: str | None = None) -> None:
        from_state = job.state
        job.state = to_state
        self.session.add(job)
        self._transition(job.job_id, from_state, to_state, reason)
        self.session.commit()

    def set_error(self, job: UploadJob, message: str) -> None:
        job.last_error = message[:500]
        self.session.add(job)
        self.session.commit()

    def save_job_file(self, job_id: str, file_type: str, file_path: str, size_bytes: int) -> None:
        row = self.session.exec(
            select(JobFile).where(JobFile.job_id == job_id, JobFile.file_type == file_type)
        ).first()
        if row:
            row.file_path = file_path
            row.size_bytes = size_bytes
            self.session.add(row)
        else:
            self.session.add(JobFile(job_id=job_id, file_type=file_type, file_path=file_path, size_bytes=size_bytes))
        self.session.commit()

    def get_job_file(self, job_id: str, file_type: str) -> JobFile | None:
        return self.session.exec(select(JobFile).where(JobFile.job_id == job_id, JobFile.file_type == file_type)).first()

    def list_job_files(self, job_id: str) -> list[JobFile]:
        return list(self.session.exec(select(JobFile).where(JobFile.job_id == job_id)).all())

    def delete_job_files_rows(self, job_id: str) -> None:
        rows = self.list_job_files(job_id)
        for row in rows:
            self.session.delete(row)
        self.session.commit()

    def mark_expired_jobs(self) -> list[UploadJob]:
        now = datetime.now(timezone.utc)
        jobs = self.session.exec(
            select(UploadJob).where(
                UploadJob.expires_at < now,
                UploadJob.state.notin_([JobState.EXPIRED, JobState.DELETED]),
            )
        ).all()

        for job in jobs:
            self.set_state(job, JobState.EXPIRED, "TTL reached")
        return list(jobs)

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


class WalletService:
    def __init__(self, session: Session):
        self.session = session

    def save_wallet(self, telegram_user_id: int, cert_name: str, encrypted_p12_b64: str, encrypted_password_b64: str, encrypted_profile_b64: str) -> WalletCertificate:
        existing = self.session.exec(
            select(WalletCertificate).where(
                WalletCertificate.telegram_user_id == telegram_user_id,
                WalletCertificate.cert_name == cert_name,
            )
        ).first()
        if existing:
            existing.encrypted_p12_b64 = encrypted_p12_b64
            existing.encrypted_password_b64 = encrypted_password_b64
            existing.encrypted_mobileprovision_b64 = encrypted_profile_b64
            self.session.add(existing)
            self.session.commit()
            self.session.refresh(existing)
            return existing

        created = WalletCertificate(
            telegram_user_id=telegram_user_id,
            cert_name=cert_name,
            encrypted_p12_b64=encrypted_p12_b64,
            encrypted_password_b64=encrypted_password_b64,
            encrypted_mobileprovision_b64=encrypted_profile_b64,
        )
        self.session.add(created)
        self.session.commit()
        self.session.refresh(created)
        return created

    def get_wallet(self, telegram_user_id: int, cert_name: str) -> WalletCertificate | None:
        return self.session.exec(
            select(WalletCertificate).where(
                WalletCertificate.telegram_user_id == telegram_user_id,
                WalletCertificate.cert_name == cert_name,
            )
        ).first()

    def delete_wallet(self, telegram_user_id: int, cert_name: str) -> bool:
        row = self.get_wallet(telegram_user_id, cert_name)
        if not row:
            return False
        self.session.delete(row)
        self.session.commit()
        return True
