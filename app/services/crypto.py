import base64
import hashlib

from cryptography.fernet import Fernet


class CryptoService:
    def __init__(self, key_material: str):
        digest = hashlib.sha256(key_material.encode("utf-8")).digest()
        self.fernet = Fernet(base64.urlsafe_b64encode(digest))

    def encrypt_to_b64(self, raw: bytes) -> str:
        return base64.b64encode(self.fernet.encrypt(raw)).decode("utf-8")

    def decrypt_from_b64(self, enc_b64: str) -> bytes:
        return self.fernet.decrypt(base64.b64decode(enc_b64.encode("utf-8")))
