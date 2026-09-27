"""Process configuration, read once from the environment."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://muse:muse@postgres:5432/muse"

    temporal_address: str = "temporal:7233"
    temporal_namespace: str = "default"
    task_queue_main: str = "muse-main"
    task_queue_model: str = "model-inference"

    session_secret: str = Field(default="", repr=False)
    session_ttl_seconds: int = 7 * 24 * 3600
    session_cookie_secure: bool = False

    centrifugo_api_url: str = "http://centrifugo:8000/api"
    centrifugo_api_key: str = Field(default="", repr=False)
    centrifugo_token_secret: str = Field(default="", repr=False)
    centrifugo_token_ttl_seconds: int = 10 * 60

    sandboxd_url: str = "http://sandboxd:8080"
    sandboxd_token: str = Field(default="", repr=False)
    artifacts_dir: str = "/data/artifacts"

    local_muse_mode: Literal["offline", "hybrid", "cloud"] = "offline"
    model_provider: Literal["ollama"] = "ollama"
    model_base_url: str = "http://host.docker.internal:11434"
    model_name: str = "qwen3.8:27b"
    model_context_tokens: int = 32768
    model_timeout_seconds: float = 600.0
    chat_history_messages: int = 20
    history_token_budget: int = 8000

    probe_timeout_seconds: float = 2.0
    heartbeat_interval_seconds: float = 10.0
    heartbeat_stale_seconds: float = 30.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
