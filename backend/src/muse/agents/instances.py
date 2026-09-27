"""The process-wide coordinator agent.

Built at import because Temporal workflows reference agents at class-definition time and both
workers must register the same activity names.
"""

import httpx

from muse.agents.coordinator import build_coordinator
from muse.models.factory import build_provider
from muse.shared.settings import get_settings
from muse.tools.specs import build_registry

_settings = get_settings()
_provider = build_provider(_settings, httpx.AsyncClient(timeout=_settings.probe_timeout_seconds))

COORDINATOR = build_coordinator(_provider.model(), build_registry(), _settings.task_queue_model)
