# SignBot Secure Gateway (Production-oriented)

Безопасная витрина для Telegram-бота подписи iOS приложений.

## Реализовано

- Landing page на `/` без directory listing.
- Install page на неугадываемом URL `/<random-id>-<app-name>`.
- Manifest endpoint `/manifest/{token}.plist` с HTTP 410 после истечения TTL.
- Внутреннее API `/internal/*` с токеном + owner-only admin/metrics маршруты.
- Машина состояний: `uploaded`, `queued`, `validating`, `signing`, `uploading`, `manifest_ready`, `completed`, `failed`, `expired`, `deleting`, `deleted`.
- Идемпотентность: повторный `job_id` возвращает существующий job.
- Wallet-режим хранения сертификатов в зашифрованном виде (Fernet over SHA-256 key material).
- Валидация файлов по extension + magic header + size limit (IPA до 1 ГБ).
- Pre-validation перед подписью:
  - корректность .p12/пароля,
  - срок действия сертификата,
  - срок действия provisioning profile,
  - проверка, что сертификат входит в profile,
  - совместимость bundle identifier (requested/IPA/profile).
- Signing pipeline:
  - `mock` режим (без внешнего бинаря),
  - `external` режим с рекурсивным обходом targets (`.framework`, `.appex`, `.bundle`, `.app`) и вызовом внешней команды.
- Автоматическая очистка по TTL: job -> expired -> deleting -> deleted,
  удаление GitHub release + локальных временных файлов.
- Recovery-проход для неконсистентных зависших job в середине пайплайна.

## Переменные окружения (.env)

```env
APP_NAME=SignBot Secure Gateway
PUBLIC_BASE_URL=https://mydomain.com
TELEGRAM_BOT_URL=https://t.me/my_bot
INTERNAL_API_TOKEN=change-me
OWNER_TELEGRAM_ID=123456789
DATABASE_URL=sqlite:///./signbot.db
MAX_IPA_SIZE_BYTES=1073741824
TTL_HOURS=12

GITHUB_TOKEN=ghp_xxx
GITHUB_OWNER=your-org-or-user
GITHUB_REPO=temporary-ipa-storage
GITHUB_API_BASE=https://api.github.com

ENCRYPTION_KEY=replace-with-strong-random-secret
PRIVATE_STORAGE_DIR=./private_storage
CLEANUP_INTERVAL_SECONDS=60

SIGNER_MODE=mock
SIGNER_COMMAND=
```

Пример для `SIGNER_COMMAND` (external mode):

```bash
SIGNER_MODE=external
SIGNER_COMMAND='rcodesign sign --pem-source cert.pem --entitlements entitlements.plist {target}'
```

## Локальный запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Внутренний workflow

1. Бот создаёт job через `POST /internal/jobs`.
2. Бот загружает `.ipa + .p12 + .mobileprovision + password` через `POST /internal/jobs/{job_id}/upload`.
3. Backend обрабатывает задачу фоном, валидирует, подписывает, загружает IPA в GitHub release.
4. Бот получает публичную install ссылку и отдаёт пользователю.
5. Через 12 часов release и локальные временные файлы удаляются.
6. Owner может смотреть `/internal/admin/jobs`, удалять jobs и читать `/internal/metrics`.
