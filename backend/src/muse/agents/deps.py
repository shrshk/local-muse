"""Agent dependencies. `tools` is the only path to any side effect."""

from dataclasses import dataclass

from muse.tools.gateway import ToolGateway
from muse.tools.schema import ExecContext


@dataclass
class AgentDeps:
    ctx: ExecContext
    tools: ToolGateway
