from pathlib import Path

from app.config import settings


class PrivateFileStore:
    def __init__(self, base_dir: str | None = None):
        self.base = Path(base_dir or settings.private_storage_dir)
        self.base.mkdir(parents=True, exist_ok=True)

    def save_bytes(self, job_id: str, file_type: str, filename: str, data: bytes) -> str:
        job_dir = self.base / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        path = job_dir / f"{file_type}-{filename}"
        path.write_bytes(data)
        return str(path)

    def read_bytes(self, path: str) -> bytes:
        return Path(path).read_bytes()

    def delete_path(self, path: str) -> None:
        p = Path(path)
        if p.exists():
            p.unlink()

    def delete_job_dir(self, job_id: str) -> None:
        job_dir = self.base / job_id
        if not job_dir.exists():
            return
        for item in job_dir.iterdir():
            if item.is_file():
                item.unlink()
        job_dir.rmdir()
