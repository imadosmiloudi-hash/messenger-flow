from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Messenger Flow Operator"
    app_env: str = "development"
    secret_key: str = "change-me-to-a-long-random-string"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7

    admin_email: str = "admin@example.com"
    admin_password: str = "change-me-strong-password"

    database_url: str = "sqlite:///./data/app.db"
    redis_url: str = "redis://localhost:6379/0"

    meta_graph_api_version: str = "v26.0"
    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_verify_token: str = "your_webhook_verify_token"
    meta_page_access_token: str = ""
    meta_page_id: str = ""

    public_base_url: str = "http://localhost:8000"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    login_rate_limit: str = "10/minute"
    send_rate_limit: str = "30/minute"

    media_upload_dir: str = "./uploads"
    max_upload_mb: int = 25

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def meta_graph_base(self) -> str:
        return f"https://graph.facebook.com/{self.meta_graph_api_version}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
