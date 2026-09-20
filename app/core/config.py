from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")
    database_url: SecretStr
    migration_database_url: SecretStr | None = None

    @field_validator("database_url", "migration_database_url")
    @classmethod
    def postgres_only(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            url = make_url(value.get_secret_value())
            if url.drivername != "postgresql+psycopg" or not url.database:
                raise ValueError("Use PostgreSQL with psycopg and an explicit database")
        return value


class Settings(DatabaseSettings):
    jwt_secret: SecretStr = Field(min_length=43)
    jwt_access_minutes: int = Field(default=30, ge=1, le=60)
    jwt_issuer: str = "nexo-api"
    jwt_audience: str = "nexo-admin"
    cors_origins: list[str] = ["http://localhost:4200"]
    storage_root: Path = Path("storage")
    video_max_bytes: int = Field(default=100 * 1024 * 1024, ge=1, le=100 * 1024 * 1024)
    video_max_seconds: int = Field(default=120, ge=1, le=120)

    @field_validator("cors_origins")
    @classmethod
    def explicit_origins(cls, value: list[str]) -> list[str]:
        if any("*" in origin for origin in value):
            raise ValueError("Use explicit origins")
        return value
