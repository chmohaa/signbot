import io
import plistlib
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding, pkcs12


class SigningError(Exception):
    pass


class SignerService:
    """Production signer with certificate/profile validation and pluggable external signer command."""

    def __init__(self, signer_mode: str = "mock", signer_command: str | None = None):
        self.signer_mode = signer_mode
        self.signer_command = signer_command

    def prevalidate(
        self,
        ipa_bytes: bytes,
        p12_bytes: bytes,
        p12_password: str,
        profile_bytes: bytes,
        expected_bundle_id: str,
    ) -> None:
        cert = self._validate_p12(p12_bytes, p12_password)
        profile = self._parse_mobileprovision(profile_bytes)
        self._validate_profile(profile)
        self._validate_profile_cert_match(profile, cert)

        ipa_bundle_id = self._extract_ipa_bundle_id(ipa_bytes)
        profile_bundle_id = self._profile_bundle_id(profile)
        if not self._bundle_id_compatible(expected_bundle_id, profile_bundle_id):
            raise SigningError("Несовместимый bundle identifier: profile vs requested app")
        if not self._bundle_id_compatible(ipa_bundle_id, profile_bundle_id):
            raise SigningError("Несовместимый bundle identifier: profile vs ipa")

    def sign(
        self,
        ipa_bytes: bytes,
        p12_bytes: bytes,
        p12_password: str,
        profile_bytes: bytes,
        expected_bundle_id: str,
    ) -> bytes:
        self.prevalidate(ipa_bytes, p12_bytes, p12_password, profile_bytes, expected_bundle_id)

        if self.signer_mode == "mock":
            return ipa_bytes

        if self.signer_mode != "external" or not self.signer_command:
            raise SigningError("Signer is not configured")

        return self._sign_with_external_command(ipa_bytes, self.signer_command)

    def _validate_p12(self, p12_bytes: bytes, password: str) -> x509.Certificate:
        try:
            _, cert, _ = pkcs12.load_key_and_certificates(p12_bytes, password.encode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise SigningError("Неверный пароль от .p12 или поврежденный p12") from exc

        if cert is None:
            raise SigningError("В .p12 отсутствует сертификат")

        now = datetime.now(timezone.utc)
        not_after = cert.not_valid_after_utc if hasattr(cert, "not_valid_after_utc") else cert.not_valid_after.replace(tzinfo=timezone.utc)
        if not_after < now:
            raise SigningError("Сертификат истёк")
        return cert

    def _parse_mobileprovision(self, raw: bytes) -> dict:
        start = raw.find(b"<?xml")
        end = raw.rfind(b"</plist>")
        if start == -1 or end == -1:
            raise SigningError("Поврежденный provisioning profile")
        plist_bytes = raw[start : end + len(b"</plist>")]
        try:
            return plistlib.loads(plist_bytes)
        except Exception as exc:  # noqa: BLE001
            raise SigningError("Некорректный provisioning profile") from exc

    def _validate_profile(self, profile: dict) -> None:
        exp = profile.get("ExpirationDate")
        if not exp:
            raise SigningError("Provisioning profile не содержит ExpirationDate")
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            raise SigningError("Provisioning profile истёк")

    def _validate_profile_cert_match(self, profile: dict, cert: x509.Certificate) -> None:
        dev_certs = profile.get("DeveloperCertificates", [])
        cert_der = cert.public_bytes(encoding=Encoding.DER)
        if dev_certs and cert_der not in dev_certs:
            raise SigningError("Сертификат не входит в provisioning profile")

    def _extract_ipa_bundle_id(self, ipa_bytes: bytes) -> str:
        try:
            with zipfile.ZipFile(io.BytesIO(ipa_bytes), "r") as zf:
                names = zf.namelist()
                info_plist = next((n for n in names if n.startswith("Payload/") and n.endswith(".app/Info.plist")), None)
                if not info_plist:
                    raise SigningError("Поврежденный IPA: отсутствует Info.plist")
                data = plistlib.loads(zf.read(info_plist))
                bundle_id = data.get("CFBundleIdentifier")
                if not bundle_id:
                    raise SigningError("CFBundleIdentifier не найден в IPA")
                return bundle_id
        except zipfile.BadZipFile as exc:
            raise SigningError("Поврежденный IPA") from exc

    def _profile_bundle_id(self, profile: dict) -> str:
        ent = profile.get("Entitlements", {})
        app_id = ent.get("application-identifier") or ent.get("com.apple.application-identifier")
        if not app_id or "." not in app_id:
            raise SigningError("В profile отсутствует application-identifier")
        return app_id.split(".", 1)[1]

    def _bundle_id_compatible(self, bundle_id: str, profile_bundle_id: str) -> bool:
        if profile_bundle_id.endswith("*"):
            return bundle_id.startswith(profile_bundle_id[:-1])
        return bundle_id == profile_bundle_id

    def _sign_with_external_command(self, ipa_bytes: bytes, command: str) -> bytes:
        temp_dir = Path(tempfile.mkdtemp(prefix="signbot-sign-"))
        try:
            input_ipa = temp_dir / "input.ipa"
            work_dir = temp_dir / "work"
            output_ipa = temp_dir / "signed.ipa"
            input_ipa.write_bytes(ipa_bytes)

            with zipfile.ZipFile(input_ipa, "r") as zf:
                zf.extractall(work_dir)

            sign_targets = self._collect_signing_targets(work_dir)
            for target in sign_targets:
                cmd = command.format(target=str(target))
                result = subprocess.run(cmd, shell=True, text=True, capture_output=True)
                if result.returncode != 0:
                    raise SigningError(f"External signer failed on {target.name}: {result.stderr[:300]}")

            self._zip_directory(work_dir, output_ipa)
            return output_ipa.read_bytes()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _collect_signing_targets(self, root: Path) -> list[Path]:
        payload = root / "Payload"
        if not payload.exists():
            raise SigningError("IPA payload missing")
        targets: list[Path] = []
        for app in payload.glob("*.app"):
            for fw in app.rglob("*.framework"):
                targets.append(fw)
            for appex in app.rglob("*.appex"):
                targets.append(appex)
            for plugin in app.rglob("*.bundle"):
                targets.append(plugin)
            targets.append(app)
        return targets

    def _zip_directory(self, source_dir: Path, output_path: Path) -> None:
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in source_dir.rglob("*"):
                if path.is_file():
                    zf.write(path, path.relative_to(source_dir))
