"""Exposes registry tools to PydanticAI. Each tool forwards a ToolIntent to the gateway.

The toolset sees only name, description, and argument schema; it never holds an executor.
PydanticAI's own argument validation is skipped (`from_schema`), so the registry validates.
Under Temporal each call is its own activity; only idempotent tools are retried.
"""

from datetime import timedelta
from typing import Any

from pydantic import JsonValue
from pydantic_ai import ModelRetry, RunContext, Tool
from pydantic_ai.toolsets import FunctionToolset
from temporalio.common import RetryPolicy
from temporalio.workflow import ActivityConfig

from muse.agents.deps import AgentDeps
from muse.agents.runtime import agent_runtime
from muse.tools.gateway import InvalidToolArgs
from muse.tools.registry import ToolRegistry
from muse.tools.schema import ToolIntent, ToolSpec

TOOLSET_ID = "gateway"


def build_toolset(
    registry: ToolRegistry, exclude: frozenset[str] = frozenset()
) -> FunctionToolset[AgentDeps]:
    tools = [_gateway_tool(s) for s in registry.specs() if s.name not in exclude]
    return FunctionToolset(tools, id=TOOLSET_ID)


def _gateway_tool(spec: ToolSpec) -> Tool[AgentDeps]:
    tool_name = spec.name

    async def call(ctx: RunContext[AgentDeps], **kwargs: Any) -> JsonValue:
        gateway = agent_runtime().gateway(ctx.deps.exec_context())
        try:
            result = await gateway.invoke(ToolIntent(tool=tool_name, args=kwargs))
        except InvalidToolArgs as exc:
            raise ModelRetry(str(exc)) from exc
        if result.ok:
            return result.output
        return {"error": result.error}

    tool = Tool.from_schema(
        call,
        name=spec.model_name,
        description=spec.description,
        json_schema=spec.args_model.model_json_schema(),
        takes_ctx=True,
    )
    attempts = spec.retry.max_attempts if spec.idempotent else 1
    tool.metadata = {
        "temporal": ActivityConfig(
            start_to_close_timeout=timedelta(seconds=spec.timeout_s),
            retry_policy=RetryPolicy(maximum_attempts=attempts),
        )
    }
    return tool
