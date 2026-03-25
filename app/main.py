from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.config import settings
from app.db import get_session, init_db
from app.models import JobState, UploadJob
from app.schemas import CreateJobRequest, CreateJobResponse, JobStatusResponse, StatsResponse
from app.services.jobs import JobService

app = FastAPI(title=settings.app_name)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.on_event("startup")
async def startup() -> None:
    init_db()
    asyncio.create_task(expiry_loop())


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self';"
    return response


def internal_auth(x_internal_token: Annotated[str | None, Header()] = None) -> None:
    if x_internal_token != settings.internal_api_token:
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"telegram_bot_url": settings.telegram_bot_url},
    )


@app.get("/{public_slug}", response_class=HTMLResponse)
def install_page(public_slug: str, request: Request, session: Session = Depends(get_session)):
    job = session.exec(select(UploadJob).where(UploadJob.public_slug == public_slug)).first()
    if not job:
        raise HTTPException(status_code=404, detail="Link not found")

    now = datetime.now(timezone.utc)
    if job.expires_at < now or job.state in {JobState.EXPIRED, JobState.DELETED}:
        return templates.TemplateResponse(
            request=request,
            name="expired.html",
            context={"app_name": job.app_name},
            status_code=410,
        )

    job.install_views += 1
    session.add(job)
    session.commit()

    seconds_left = int((job.expires_at - now).total_seconds())
    manifest_url = f"{settings.public_base_url}/manifest/{job.manifest_token}.plist"
    itms_link = f"itms-services://?action=download-manifest&url={manifest_url}"
    return templates.TemplateResponse(
        request=request,
        name="install.html",
        context={
            "app_name": job.app_name,
            "seconds_left": max(0, seconds_left),
            "itms_link": itms_link,
            "public_url": f"{settings.public_base_url}/{job.public_slug}",
        },
    )


@app.get("/manifest/{manifest_token}.plist")
def manifest(manifest_token: str, session: Session = Depends(get_session)):
    job = session.exec(select(UploadJob).where(UploadJob.manifest_token == manifest_token)).first()
    if not job:
        raise HTTPException(status_code=404, detail="Manifest not found")

    now = datetime.now(timezone.utc)
    if job.expires_at < now or job.state in {JobState.EXPIRED, JobState.DELETED}:
        return PlainTextResponse("expired", status_code=410)

    if not job.github_asset_url:
        return PlainTextResponse("not-ready", status_code=409)

    plist = f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\"><dict><key>items</key><array><dict><key>assets</key><array>
<dict><key>kind</key><string>software-package</string><key>url</key><string>{job.github_asset_url}</string></dict>
</array><key>metadata</key><dict>
<key>bundle-identifier</key><string>{job.bundle_id}</string>
<key>bundle-version</key><string>1.0</string>
<key>kind</key><string>software</string>
<key>title</key><string>{job.app_name}</string>
</dict></dict></array></dict></plist>"""

    job.manifest_views += 1
    session.add(job)
    session.commit()
    return Response(content=plist, media_type="application/xml")


@app.post("/internal/jobs", response_model=CreateJobResponse, dependencies=[Depends(internal_auth)])
def create_job(payload: CreateJobRequest, session: Session = Depends(get_session)):
    svc = JobService(session)
    job = svc.create_or_get_job(payload)
    return CreateJobResponse(
        job_id=job.job_id,
        public_url=f"{settings.public_base_url}/{job.public_slug}",
        expires_at=job.expires_at,
        state=job.state,
    )


@app.get("/internal/jobs/{job_id}", response_model=JobStatusResponse, dependencies=[Depends(internal_auth)])
def job_status(job_id: str, session: Session = Depends(get_session)):
    job = session.exec(select(UploadJob).where(UploadJob.job_id == job_id)).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatusResponse(
        job_id=job.job_id,
        state=job.state,
        public_url=f"{settings.public_base_url}/{job.public_slug}",
        expires_at=job.expires_at,
        error=job.last_error,
    )


@app.get("/internal/stats", response_model=StatsResponse, dependencies=[Depends(internal_auth)])
def stats(session: Session = Depends(get_session)):
    return JSONResponse(JobService(session).stats())


async def expiry_loop() -> None:
    while True:
        with Session(bind=session_bind()) as session:
            JobService(session).mark_expired_jobs()
        await asyncio.sleep(60)


def session_bind():
    from app.db import engine

    return engine
