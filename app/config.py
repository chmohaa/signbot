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


settings = Settings()
