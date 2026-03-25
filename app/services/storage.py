from dataclasses import dataclass

import httpx

from app.config import settings


class StorageError(Exception):
    pass


@dataclass
class UploadedAsset:
    release_id: int
    asset_url: str
    tag_name: str


class StorageAdapter:
    async def upload_signed_ipa(self, job_id: str, file_name: str, content: bytes) -> UploadedAsset:  # pragma: no cover - interface
        raise NotImplementedError

    async def delete_release(self, release_id: int) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class GitHubReleaseStorage(StorageAdapter):
    def __init__(self):
        if not settings.github_owner or not settings.github_repo or not settings.github_token:
            raise StorageError("GitHub storage is not configured")
        self.api_base = settings.github_api_base.rstrip("/")

    async def upload_signed_ipa(self, job_id: str, file_name: str, content: bytes) -> UploadedAsset:
        headers = {
            "Authorization": f"Bearer {settings.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        tag = f"tmp-{job_id}"
        release_payload = {
            "tag_name": tag,
            "name": f"Temporary {job_id}",
            "draft": False,
            "prerelease": True,
            "generate_release_notes": False,
        }

        async with httpx.AsyncClient(timeout=60) as client:
            release_resp = await client.post(
                f"{self.api_base}/repos/{settings.github_owner}/{settings.github_repo}/releases",
                headers=headers,
                json=release_payload,
            )
            if release_resp.status_code not in {200, 201, 422}:
                raise StorageError(f"GitHub release create failed: {release_resp.status_code} {release_resp.text}")

            if release_resp.status_code == 422:
                get_release = await client.get(
                    f"{self.api_base}/repos/{settings.github_owner}/{settings.github_repo}/releases/tags/{tag}",
                    headers=headers,
                )
                if get_release.status_code != 200:
                    raise StorageError(f"GitHub release fetch failed: {get_release.status_code} {get_release.text}")
                release_data = get_release.json()
            else:
                release_data = release_resp.json()

            upload_url_template = release_data["upload_url"]
            release_id = int(release_data["id"])
            upload_url = upload_url_template.split("{")[0]

            upload_resp = await client.post(
                f"{upload_url}?name={file_name}",
                headers={**headers, "Content-Type": "application/octet-stream"},
                content=content,
            )
            if upload_resp.status_code not in {200, 201}:
                raise StorageError(f"GitHub asset upload failed: {upload_resp.status_code} {upload_resp.text}")

            asset_data = upload_resp.json()
            download_url = asset_data.get("browser_download_url")
            if not download_url:
                raise StorageError("GitHub did not return browser_download_url")

            return UploadedAsset(release_id=release_id, asset_url=download_url, tag_name=tag)

    async def delete_release(self, release_id: int) -> None:
        headers = {
            "Authorization": f"Bearer {settings.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.delete(
                f"{self.api_base}/repos/{settings.github_owner}/{settings.github_repo}/releases/{release_id}",
                headers=headers,
            )
            if resp.status_code not in {204, 404}:
                raise StorageError(f"GitHub release delete failed: {resp.status_code} {resp.text}")
