from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "SignBot Secure Gateway"
    public_base_url: str = "https://mydomain.com"
    telegram_bot_url: str = "https://t.me/my_bot"
    internal_api_token: str = "change-me"
    owner_telegram_id: int = 123456789
    database_url: str = "sqlite:///./signbot.db"
    max_ipa_size_bytes: int = 1024 * 1024 * 1024
    ttl_hours: int = 12

    github_token: str = ""
    github_owner: str = ""
    github_repo: str = ""
    github_api_base: str = "https://api.github.com"

    encryption_key: str = Field(
        default="PLEASE_CHANGE_ME_32_BYTE_SECRET_KEY__",
        description="32+ byte secret used to encrypt wallet payload",
    )
    private_storage_dir: str = "./private_storage"
    cleanup_interval_seconds: int = 60

    signer_mode: str = "mock"  # mock|external
    signer_command: str = ""  # e.g. rcodesign sign --p12 cert.p12 --password pass {target}


settings = Settings()
