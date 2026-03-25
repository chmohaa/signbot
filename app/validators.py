from pathlib import Path

ALLOWED_EXTENSIONS = {".ipa", ".p12", ".mobileprovision", ".png", ".jpg", ".jpeg"}
ZIP_MAGIC = b"PK\x03\x04"


def sanitize_filename(name: str) -> str:
    cleaned = "".join(c for c in name if c.isalnum() or c in {"-", "_", "."})
    return cleaned[:180]


def validate_extension(name: str) -> bool:
    return Path(name).suffix.lower() in ALLOWED_EXTENSIONS


def validate_magic(name: str, content: bytes) -> bool:
    ext = Path(name).suffix.lower()
    if ext == ".ipa":
        return content.startswith(ZIP_MAGIC)
    if ext in {".png"}:
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in {".jpg", ".jpeg"}:
        return content.startswith(b"\xff\xd8\xff")
    if ext == ".p12":
        return content.startswith(b"0\x82")
    if ext == ".mobileprovision":
        return b"<?xml" in content or b"plist" in content
    return False
