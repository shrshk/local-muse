"""Temporal worker entry point: `python -m muse.worker --role main|model`."""

import argparse
import asyncio
import signal
from dataclasses import dataclass

import httpx
from temporalio.client import Client
from temporalio.worker import Worker

from muse.activities.ops import ping
from muse.modules.health.probes import Probe, ProcessProbe, SandboxdProbe
from muse.sandbox.client import SandboxClient
from muse.shared.db import create_engine
from muse.shared.logger import configure_logging, get_logger
from muse.shared.settings import Settings, get_settings
from muse.worker.heartbeat import HeartbeatReporter

logger = get_logger(__name__)


@dataclass(frozen=True)
class Role:
    service: str
    task_queue: str
    max_concurrent_activities: int | None


class WorkerProcess:
    def __init__(self, role_name: str, settings: Settings) -> None:
        self._settings = settings
        self._role = self._resolve_role(role_name)

    def _resolve_role(self, name: str) -> Role:
        if name == "model":
            # One local model: the queue serializes inference, no scheduler needed.
            return Role("worker-model", self._settings.task_queue_model, 1)
        return Role("worker", self._settings.task_queue_main, None)

    def _probes(self, http: httpx.AsyncClient) -> list[Probe]:
        probes: list[Probe] = [ProcessProbe(self._role.service, self._role.task_queue)]
        if self._role.service == "worker":
            sandbox = SandboxClient(http, self._settings)
            probes.append(SandboxdProbe(sandbox, self._settings.probe_timeout_seconds))
        return probes

    async def run(self) -> None:
        client = await Client.connect(
            self._settings.temporal_address, namespace=self._settings.temporal_namespace
        )
        engine = create_engine(self._settings, pool_size=2)
        http = httpx.AsyncClient(timeout=self._settings.probe_timeout_seconds)
        worker = Worker(
            client,
            task_queue=self._role.task_queue,
            activities=[ping],
            max_concurrent_activities=self._role.max_concurrent_activities,
        )
        reporter = HeartbeatReporter(
            engine, self._probes(http), self._settings.heartbeat_interval_seconds
        )

        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)

        logger.info("worker_started", task_queue=self._role.task_queue)
        worker_task = asyncio.create_task(worker.run())
        reporter_task = asyncio.create_task(reporter.run(stop))
        stop_task = asyncio.create_task(stop.wait())
        try:
            await asyncio.wait({worker_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            stop.set()
            await worker.shutdown()
            await reporter_task
            await http.aclose()
            await engine.dispose()
            logger.info("worker_stopped", task_queue=self._role.task_queue)
        if worker_task.done() and (exc := worker_task.exception()) is not None:
            raise exc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=["main", "model"], default="main")
    args = parser.parse_args()
    settings = get_settings()
    configure_logging(f"worker-{args.role}", settings.log_level)
    asyncio.run(WorkerProcess(args.role, settings).run())


if __name__ == "__main__":
    main()
