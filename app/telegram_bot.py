from __future__ import annotations

import asyncio
import tempfile
import uuid
from dataclasses import dataclass, field

import httpx
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from app.config import settings

WAIT_IPA, WAIT_P12, WAIT_PROFILE, WAIT_PASSWORD = range(4)


@dataclass
class SessionDraft:
    job_id: str
    app_name: str
    bundle_id: str
    ipa_path: str | None = None
    p12_path: str | None = None
    profile_path: str | None = None
    p12_password: str | None = None
    files: list[str] = field(default_factory=list)


class BackendClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.headers = {"X-Internal-Token": token}

    async def create_job(self, telegram_user_id: int, app_name: str, bundle_id: str) -> dict:
        job_id = f"tg-{telegram_user_id}-{uuid.uuid4().hex}"
        payload = {
            "job_id": job_id,
            "telegram_user_id": telegram_user_id,
            "app_name": app_name,
            "bundle_id": bundle_id,
            "app_version": "1.0",
            "mode": "one_time",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{self.base_url}/internal/jobs", json=payload, headers=self.headers)
            resp.raise_for_status()
            return resp.json()

    async def upload_job(self, job_id: str, ipa_path: str, p12_path: str, profile_path: str, p12_password: str) -> dict:
        files = {
            "ipa": ("app.ipa", open(ipa_path, "rb"), "application/octet-stream"),
            "p12": ("cert.p12", open(p12_path, "rb"), "application/x-pkcs12"),
            "mobileprovision": ("profile.mobileprovision", open(profile_path, "rb"), "application/octet-stream"),
        }
        data = {"p12_password": p12_password}
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{self.base_url}/internal/jobs/{job_id}/upload",
                    files=files,
                    data=data,
                    headers=self.headers,
                )
                resp.raise_for_status()
                return resp.json()
        finally:
            for _, f in files.values():
                f.close()

    async def status(self, job_id: str) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{self.base_url}/internal/jobs/{job_id}", headers=self.headers)
            resp.raise_for_status()
            return resp.json()


def get_backend_client() -> BackendClient:
    backend_base = settings.backend_internal_url.rstrip("/")
    return BackendClient(backend_base, settings.internal_api_token)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Привет! Используй: /sign <bundle_id> <app_name>.\n"
        "Потом по шагам отправь IPA, P12, mobileprovision и пароль."
    )


async def sign_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if len(context.args) < 2:
        await update.message.reply_text("Формат: /sign <bundle_id> <app_name>")
        return ConversationHandler.END

    bundle_id = context.args[0]
    app_name = " ".join(context.args[1:])
    backend = get_backend_client()

    data = await backend.create_job(update.effective_user.id, app_name, bundle_id)
    draft = SessionDraft(job_id=data["job_id"], app_name=app_name, bundle_id=bundle_id)
    context.user_data["draft"] = draft

    await update.message.reply_text(f"Job создан: {draft.job_id}. Пришли .ipa файлом")
    return WAIT_IPA


async def receive_ipa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft: SessionDraft = context.user_data["draft"]
    doc = update.message.document
    if not doc or not doc.file_name.lower().endswith(".ipa"):
        await update.message.reply_text("Нужен файл .ipa")
        return WAIT_IPA

    path = await _download_doc(doc, suffix=".ipa")
    draft.ipa_path = path
    draft.files.append(path)
    await update.message.reply_text("Ок. Теперь пришли .p12")
    return WAIT_P12


async def receive_p12(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft: SessionDraft = context.user_data["draft"]
    doc = update.message.document
    if not doc or not doc.file_name.lower().endswith(".p12"):
        await update.message.reply_text("Нужен файл .p12")
        return WAIT_P12

    path = await _download_doc(doc, suffix=".p12")
    draft.p12_path = path
    draft.files.append(path)
    await update.message.reply_text("Отлично. Теперь пришли .mobileprovision")
    return WAIT_PROFILE


async def receive_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft: SessionDraft = context.user_data["draft"]
    doc = update.message.document
    if not doc or not doc.file_name.lower().endswith(".mobileprovision"):
        await update.message.reply_text("Нужен файл .mobileprovision")
        return WAIT_PROFILE

    path = await _download_doc(doc, suffix=".mobileprovision")
    draft.profile_path = path
    draft.files.append(path)
    await update.message.reply_text("Теперь отправь пароль от p12 обычным сообщением")
    return WAIT_PASSWORD


async def receive_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft: SessionDraft = context.user_data["draft"]
    draft.p12_password = update.message.text.strip()

    backend = get_backend_client()
    await backend.upload_job(draft.job_id, draft.ipa_path, draft.p12_path, draft.profile_path, draft.p12_password)

    status = await backend.status(draft.job_id)
    await update.message.reply_text(
        f"Задача принята: {status['job_id']}\nСтатус: {status['state']}\nСсылка: {status['public_url']}"
    )
    _cleanup_draft(context)
    return ConversationHandler.END


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 1:
        await update.message.reply_text("Формат: /status <job_id>")
        return
    backend = get_backend_client()
    data = await backend.status(context.args[0])
    await update.message.reply_text(f"{data['job_id']} => {data['state']}\n{data['public_url']}")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _cleanup_draft(context)
    await update.message.reply_text("Отменено")
    return ConversationHandler.END


async def _download_doc(doc, suffix: str) -> str:
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tf:
        path = tf.name
    file = await doc.get_file()
    await file.download_to_drive(custom_path=path)
    return path


def _cleanup_draft(context: ContextTypes.DEFAULT_TYPE) -> None:
    draft: SessionDraft | None = context.user_data.pop("draft", None)
    if not draft:
        return
    for path in draft.files:
        try:
            import os

            os.remove(path)
        except OSError:
            pass


def build_app() -> Application:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

    app = Application.builder().token(settings.telegram_bot_token).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("sign", sign_start)],
        states={
            WAIT_IPA: [MessageHandler(filters.Document.ALL, receive_ipa)],
            WAIT_P12: [MessageHandler(filters.Document.ALL, receive_p12)],
            WAIT_PROFILE: [MessageHandler(filters.Document.ALL, receive_profile)],
            WAIT_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_password)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(conv)
    return app


def run_bot() -> None:
    app = build_app()
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    run_bot()
