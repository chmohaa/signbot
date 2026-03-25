from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.config import settings
from app.db import get_session, init_db
from app.models import JobState, UploadJob
from app.schemas import (
    CreateJobRequest,
    CreateJobResponse,
    JobStatusResponse,
    StatsResponse,
    WalletDeleteRequest,
    WalletSaveRequest,
)
from app.services.crypto import CryptoService
from app.services.file_store import PrivateFileStore
from app.services.jobs import JobService, WalletService
from app.services.signer import SignerService, SigningError
from app.services.storage import GitHubReleaseStorage, StorageError
from app.validators import ValidationError, sanitize_filename, validate_file

app = FastAPI(title=settings.app_name)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

crypto = CryptoService(settings.encryption_key)
file_store = PrivateFileStore(settings.private_storage_dir)
signer = SignerService()
processing_jobs: set[str] = set()


@app.on_event("startup")
async def startup() -> None:
    init_db()
    Path(settings.private_storage_dir).mkdir(parents=True, exist_ok=True)
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


def owner_auth(x_owner_telegram_id: Annotated[int | None, Header()] = None) -> None:
    if x_owner_telegram_id != settings.owner_telegram_id:
        raise HTTPException(status_code=403, detail="Owner access required")


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
<key>bundle-version</key><string>{job.app_version}</string>
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
    job = svc.create_or_get_job(
        job_id=payload.job_id,
        telegram_user_id=payload.telegram_user_id,
        app_name=payload.app_name,
        bundle_id=payload.bundle_id,
        app_version=payload.app_version,
        mode=payload.mode,
    )
    return CreateJobResponse(
        job_id=job.job_id,
        public_url=f"{settings.public_base_url}/{job.public_slug}",
        expires_at=job.expires_at,
        state=job.state,
    )


@app.post("/internal/jobs/{job_id}/upload", dependencies=[Depends(internal_auth)])
async def upload_job_files(
    job_id: str,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
    ipa: UploadFile = File(...),
    p12: UploadFile = File(...),
    mobileprovision: UploadFile = File(...),
    p12_password: str = Form(...),
):
    svc = JobService(session)
    job = svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.state in {JobState.COMPLETED, JobState.MANIFEST_READY, JobState.UPLOADING, JobState.SIGNING, JobState.VALIDATING}:
        return {"job_id": job_id, "state": job.state, "message": "already in progress or completed"}

    try:
        ipa_bytes = await ipa.read()
        p12_bytes = await p12.read()
        profile_bytes = await mobileprovision.read()

        ipa_name = sanitize_filename(ipa.filename or "app.ipa")
        p12_name = sanitize_filename(p12.filename or "cert.p12")
        profile_name = sanitize_filename(mobileprovision.filename or "profile.mobileprovision")

        validate_file(ipa_name, ipa_bytes, settings.max_ipa_size_bytes)
        validate_file(p12_name, p12_bytes, 20 * 1024 * 1024)
        validate_file(profile_name, profile_bytes, 20 * 1024 * 1024)
    except ValidationError as exc:
        svc.set_state(job, JobState.FAILED, str(exc))
        svc.set_error(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc))

    ipa_path = file_store.save_bytes(job.job_id, "ipa", ipa_name, ipa_bytes)
    p12_path = file_store.save_bytes(job.job_id, "p12", p12_name, p12_bytes)
    profile_path = file_store.save_bytes(job.job_id, "mobileprovision", profile_name, profile_bytes)

    svc.save_job_file(job.job_id, "ipa", ipa_path, len(ipa_bytes))
    svc.save_job_file(job.job_id, "p12", p12_path, len(p12_bytes))
    svc.save_job_file(job.job_id, "mobileprovision", profile_path, len(profile_bytes))
    encrypted_password = crypto.encrypt_to_b64(p12_password.encode("utf-8"))
    svc.save_job_file(job.job_id, "p12_password", file_store.save_bytes(job.job_id, "secret", "p12_password.bin", encrypted_password.encode("utf-8")), len(encrypted_password))

    svc.set_state(job, JobState.UPLOADED, "files uploaded")
    background.add_task(process_job, job.job_id)

    return {"job_id": job.job_id, "state": job.state, "message": "processing started"}


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


@app.get("/internal/stats", response_model=StatsResponse, dependencies=[Depends(internal_auth), Depends(owner_auth)])
def stats(session: Session = Depends(get_session)):
    return JSONResponse(JobService(session).stats())


@app.post("/internal/wallet", dependencies=[Depends(internal_auth)])
def wallet_save(payload: WalletSaveRequest, session: Session = Depends(get_session)):
    svc = WalletService(session)
    encrypted_p12 = crypto.encrypt_to_b64(base64.b64decode(payload.p12_b64.encode("utf-8")))
    encrypted_password = crypto.encrypt_to_b64(payload.p12_password.encode("utf-8"))
    encrypted_profile = crypto.encrypt_to_b64(base64.b64decode(payload.mobileprovision_b64.encode("utf-8")))
    wallet = svc.save_wallet(payload.telegram_user_id, payload.cert_name, encrypted_p12, encrypted_password, encrypted_profile)
    return {"id": wallet.id, "telegram_user_id": wallet.telegram_user_id, "cert_name": wallet.cert_name}


