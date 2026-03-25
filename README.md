# SignBot Secure Gateway

Безопасная витрина для Telegram-бота подписи iOS приложений.

## Что реализовано

- Landing page на `/` без листинга файлов.
- Install page по неугадываемой ссылке `/<random-id>-<app-name>`.
- Временные manifest endpoint'ы `/manifest/{token}.plist` с TTL.
- Внутреннее API `/internal/*` только по токену (и дополнительно ограничивается nginx).
- Машина состояний job'ов:
  `uploaded`, `queued`, `validating`, `signing`, `uploading`, `manifest_ready`, `completed`, `failed`, `expired`, `deleting`, `deleted`.
- Идемпотентное создание задач: повторный `job_id` возвращает существующую задачу.
- Базовая статистика.
- Фоновый цикл, который помечает задачи как `expired`.
- Nginx-конфиг с отключённым autoindex, блоком опасных файлов и HTTPS redirect.

## Быстрый старт

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Важно

- Текущий `GitHubReleaseStorage` в `app/services/storage.py` — заглушка интерфейса.
- Для production нужно подключить реальный GitHub API adapter и worker подписи.
- IPA не хранятся в этом приложении — только метаданные и выдача install/manifest.
