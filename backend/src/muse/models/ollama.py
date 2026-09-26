"""Ollama over its OpenAI-compatible API. Runs natively on the host (llama.cpp + Metal)."""

import httpx
from openai import AsyncOpenAI
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider as PydanticOllamaProvider

from muse.models.provider import ProviderHealth
from muse.modules.health.health_schema import ComponentStatus
from muse.shared.settings import Settings


class OllamaProvider:
    name = "ollama"
    is_local = True

    def __init__(self, settings: Settings, probe_http: httpx.AsyncClient) -> None:
        self._base_url = settings.model_base_url.rstrip("/")
        self._model_name = settings.model_name
        self._probe_http = probe_http
        # Ollama ignores the key; the OpenAI client requires one.
        self._client = AsyncOpenAI(
            base_url=f"{self._base_url}/v1",
            api_key="ollama",
            timeout=settings.model_timeout_seconds,
            max_retries=1,
        )
        self._model = OpenAIChatModel(
            self._model_name, provider=PydanticOllamaProvider(openai_client=self._client)
        )

    def model(self) -> Model:
        return self._model

    async def health(self) -> ProviderHealth:
        try:
            response = await self._probe_http.get(f"{self._base_url}/api/tags")
            response.raise_for_status()
            models = {m["name"] for m in response.json().get("models", [])}
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            return self._health(
                ComponentStatus.OFFLINE, f"ollama unreachable ({type(exc).__name__})"
            )
        if self._model_name in models or f"{self._model_name}:latest" in models:
            return self._health(ComponentStatus.ONLINE, self._model_name)
        return self._health(ComponentStatus.DEGRADED, f"run: ollama pull {self._model_name}")

    def _health(self, status: ComponentStatus, detail: str) -> ProviderHealth:
        return ProviderHealth(
            provider=self.name, model=self._model_name, status=status, detail=detail
        )

    async def aclose(self) -> None:
        await self._client.close()
