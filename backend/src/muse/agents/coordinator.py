"""Coordinator agent: answers directly and calls tools through the gateway.

Durable through PydanticAI's TemporalDurability: inside a workflow, model requests and tool calls
become activities; outside one (unit tests) the capability is transparent.
"""

from datetime import timedelta

from pydantic_ai import Agent
from pydantic_ai.durable_exec.temporal import TemporalDurability
from pydantic_ai.models import Model
from temporalio.common import RetryPolicy
from temporalio.workflow import ActivityConfig

from muse.agents.deps import AgentDeps
from muse.agents.events import publish_run_events
from muse.agents.toolset import build_toolset
from muse.tools.registry import ToolRegistry

AGENT_NAME = "coordinator"

INSTRUCTIONS = """\
You are Local Muse, a personal assistant running entirely on the user's Mac.
Answer concisely. Use a tool when it gives a better answer than guessing, for example the
current date or time. Never invent tool results. If a tool returns an error, say so plainly.
When the user tells you a lasting fact about themselves (preferences, constraints, devices,
standing choices), save it with profile_remember. Never save secrets or passwords.
For longer, separable work, start a background topic with topic_start (one call per topic) and
tell the user it is running; you will receive its result later as an [event] message.
When an [event] reports a topic result, relay the useful parts to the user; do not start new
topics in reply to an [event]."""

# One user turn may take at most this many model requests (each tool round-trip is one).
MAX_REQUESTS_PER_TURN = 8


def build_durability(
    model_task_queue: str, *, stream_events: bool = True
) -> TemporalDurability[AgentDeps]:
    return TemporalDurability(
        event_stream_handler=publish_run_events if stream_events else None,
        activity_config=ActivityConfig(
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        ),
        # A dense local model can take minutes; heartbeats (worker interceptor) catch dead workers.
        model_activity_config=ActivityConfig(
            task_queue=model_task_queue,
            start_to_close_timeout=timedelta(minutes=10),
            heartbeat_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=2)),
        ),
    )


def build_coordinator(
    model: Model, registry: ToolRegistry, model_task_queue: str
) -> Agent[AgentDeps, str]:
    return Agent(
        model,
        name=AGENT_NAME,
        deps_type=AgentDeps,
        output_type=str,
        instructions=INSTRUCTIONS,
        toolsets=[build_toolset(registry)],
        retries=1,
        capabilities=[build_durability(model_task_queue)],
    )
