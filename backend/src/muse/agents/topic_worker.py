"""Topic worker agent: pursues one objective in the background and returns a structured report.

It gets the same gateway toolset minus topic.start (depth is 1).
"""

from pydantic import BaseModel, Field
from pydantic_ai import Agent, DeferredToolRequests
from pydantic_ai.models import Model

from muse.agents.coordinator import build_durability
from muse.agents.deps import AgentDeps
from muse.agents.toolset import build_toolset
from muse.tools.registry import ToolRegistry

AGENT_NAME = "topic_worker"
NO_TOPIC_TOOLS = frozenset({"topic.start", "goal.create"})

INSTRUCTIONS = """\
You are a Local Muse background worker. You pursue exactly one objective, given below, without
talking to the user. Use tools when they help; never invent tool results. When you are done,
return a concise report. List anything you could not finish under unfinished_work."""

DEFAULT_STEP_LIMIT = 60


class TopicReport(BaseModel):
    summary: str = Field(description="What you found or did, in a few sentences")
    decisions: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    unfinished_work: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)


def build_topic_worker(
    model: Model, registry: ToolRegistry, model_task_queue: str
) -> Agent[AgentDeps, TopicReport | DeferredToolRequests]:
    return Agent(
        model,
        name=AGENT_NAME,
        deps_type=AgentDeps,
        output_type=[TopicReport, DeferredToolRequests],
        instructions=INSTRUCTIONS,
        toolsets=[build_toolset(registry, exclude=NO_TOPIC_TOOLS)],
        retries=1,
        capabilities=[build_durability(model_task_queue)],
    )
