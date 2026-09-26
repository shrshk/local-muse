"""Exposes registry tools to PydanticAI. Each tool forwards a ToolIntent to the gateway.

The toolset sees only name, description, and argument schema; it never holds an executor.
PydanticAI's own argument validation is skipped (`from_schema`), so the registry validates.
"""

from typing import Any

from pydantic import JsonValue
from pydantic_ai import ModelRetry, RunContext, Tool
from pydantic_ai.toolsets import FunctionToolset

from muse.agents.deps import AgentDeps
from muse.tools.gateway import InvalidToolArgs
from muse.tools.registry import ToolRegistry
from muse.tools.schema import ToolIntent, ToolSpec


def build_toolset(registry: ToolRegistry) -> FunctionToolset[AgentDeps]:
    return FunctionToolset([_gateway_tool(s) for s in registry.specs()], id="gateway")


def _gateway_tool(spec: ToolSpec) -> Tool[AgentDeps]:
    tool_name = spec.name

    async def call(ctx: RunContext[AgentDeps], **kwargs: Any) -> JsonValue:
        try:
            result = await ctx.deps.tools.invoke(ToolIntent(tool=tool_name, args=kwargs))
        except InvalidToolArgs as exc:
            raise ModelRetry(str(exc)) from exc
        if result.ok:
            return result.output
        return {"error": result.error}

    return Tool.from_schema(
        call,
        name=spec.model_name,
        description=spec.description,
        json_schema=spec.args_model.model_json_schema(),
        takes_ctx=True,
    )
