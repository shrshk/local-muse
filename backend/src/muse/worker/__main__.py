"""Temporal worker entry point: `python -m muse.worker --role main|model`.

main   workflows, conversation activities, tool and tool-event activities (queue muse-main)
model  model-request activities only, one at a time (queue model-inference)
"""

import argparse
import asyncio
import pathlib
import signal
from collections.abc import Callable
from typing import Any

import httpx
from pydantic_ai.durable_exec.temporal import TemporalDurability
from temporalio.worker import Worker

from muse.activities.approvals import ApprovalActivities
from muse.activities.browser import BrowserActivities
from muse.activities.conversation import ConversationActivities
from muse.activities.goals import GoalActivities
from muse.activities.sandbox import SandboxActivities
from muse.activities.topics import TopicActivities
from muse.agents.instances import AGENTS
from muse.agents.runtime import AgentRuntime, configure_agent_runtime
from muse.browser.controller import BrowserController
from muse.modules.artifacts.store import ArtifactStore
from muse.modules.browser.taint import PostgresTaintStore
from muse.modules.goals.goal_scheduler import GoalScheduler
from muse.modules.health.probes import Probe, ProcessProbe, SandboxdProbe
from muse.policy.engine import PolicyEngine
from muse.realtime.publisher import RealtimePublisher
from muse.sandbox.client import SandboxClient
from muse.shared.db import create_engine
from muse.shared.logger import configure_logging, get_logger
from muse.shared.settings import Settings, get_settings
from muse.shared.temporal import connect_temporal
from muse.tools.approvals import PostgresApprovalStore, PostgresDomainAllowlist
from muse.tools.recorder import PostgresActionRecorder
from muse.tools.schema import ToolServices
from muse.tools.specs import build_registry
from muse.worker.heartbeat import HeartbeatReporter
from muse.worker.interceptors import HeartbeatInterceptor
from muse.workflows.conversation import ConversationWorkflow
from muse.workflows.goals import GoalRunWorkflow, GoalWorkflow
from muse.workflows.topic import TopicWorkflow

logger = get_logger(__name__)

MODEL_ACTIVITY_MARKER = "__model_"


def model_activities() -> list[Callable[..., Any]]:
    activities: list[Callable[..., Any]] = []
    for agent in AGENTS:
        durability = TemporalDurability.from_agent(agent)
        assert durability is not None
        activities += [
            a
            for a in durability.temporal_activities
            if MODEL_ACTIVITY_MARKER in getattr(a, "__temporal_activity_definition").name
        ]
    return activities


class WorkerProcess:
    def __init__(self, role: str, settings: Settings) -> None:
        self._role = role
        self._settings = settings
        self._service = "worker-model" if role == "model" else "worker"

    async def run(self) -> None:
        settings = self._settings
        client = await connect_temporal(settings)
        engine = create_engine(settings, pool_size=4)
        http = httpx.AsyncClient(timeout=settings.probe_timeout_seconds)
        publisher = RealtimePublisher(engine, http, settings)
        sandbox = SandboxClient(http, settings)
        artifacts = ArtifactStore(engine, pathlib.Path(settings.artifacts_dir))
        browser = (
            BrowserController(
                engine, artifacts, publisher, pathlib.Path(settings.browser_profile_dir)
            )
            if self._role == "main"
            else None
        )
        configure_agent_runtime(
            AgentRuntime(
                registry=build_registry(),
                policy=PolicyEngine(PostgresDomainAllowlist(engine), PostgresTaintStore(engine)),
                recorder=PostgresActionRecorder(engine),
                services=ToolServices(
                    engine=engine,
                    sandbox=sandbox if self._role == "main" else None,
                    artifacts=artifacts,
                    browser=browser,
                ),
                publisher=publisher,
                approvals=PostgresApprovalStore(engine),
            )
        )
        worker = self._build_worker(
            client,
            ConversationActivities(engine, publisher),
            TopicActivities(engine),
            SandboxActivities(engine, sandbox),
            ApprovalActivities(engine),
            BrowserActivities(engine, browser, publisher) if browser else None,
            GoalActivities(engine, publisher, GoalScheduler(client, settings.task_queue_main)),
        )
        reporter = HeartbeatReporter(
            engine, self._probes(http), settings.heartbeat_interval_seconds
        )

        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)

        logger.info("worker_started", role=self._role)
        worker_task = asyncio.create_task(worker.run())
        reporter_task = asyncio.create_task(reporter.run(stop))
        stop_task = asyncio.create_task(stop.wait())
        try:
            await asyncio.wait({worker_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            stop.set()
            await worker.shutdown()
            await reporter_task
            if browser:
                await browser.stop()
            await http.aclose()
            await engine.dispose()
            logger.info("worker_stopped", role=self._role)
        if worker_task.done() and (exc := worker_task.exception()) is not None:
            raise exc

    def _build_worker(
        self,
        client: Any,
        conversations: ConversationActivities,
        topics: TopicActivities,
        sandboxes: SandboxActivities,
        approvals: ApprovalActivities,
        browsers: BrowserActivities | None,
        goals: GoalActivities,
    ) -> Worker:
        if self._role == "model":
            # One local model: the queue serializes inference, no scheduler needed.
            return Worker(
                client,
                task_queue=self._settings.task_queue_model,
                activities=model_activities(),
                max_concurrent_activities=1,
                interceptors=[HeartbeatInterceptor()],
            )
        browser_activities: list[Callable[..., Any]] = (
            [browsers.set_mode, browsers.human_input, browsers.close] if browsers else []
        )
        # Agent activities are added by PydanticAIPlugin from the workflow's agents.
        return Worker(
            client,
            task_queue=self._settings.task_queue_main,
            workflows=[ConversationWorkflow, TopicWorkflow, GoalWorkflow, GoalRunWorkflow],
            activities=[
                conversations.persist_message,
                conversations.load_turn,
                conversations.load_compaction,
                conversations.save_summary,
                conversations.profile_context,
                conversations.publish_event,
                topics.claim_pending,
                topics.finish,
                sandboxes.release,
                approvals.record_decision,
                approvals.expire,
                *browser_activities,
                goals.activate_pending,
                goals.load,
                goals.record,
                goals.record_failure,
                goals.set_status,
            ],
            interceptors=[HeartbeatInterceptor()],
        )

    def _probes(self, http: httpx.AsyncClient) -> list[Probe]:
        queue = (
            self._settings.task_queue_model
            if self._role == "model"
            else self._settings.task_queue_main
        )
        probes: list[Probe] = [ProcessProbe(self._service, queue)]
        if self._role == "main":
            sandbox = SandboxClient(http, self._settings)
            probes.append(SandboxdProbe(sandbox, self._settings.probe_timeout_seconds))
        return probes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=["main", "model"], default="main")
    args = parser.parse_args()
    settings = get_settings()
    configure_logging(f"worker-{args.role}", settings.log_level)
    asyncio.run(WorkerProcess(args.role, settings).run())


if __name__ == "__main__":
    main()
