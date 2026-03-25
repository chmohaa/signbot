from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models import JobState


class CreateJobRequest(BaseModel):
    job_id: str = Field(min_length=10, max_length=128)
    telegram_user_id: int
    app_name: str = Field(min_length=1, max_length=120)
    bundle_id: str = Field(min_length=3, max_length=255)
    app_version: str = Field(default="1.0", min_length=1, max_length=50)
    mode: str = Field(default="one_time", pattern="^(one_time|wallet)$")


class CreateJobResponse(BaseModel):
    job_id: str
    public_url: str
    expires_at: datetime
    state: JobState


class JobStatusResponse(BaseModel):
    job_id: str
    state: JobState
    public_url: str
    expires_at: datetime
    error: Optional[str] = None


class StatsResponse(BaseModel):
    total_jobs: int
    active_jobs: int
    deleted_jobs: int
    failed_jobs: int


class WalletSaveRequest(BaseModel):
    telegram_user_id: int
    cert_name: str = Field(min_length=2, max_length=80)
    p12_b64: str
    p12_password: str
    mobileprovision_b64: str


class WalletDeleteRequest(BaseModel):
    telegram_user_id: int
    cert_name: str
