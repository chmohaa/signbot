# SignBot Secure Gateway (Production-oriented)

Безопасная витрина для Telegram-бота подписи iOS приложений.

## Реализовано

- Landing page на `/` без directory listing.
- Install page на неугадываемом URL `/<random-id>-<app-name>`.
- Manifest endpoint `/manifest/{token}.plist` с HTTP 410 после истечения TTL.
- Внутреннее API `/internal/*` с токеном + owner-only admin/metrics маршруты.
- Машина состояний: `uploaded`, `queued`, `validating`, `signing`, `uploading`, `manifest_ready`, `completed`, `failed`, `expired`, `deleting`, `deleted`.
- Wallet-хранение сертификатов в зашифрованном виде.
- Signing pipeline с двумя режимами:
  - `mock` (локальная разработка),
  - `external` (боевой режим с внешней командой signer).
- GitHub Releases как временное хранилище IPA + удаление по TTL.
- Recovery-проход для зависших неконсистентных задач.

## 1) Production env (пункт 1)

Используй шаблон `.env.production.example` и создай `.env`:

```bash
cp .env.production.example .env
```

Проверь критичные поля:
- `INTERNAL_API_TOKEN`
- `GITHUB_*`
- `ENCRYPTION_KEY`
- `SIGNER_MODE=external`
- `SIGNER_COMMAND=...`
- `TELEGRAM_BOT_TOKEN`
- `BACKEND_INTERNAL_URL`

## 2) Реальный signer toolchain (пункт 2)

`SignerService` в `external` режиме вызывает команду из `SIGNER_COMMAND` для каждого target (`.framework`, `.appex`, `.bundle`, `.app`).

Пример:

```bash
SIGNER_MODE=external
SIGNER_COMMAND='rcodesign sign --pem-source /etc/signbot/cert.pem --entitlements /etc/signbot/entitlements.plist {target}'
```

## 3) Telegram bot слой (пункт 3)

Добавлен `app/telegram_bot.py`:
- `/sign <bundle_id> <app_name>`
- пошаговый upload (`.ipa` -> `.p12` -> `.mobileprovision` -> пароль)
- отправка во внутренний backend API
- `/status <job_id>`

Запуск:

```bash
python -m app.telegram_bot
```

## 4) E2E smoke test (пункт 4)

Добавлен скрипт `scripts/e2e_smoke.py` для проверки полного цикла с **реальными файлами**:

```bash
BACKEND_URL=http://127.0.0.1:8000 \
INTERNAL_TOKEN=... \
TELEGRAM_USER_ID=123 \
APP_NAME='My App' \
BUNDLE_ID='com.example.app' \
IPA_PATH=/path/app.ipa \
P12_PATH=/path/cert.p12 \
PROFILE_PATH=/path/profile.mobileprovision \
P12_PASSWORD='secret' \
python scripts/e2e_smoke.py
```

## Локальный запуск API

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Внутренний workflow

1. Бот создаёт job через `POST /internal/jobs`.
2. Бот загружает `.ipa + .p12 + .mobileprovision + password` через `POST /internal/jobs/{job_id}/upload`.
3. Backend валидирует, подписывает и загружает IPA в GitHub release.
4. Пользователь получает install URL.
5. Через 12 часов release и временные данные удаляются.
