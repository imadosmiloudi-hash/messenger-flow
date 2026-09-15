from functools import lru_cache
from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict

# Canonical Facebook OAuth callback path (no trailing slash).
META_OAUTH_CALLBACK_PATH = "/api/integrations/facebook/callback"

_PLACEHOLDER_HOST_MARKERS = (
    "your-ngrok-or-domain.example",
    "your-domain.example",
    "example.invalid",
)


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
    # Optional; defaults to canonical public origin + META_OAUTH_CALLBACK_PATH
    meta_redirect_uri: str = ""
    meta_oauth_scopes: str = (
        "pages_show_list,pages_messaging,pages_manage_metadata,"
        "pages_read_engagement,business_management"
    )

    # Composio (preferred when configured / MESSAGING_PROVIDER=composio)
    composio_api_key: str = ""
    composio_connected_account_id: str = "facebook_alvar-therm"
    composio_user_id: str = "default"
    messaging_provider: str = "composio"  # composio|meta

    public_base_url: str = "http://localhost:8000"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Railway-injected public host hints (optional)
    railway_public_domain: str = ""
    railway_service_web_url: str = ""

    login_rate_limit: str = "10/minute"
    send_rate_limit: str = "120/minute"

    media_upload_dir: str = "./uploads"
    max_upload_mb: int = 25

    # Micro-gap between sequential media sends in one step (ms) to avoid Meta/Composio rate limits
    flow_media_gap_ms: int = 40

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def meta_graph_base(self) -> str:
        return f"https://graph.facebook.com/{self.meta_graph_api_version}"

    @property
    def sqlalchemy_database_url(self) -> str:
        url = self.database_url
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        if url.startswith("postgresql://") and "+psycopg" not in url.split("://", 1)[0]:
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        return url

    @staticmethod
    def _origin_from_url(value: str) -> str | None:
        """Normalize a URL or bare host to scheme://host[:port] with no trailing slash."""
        raw = (value or "").strip()
        if not raw:
            return None
        if "://" not in raw:
            raw = f"https://{raw.lstrip('/')}"
        parsed = urlparse(raw)
        if not parsed.scheme or not parsed.netloc or not parsed.hostname:
            return None
        try:
            port = f":{parsed.port}" if parsed.port is not None else ""
        except ValueError:
            return None
        host = parsed.hostname.lower()
        host = f"[{host}]" if ":" in host else host
        return f"{parsed.scheme.lower()}://{host}{port}"

    @property
    def is_production(self) -> bool:
        return (self.app_env or "").strip().lower() in {"production", "prod"}

    @property
    def canonical_public_base_url(self) -> str:
        """
        Resolve public HTTPS origin for OAuth / webhooks.

        Preference order:
        1. META_REDIRECT_URI host (path ignored; callback path is forced)
        2. PUBLIC_BASE_URL
        3. RAILWAY_PUBLIC_DOMAIN / RAILWAY_SERVICE_WEB_URL when present
        """
        candidates: list[str] = []
        if (self.meta_redirect_uri or "").strip():
            candidates.append(self.meta_redirect_uri.strip())
        railway_hints = [
            value.strip()
            for value in (self.railway_public_domain, self.railway_service_web_url)
            if (value or "").strip()
        ]
        public_base = (self.public_base_url or "").strip()
        # Do not let the implicit development default hide a Railway-provided host.
        # An explicitly configured localhost PUBLIC_BASE_URL is retained and rejected in production.
        public_is_implicit_dev_default = (
            public_base == "http://localhost:8000"
            and "public_base_url" not in self.model_fields_set
        )
        if public_base and not (public_is_implicit_dev_default and railway_hints):
            candidates.append(public_base)
        candidates.extend(railway_hints)

        for candidate in candidates:
            origin = self._origin_from_url(candidate)
            if origin:
                return origin
        # Development default
        return "http://localhost:8000"

    @property
    def resolved_meta_redirect_uri(self) -> str:
        """Always canonical origin + /api/integrations/facebook/callback (no trailing slash)."""
        base = self.canonical_public_base_url.rstrip("/")
        return f"{base}{META_OAUTH_CALLBACK_PATH}"

    @property
    def oauth_redirect_host(self) -> str:
        return (urlparse(self.resolved_meta_redirect_uri).hostname or "").lower()

    def production_oauth_redirect_error(self) -> str | None:
        """
        In production, reject localhost, http, and placeholder domains.
        Returns an operator-facing error message, or None when OK / non-production.
        """
        if not self.is_production:
            return None

        uri = self.resolved_meta_redirect_uri
        parsed = urlparse(uri)
        host = (parsed.hostname or "").lower()
        scheme = (parsed.scheme or "").lower()

        problems: list[str] = []
        if scheme != "https":
            problems.append("must use https (not http)")
        if not host:
            problems.append("missing host")
        elif host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".localhost"):
            problems.append("must not use localhost")
        else:
            reserved_placeholder = host.endswith((".example", ".invalid", ".test"))
            for marker in _PLACEHOLDER_HOST_MARKERS:
                if marker in host:
                    reserved_placeholder = True
                    break
            if reserved_placeholder:
                problems.append(f"placeholder host ({host}) is not allowed")

        path = parsed.path or ""
        if path.rstrip("/") != META_OAUTH_CALLBACK_PATH:
            problems.append(f"path must be exactly {META_OAUTH_CALLBACK_PATH}")

        if not problems:
            return None

        return (
            "Production OAuth redirect is invalid ("
            + "; ".join(problems)
            + "). Owner must set PUBLIC_BASE_URL and/or META_REDIRECT_URI to the "
            "public HTTPS API origin (see docs/CONNECT_FACEBOOK.md)."
        )

    @property
    def meta_oauth_scope_list(self) -> list[str]:
        return [s.strip() for s in (self.meta_oauth_scopes or "").split(",") if s.strip()]

    def uses_composio(self) -> bool:
        """Prefer Composio when configured; honor explicit MESSAGING_PROVIDER."""
        provider = (self.messaging_provider or "").strip().lower()
        if provider == "meta":
            return False
        if provider == "composio":
            return bool(self.composio_api_key)
        # auto / empty: prefer composio when key + connected account present
        return bool(self.composio_api_key and self.composio_connected_account_id)


@lru_cache
def get_settings() -> Settings:
    return Settings()
