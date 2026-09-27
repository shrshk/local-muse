"""Process-wide agents.

Built at import because Temporal workflows reference agents at class-definition time and every
worker must register the same activity names.
"""

import httpx

from muse.agents.coordinator import build_coordinator
from muse.agents.goal_checker import build_goal_checker
from muse.agents.summarizer import build_summarizer
from muse.agents.topic_worker import build_topic_worker
from muse.models.factory import build_provider
from muse.shared.settings import get_settings
from muse.tools.specs import build_registry

_settings = get_settings()
_provider = build_provider(_settings, httpx.AsyncClient(timeout=_settings.probe_timeout_seconds))
_registry = build_registry()

COORDINATOR = build_coordinator(_provider.model(), _registry, _settings.task_queue_model)
TOPIC_WORKER = build_topic_worker(_provider.model(), _registry, _settings.task_queue_model)
SUMMARIZER = build_summarizer(_provider.model(), _settings.task_queue_model)
GOAL_CHECKER = build_goal_checker(_provider.model(), _registry, _settings.task_queue_model)
AGENTS = (COORDINATOR, TOPIC_WORKER, SUMMARIZER, GOAL_CHECKER)
