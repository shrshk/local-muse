"""sandboxd configuration."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    log_level: str = "INFO"
    sandboxd_token: str = Field(min_length=32, repr=False)
    docker_url: str = "unix:///var/run/docker.sock"
    docker_timeout_seconds: float = 30.0
    sandbox_image: str = "local-muse-sandbox:1"
    max_running_sandboxes: int = 2


@lru_cache
def get_settings() -> Settings:
    return Settings()
