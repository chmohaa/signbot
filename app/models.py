from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


class JobState(str, Enum):
    UPLOADED = "uploaded"
    QUEUED = "queued"
    VALIDATING = "validating"
    SIGNING = "signing"
    UPLOADING = "uploading"
    MANIFEST_READY = "manifest_ready"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"
    DELETING = "deleting"
    DELETED = "deleted"


class UploadJob(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: str = Field(index=True, unique=True)
    public_id: str = Field(index=True, unique=True)
    public_slug: str = Field(index=True, unique=True)
    app_name: str
    bundle_id: str
    telegram_user_id: int = Field(index=True)
    mode: str = Field(default="one_time")

    state: JobState = Field(default=JobState.UPLOADED)
    github_release_id: Optional[int] = None
    github_asset_url: Optional[str] = None
    manifest_token: str = Field(index=True, unique=True)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    expires_at: datetime = Field(index=True)
    deleted_at: Optional[datetime] = None

    install_views: int = 0
    manifest_views: int = 0
    download_views: int = 0

    last_error: Optional[str] = None


class JobStateTransition(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: str = Field(index=True)
    from_state: Optional[JobState] = None
    to_state: JobState
    transitioned_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    reason: Optional[str] = None


class WalletCertificate(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    telegram_user_id: int = Field(index=True)
    cert_name: str
    encrypted_p12_b64: str
    encrypted_password_b64: str
    encrypted_mobileprovision_b64: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def ttl_expires(now: datetime, ttl_hours: int) -> datetime:
    return now + timedelta(hours=ttl_hours)
