from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models import JobState


class CreateJobRequest(BaseModel):
    job_id: str = Field(min_length=10, max_length=128)
    telegram_user_id: int
    app_name: str = Field(min_length=1, max_length=120)
    bundle_id: str = Field(min_length=3, max_length=255)
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
