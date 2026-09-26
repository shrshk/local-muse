"""Coordinator agent: answers directly and calls tools through the gateway."""

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model
from pydantic_ai.usage import UsageLimits

from muse.agents.deps import AgentDeps
from muse.agents.toolset import build_toolset
from muse.tools.registry import ToolRegistry

INSTRUCTIONS = """\
You are Local Muse, a personal assistant running entirely on the user's Mac.
Answer concisely. Use a tool when it gives a better answer than guessing, for example the
current date or time. Never invent tool results. If a tool returns an error, say so plainly."""

# One user turn may take at most this many model requests (each tool round-trip is one).
MAX_REQUESTS_PER_TURN = 8


class Coordinator:
    def __init__(self, model: Model, registry: ToolRegistry) -> None:
        self._agent = Agent(
            model,
            deps_type=AgentDeps,
            output_type=str,
            instructions=INSTRUCTIONS,
            toolsets=[build_toolset(registry)],
            retries=1,
        )

    async def reply(self, prompt: str, history: list[ModelMessage], deps: AgentDeps) -> str:
        result = await self._agent.run(
            prompt,
            message_history=history,
            deps=deps,
            usage_limits=UsageLimits(request_limit=MAX_REQUESTS_PER_TURN),
        )
        return result.output
