"""Provider selection. `offline` mode only ever builds a local provider."""

import httpx

from muse.models.ollama import OllamaProvider
from muse.shared.settings import Settings


class ProviderConfigError(Exception):
    pass


def build_provider(settings: Settings, probe_http: httpx.AsyncClient) -> OllamaProvider:
    if settings.local_muse_mode != "offline":
        raise ProviderConfigError(f"mode {settings.local_muse_mode!r} is not implemented in v1")
    if settings.model_provider != "ollama":
        raise ProviderConfigError(f"provider {settings.model_provider!r} is not local")
    return OllamaProvider(settings, probe_http)
