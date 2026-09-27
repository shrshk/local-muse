"""Summarizer agent: compacts older conversation turns into a running summary. No tools."""

from pydantic_ai import Agent
from pydantic_ai.models import Model

from muse.agents.coordinator import build_durability
from muse.agents.deps import AgentDeps

AGENT_NAME = "summarizer"

INSTRUCTIONS = """\
You maintain a running summary of a conversation between a user and their assistant, for the
assistant's own future reference. Merge the previous summary with the new messages. Keep facts,
decisions, commitments, and open questions; drop small talk. At most 200 words, plain prose.
Never include secrets, passwords, or credentials."""


def build_summarizer(model: Model, model_task_queue: str) -> Agent[AgentDeps, str]:
    return Agent(
        model,
        name=AGENT_NAME,
        deps_type=AgentDeps,
        output_type=str,
        instructions=INSTRUCTIONS,
        # Summaries are internal; no token streaming to the chat.
        capabilities=[build_durability(model_task_queue, stream_events=False)],
    )