@app.get("/internal/wallet/{telegram_user_id}/{cert_name}", dependencies=[Depends(internal_auth), Depends(owner_auth)])
def wallet_get(telegram_user_id: int, cert_name: str, session: Session = Depends(get_session)):
    svc = WalletService(session)
    wallet = svc.get_wallet(telegram_user_id, cert_name)
    if not wallet:
        raise HTTPException(status_code=404, detail="wallet not found")
    return {
        "telegram_user_id": telegram_user_id,
        "cert_name": cert_name,
        "has_data": True,
        "created_at": wallet.created_at,
    }


@app.delete("/internal/wallet", dependencies=[Depends(internal_auth), Depends(owner_auth)])
def wallet_delete(payload: WalletDeleteRequest, session: Session = Depends(get_session)):
    svc = WalletService(session)
    removed = svc.delete_wallet(payload.telegram_user_id, payload.cert_name)
    return {"deleted": removed}


@app.get("/health")
def health() -> dict:
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}


async def process_job(job_id: str) -> None:
    if job_id in processing_jobs:
        return
    processing_jobs.add(job_id)
    try:
        from app.db import engine

        with Session(engine) as session:
            svc = JobService(session)
            job = svc.get_job(job_id)
            if not job:
                return

            if job.state in {JobState.COMPLETED, JobState.DELETED, JobState.EXPIRED}:
                return

            ipa_file = svc.get_job_file(job_id, "ipa")
            p12_file = svc.get_job_file(job_id, "p12")
            profile_file = svc.get_job_file(job_id, "mobileprovision")
            password_file = svc.get_job_file(job_id, "p12_password")
            if not all([ipa_file, p12_file, profile_file, password_file]):
                svc.set_state(job, JobState.FAILED, "incomplete job files")
                svc.set_error(job, "incomplete job files")
                return

            ipa_bytes = file_store.read_bytes(ipa_file.file_path)
            p12_bytes = file_store.read_bytes(p12_file.file_path)
            profile_bytes = file_store.read_bytes(profile_file.file_path)
            p12_password = crypto.decrypt_from_b64(file_store.read_bytes(password_file.file_path).decode("utf-8")).decode("utf-8")

            try:
                svc.set_state(job, JobState.VALIDATING, "pre-validation")
                signer.prevalidate(ipa_bytes, p12_bytes, p12_password, profile_bytes)

                svc.set_state(job, JobState.SIGNING, "signing ipa")
                signed_ipa = signer.sign(ipa_bytes, p12_bytes, p12_password, profile_bytes)

                svc.set_state(job, JobState.UPLOADING, "uploading to github releases")
                storage = GitHubReleaseStorage()
                uploaded = await storage.upload_signed_ipa(job.job_id, f"{job.public_id}.ipa", signed_ipa)

                job.github_release_id = uploaded.release_id
                job.github_asset_url = uploaded.asset_url
                job.github_tag = uploaded.tag_name
                session.add(job)
                session.commit()

                svc.set_state(job, JobState.MANIFEST_READY, "manifest ready")
                svc.set_state(job, JobState.COMPLETED, "completed")
            except SigningError as exc:
                svc.set_state(job, JobState.FAILED, "signing failed")
                svc.set_error(job, str(exc))
            except StorageError as exc:
                svc.set_state(job, JobState.FAILED, "storage failed")
                svc.set_error(job, str(exc))
            except Exception as exc:  # noqa: BLE001
                svc.set_state(job, JobState.FAILED, "unexpected error")
                svc.set_error(job, str(exc))
    finally:
        processing_jobs.discard(job_id)


async def expiry_loop() -> None:
    from app.db import engine

    while True:
        with Session(engine) as session:
            svc = JobService(session)
            expired_jobs = svc.mark_expired_jobs()
            for job in expired_jobs:
                if job.github_release_id:
                    try:
                        svc.set_state(job, JobState.DELETING, "deleting expired release")
                        storage = GitHubReleaseStorage()
                        await storage.delete_release(job.github_release_id)
                    except StorageError as exc:
                        svc.set_error(job, str(exc))
                    finally:
                        for row in svc.list_job_files(job.job_id):
                            file_store.delete_path(row.file_path)
                        svc.delete_job_files_rows(job.job_id)
                        file_store.delete_job_dir(job.job_id)
                        job.deleted_at = datetime.now(timezone.utc)
                        session.add(job)
                        session.commit()
                        svc.set_state(job, JobState.DELETED, "expired cleanup completed")
                else:
                    for row in svc.list_job_files(job.job_id):
                        file_store.delete_path(row.file_path)
                    svc.delete_job_files_rows(job.job_id)
                    file_store.delete_job_dir(job.job_id)
        await asyncio.sleep(settings.cleanup_interval_seconds)
