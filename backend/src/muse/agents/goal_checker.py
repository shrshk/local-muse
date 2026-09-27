"""Goal checker agent: runs one check and returns a comparable observation."""

from pydantic import BaseModel, Field
from pydantic_ai import Agent, DeferredToolRequests
from pydantic_ai.models import Model

from muse.agents.coordinator import build_durability
from muse.agents.deps import AgentDeps
from muse.agents.toolset import build_toolset
from muse.tools.registry import ToolRegistry

AGENT_NAME = "goal_checker"
NO_NESTED_WORK = frozenset({"topic.start", "goal.create"})
REQUEST_LIMIT = 20

INSTRUCTIONS = """\
You run one scheduled check for the user, without talking to them. Use tools when they help;
never invent tool results. Report:
- value: the answer in the shortest canonical form (a number, a word, a short phrase), worded
  the same way every time the underlying state is the same, so runs can be compared.
- condition_met: if a condition is given, whether it is true right now; otherwise null.
- summary: one or two sentences for the user."""


class GoalObservation(BaseModel):
    value: str = Field(max_length=200)
    condition_met: bool | None = None
    summary: str = Field(max_length=1000)


def build_goal_checker(
    model: Model, registry: ToolRegistry, model_task_queue: str
) -> Agent[AgentDeps, GoalObservation | DeferredToolRequests]:
    return Agent(
        model,
        name=AGENT_NAME,
        deps_type=AgentDeps,
        output_type=[GoalObservation, DeferredToolRequests],
        instructions=INSTRUCTIONS,
        toolsets=[build_toolset(registry, exclude=NO_NESTED_WORK)],
        retries=1,
        capabilities=[build_durability(model_task_queue)],
    )
