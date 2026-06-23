from __future__ import annotations

from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )

    app_env: str = Field(default="local", validation_alias="QUANT_APP_ENV")
    database_url: str = Field(
        default="sqlite+pysqlite:///quant_trading.db",
        validation_alias="DATABASE_URL",
    )
    require_auth: bool = Field(default=False, validation_alias="QUANT_REQUIRE_AUTH")
    api_token: str | None = Field(
        default=None,
        validation_alias="QUANT_API_TOKEN",
        repr=False,
    )
    auth_header: str = Field(default="Authorization", validation_alias="QUANT_AUTH_HEADER")
    public_routes: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["/health"],
        validation_alias="QUANT_PUBLIC_ROUTES",
    )
    job_executor: str = Field(default="inline", validation_alias="QUANT_JOB_EXECUTOR")
    redis_url: str = Field(default="redis://localhost:6379/0", validation_alias="REDIS_URL")
    trading_enabled: bool = Field(default=False, validation_alias="QUANT_TRADING_ENABLED")
    broker_mode: str = Field(default="simulated", validation_alias="QUANT_BROKER_MODE")

    @field_validator("public_routes", mode="before")
    @classmethod
    def parse_public_routes(cls, value: object) -> list[str]:
        if value is None or value == "":
            return ["/health"]
        if isinstance(value, str):
            routes = [item.strip() for item in value.split(",") if item.strip()]
            return routes or ["/health"]
        if isinstance(value, list):
            routes = [str(item).strip() for item in value if str(item).strip()]
            return routes or ["/health"]
        raise TypeError("QUANT_PUBLIC_ROUTES must be a comma-separated string or list")

    @field_validator("job_executor", mode="before")
    @classmethod
    def normalize_job_executor(cls, value: object) -> str:
        executor = str(value or "inline").strip().lower()
        if executor not in {"inline", "rq"}:
            raise ValueError("QUANT_JOB_EXECUTOR must be inline or rq")
        return executor

    @field_validator("broker_mode", mode="before")
    @classmethod
    def normalize_broker_mode(cls, value: object) -> str:
        broker_mode = str(value or "simulated").strip().lower()
        if broker_mode not in {"simulated", "dry_run"}:
            raise ValueError("QUANT_BROKER_MODE must be simulated or dry_run")
        return broker_mode

    @model_validator(mode="after")
    def require_api_token_for_auth(self) -> "AppSettings":
        if self.require_auth and not (self.api_token or "").strip():
            raise ValueError("QUANT_API_TOKEN is required when QUANT_REQUIRE_AUTH=true")
        if self.api_token is not None:
            self.api_token = self.api_token.strip() or None
        self.auth_header = self.auth_header.strip() or "Authorization"
        self.redis_url = self.redis_url.strip() or "redis://localhost:6379/0"
        self.broker_mode = self.broker_mode.strip() or "simulated"
        self.public_routes = [
            route if route.startswith("/") else f"/{route}" for route in self.public_routes
        ]
        return self
