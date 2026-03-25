#!/usr/bin/env python3
"""Manual production smoke test for SignBot backend.

Usage:
  BACKEND_URL=http://127.0.0.1:8000 \
  INTERNAL_TOKEN=... \
  TELEGRAM_USER_ID=123 \
  APP_NAME='My App' \
  BUNDLE_ID='com.example.myapp' \
  IPA_PATH=/path/app.ipa \
  P12_PATH=/path/cert.p12 \
  PROFILE_PATH=/path/profile.mobileprovision \
  P12_PASSWORD='secret' \
  python scripts/e2e_smoke.py
"""

from __future__ import annotations

import os
import time
import uuid

import httpx


def getenv(name: str) -> str:
    value = os.getenv(name, "")
    if not value:
        raise SystemExit(f"Missing env: {name}")
    return value


def main() -> None:
    base = getenv("BACKEND_URL").rstrip("/")
    token = getenv("INTERNAL_TOKEN")
    user_id = int(getenv("TELEGRAM_USER_ID"))
    app_name = getenv("APP_NAME")
    bundle_id = getenv("BUNDLE_ID")
    ipa_path = getenv("IPA_PATH")
    p12_path = getenv("P12_PATH")
    profile_path = getenv("PROFILE_PATH")
    p12_password = getenv("P12_PASSWORD")

    headers = {"X-Internal-Token": token}
    job_id = f"e2e-{uuid.uuid4().hex}"

    with httpx.Client(timeout=120) as client:
        create = client.post(
            f"{base}/internal/jobs",
            headers=headers,
            json={
                "job_id": job_id,
                "telegram_user_id": user_id,
                "app_name": app_name,
                "bundle_id": bundle_id,
                "app_version": "1.0",
                "mode": "one_time",
            },
        )
        create.raise_for_status()
        public_url = create.json()["public_url"]
        print("Job created:", job_id)
        print("Public URL:", public_url)

        with open(ipa_path, "rb") as ipa, open(p12_path, "rb") as p12, open(profile_path, "rb") as prof:
            upload = client.post(
                f"{base}/internal/jobs/{job_id}/upload",
                headers=headers,
                data={"p12_password": p12_password},
                files={
                    "ipa": ("app.ipa", ipa, "application/octet-stream"),
                    "p12": ("cert.p12", p12, "application/x-pkcs12"),
                    "mobileprovision": ("profile.mobileprovision", prof, "application/octet-stream"),
                },
            )
        upload.raise_for_status()
        print("Upload accepted:", upload.json())

        for _ in range(60):
            status = client.get(f"{base}/internal/jobs/{job_id}", headers=headers)
            status.raise_for_status()
            body = status.json()
            print("State:", body["state"])
            if body["state"] in {"completed", "failed"}:
                print("Final:", body)
                break
            time.sleep(2)
        else:
            raise SystemExit("Timeout waiting for final state")


if __name__ == "__main__":
    main()
