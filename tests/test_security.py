import io
import zipfile

import pytest

from app.services.crypto import CryptoService
from app.validators import ValidationError, validate_file


def build_minimal_ipa() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Payload/App.app/Info.plist", "plist")
    return buf.getvalue()


def test_crypto_roundtrip():
    svc = CryptoService("secret-key")
    raw = b"super-secret"
    encrypted = svc.encrypt_to_b64(raw)
    assert svc.decrypt_from_b64(encrypted) == raw


def test_validate_file_rejects_wrong_signature():
    with pytest.raises(ValidationError):
        validate_file("app.ipa", b"not-an-ipa", 1024)


def test_validate_file_accepts_ipa():
    ipa = build_minimal_ipa()
    validate_file("app.ipa", ipa, 1024 * 1024)
