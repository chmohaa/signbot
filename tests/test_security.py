import io
import zipfile

import pytest

from app.services.crypto import CryptoService
from app.services.signer import SignerService, SigningError
from app.validators import ValidationError, validate_file


def build_minimal_ipa() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Payload/App.app/Info.plist", b"<?xml version='1.0'?><plist version='1.0'><dict><key>CFBundleIdentifier</key><string>com.test.app</string></dict></plist>")
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


def test_signer_fails_invalid_p12():
    signer = SignerService()
    ipa = build_minimal_ipa()
    with pytest.raises(SigningError):
        signer.prevalidate(
            ipa_bytes=ipa,
            p12_bytes=b"bad-p12",
            p12_password="wrong",
            profile_bytes=b"<?xml version='1.0'?><plist version='1.0'><dict><key>ExpirationDate</key><date>2099-01-01T00:00:00Z</date><key>Entitlements</key><dict><key>application-identifier</key><string>ABCDE.com.test.*</string></dict></dict></plist>",
            expected_bundle_id="com.test.app",
        )
