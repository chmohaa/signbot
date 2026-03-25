from dataclasses import dataclass


@dataclass
class UploadedAsset:
    release_id: int
    asset_url: str


class StorageAdapter:
    async def upload_signed_ipa(self, job_id: str, file_name: str, content: bytes) -> UploadedAsset:  # pragma: no cover - interface
        raise NotImplementedError

    async def delete_release(self, release_id: int) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class GitHubReleaseStorage(StorageAdapter):
    """Stub adapter; integrate GitHub API (create release/upload asset/delete release) in production."""

    async def upload_signed_ipa(self, job_id: str, file_name: str, content: bytes) -> UploadedAsset:
        fake_release_id = abs(hash((job_id, file_name))) % 10_000_000
        return UploadedAsset(release_id=fake_release_id, asset_url=f"https://github.com/releases/{job_id}/{file_name}")

    async def delete_release(self, release_id: int) -> None:
        return None
