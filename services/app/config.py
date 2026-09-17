import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BOOK_", env_file=".env", extra="ignore")

    database_url: SecretStr = SecretStr("postgresql+psycopg://book:book@localhost:5432/book")
    public_url: str = "http://localhost:8000"
    secret_key: SecretStr | None = None
    secret_key_file: Path | None = None
    bootstrap_token: SecretStr | None = None
    bootstrap_token_file: Path | None = None
    cookie_secure: bool = True
    session_hours: int = 168
    web_dist: Path = Path("apps/web/dist")
    recovery_mode: bool = False
    db_pool_size: int = 5
    hardcover_url: str = "https://api.hardcover.app"
    openlibrary_url: str = "https://openlibrary.org"

    @field_validator("public_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.netloc or parts.username:
            raise ValueError("Use an HTTP(S) origin without credentials")
        if parts.path not in {"", "/"} or parts.query or parts.fragment:
            raise ValueError("Use an origin without a path, query or fragment")
        return value.rstrip("/")

    @model_validator(mode="after")
    def load_secrets(self) -> "Settings":
        if self.secret_key_file:
            self.secret_key = SecretStr(self.secret_key_file.read_text().strip())
        if self.bootstrap_token_file:
            self.bootstrap_token = SecretStr(self.bootstrap_token_file.read_text().strip())
        if self.secret_key:
            Fernet(self.secret_key.get_secret_value().encode())
        return self

    def encryption_key(self) -> bytes:
        if not self.secret_key:
            raise RuntimeError("Configure BOOK_SECRET_KEY or BOOK_SECRET_KEY_FILE before startup")
        return self.secret_key.get_secret_value().encode()

    @property
    def psycopg_url(self) -> str:
        return self.database_url.get_secret_value().replace(
            "postgresql+psycopg://", "postgresql://"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings(_env_file=os.environ.get("BOOK_ENV_FILE", ".env") or None)
