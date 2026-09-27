"""Process-level services for code that runs inside activities.

Activity functions are registered by PydanticAI, so they cannot take constructor arguments.
Each worker process configures this once at startup; nothing here crosses a durable boundary.
"""

from dataclasses import dataclass

from muse.policy.engine import PolicyEngine
from muse.realtime.publisher import RealtimePublisher
from muse.tools.gateway import ToolGateway
from muse.tools.recorder import ActionRecorder
from muse.tools.registry import ToolRegistry
from muse.tools.schema import ExecContext


@dataclass(frozen=True)
class AgentRuntime:
    registry: ToolRegistry
    policy: PolicyEngine
    recorder: ActionRecorder
    publisher: RealtimePublisher | None

    def gateway(self, ctx: ExecContext) -> ToolGateway:
        return ToolGateway(self.registry, self.policy, self.recorder, ctx)


_runtime: AgentRuntime | None = None


def configure_agent_runtime(runtime: AgentRuntime) -> None:
    global _runtime
    _runtime = runtime


def agent_runtime() -> AgentRuntime:
    if _runtime is None:
        raise RuntimeError("agent runtime not configured; call configure_agent_runtime() first")
    return _runtime
