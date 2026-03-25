import io
import zipfile


class SigningError(Exception):
    pass


class SignerService:
    """Production hook: integrate real signing binary/pipeline here."""

    def prevalidate(self, ipa_bytes: bytes, p12_bytes: bytes, p12_password: str, profile_bytes: bytes) -> None:
        if not p12_password:
            raise SigningError("Неверный пароль от .p12")
        if b"plist" not in profile_bytes:
            raise SigningError("Поврежденный provisioning profile")
        try:
            with zipfile.ZipFile(io.BytesIO(ipa_bytes), "r") as zf:
                names = zf.namelist()
                if not any(n.startswith("Payload/") for n in names):
                    raise SigningError("Поврежденный IPA: нет Payload")
        except zipfile.BadZipFile as exc:
            raise SigningError("Поврежденный IPA") from exc

    def sign(self, ipa_bytes: bytes, p12_bytes: bytes, p12_password: str, profile_bytes: bytes) -> bytes:
        self.prevalidate(ipa_bytes, p12_bytes, p12_password, profile_bytes)
        return ipa_bytes
