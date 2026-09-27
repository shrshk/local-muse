"""Workflow-side pauses shared by ConversationWorkflow and TopicWorkflow.

A run ends with DeferredToolRequests when a tool needs approval (`approvals`) or when a human has
the browser (`calls`, reason human_takeover). The workflow waits, durably, until every approval
is decided (the `decide_approval` Update) or expires, and every browser is handed back (the
`set_browser_mode` Update), then re-runs the agent with the answers. The gateway executes
approved calls itself; deferred browser calls are simply re-planned by the model.
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from pydantic_ai import (
        Agent,
        DeferredToolRequests,
        DeferredToolResults,
        ToolApproved,
        ToolDenied,
    )
    from pydantic_ai.agent import AgentRunResult
    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.usage import UsageLimits

    from muse.activities.approvals import (
        ApprovalActivities,
        ExpireApprovalsInput,
    )
    from muse.agents.deps import AgentDeps

ACTIVITY_TIMEOUT = timedelta(seconds=15)
ACTIVITY_RETRY = RetryPolicy(maximum_attempts=10, initial_interval=timedelta(seconds=1))
DENIED = "The user denied this action. Do not retry it."
EXPIRED = "Nobody approved this action in time. Do not retry it."
BROWSER_RETURNED = (
    "The user took control of the browser and has now handed it back. The page may have "
    "changed: take a new snapshot before acting."
)
BROWSER_NOT_RETURNED = "The user still has control of the browser. Do not use it now."


class BrowserModes:
    """Per-session control mode, as Temporal state. `agent` unless a human took over."""

    def __init__(self) -> None:
        self._modes: dict[str, str] = {}

    def set(self, session_id: uuid.UUID, mode: str) -> None:
        self._modes[str(session_id)] = mode

    def is_human(self, session_id: uuid.UUID) -> bool:
        return self._modes.get(str(session_id)) == "human"

    def ready(self, session_id: str) -> bool:
        return self._modes.get(session_id, "agent") == "agent"

    def as_dict(self) -> dict[str, str]:
        return dict(self._modes)


class ApprovalGate:
    def __init__(self) -> None:
        self._tool_calls: dict[uuid.UUID, str] = {}
        self._decisions: dict[uuid.UUID, bool | None] = {}

    def open(self, pending: dict[uuid.UUID, str]) -> None:
        self._tool_calls = dict(pending)
        self._decisions = {approval_id: None for approval_id in pending}

    def check(self, approval_id: uuid.UUID) -> None:
        """Update validator: reject anything this run is not waiting on."""
        if approval_id not in self._decisions:
            raise ValueError("this workflow is not waiting on that approval")
        if self._decisions[approval_id] is not None:
            raise ValueError("already decided")

    def record(self, approval_id: uuid.UUID, approved: bool) -> None:
        if self._decisions.get(approval_id, False) is None:
            self._decisions[approval_id] = approved

    def all_decided(self) -> bool:
        return all(d is not None for d in self._decisions.values())

    def undecided(self) -> list[uuid.UUID]:
        return [a for a, d in self._decisions.items() if d is None]

    def waiting(self) -> list[uuid.UUID]:
        return self.undecided()

    def results(self, expired: set[uuid.UUID]) -> DeferredToolResults:
        approvals: dict[str, bool | ToolApproved | ToolDenied] = {}
        for approval_id, tool_call_id in self._tool_calls.items():
            decision = self._decisions.get(approval_id)
            if decision:
                approvals[tool_call_id] = True
            else:
                approvals[tool_call_id] = ToolDenied(EXPIRED if approval_id in expired else DENIED)
        return DeferredToolResults(approvals=approvals)

    def clear(self) -> None:
        self._tool_calls = {}
        self._decisions = {}


async def run_with_approvals(
    agent: Agent[AgentDeps, Any],
    prompt: str,
    history: list[ModelMessage],
    deps: AgentDeps,
    limits: UsageLimits,
    gate: ApprovalGate,
    on_waiting: Callable[[list[uuid.UUID]], Awaitable[None]],
    wait_limit: timedelta,
    browsers: BrowserModes | None = None,
) -> AgentRunResult[Any]:
    result = await agent.run(prompt, message_history=history, deps=deps, usage_limits=limits)
    while isinstance(result.output, DeferredToolRequests):
        requests = result.output
        pending = {
            uuid.UUID(requests.metadata[call.tool_call_id]["approval_id"]): call.tool_call_id
            for call in requests.approvals
        }
        taken_over = {
            call.tool_call_id: requests.metadata.get(call.tool_call_id, {}).get("session_id", "")
            for call in requests.calls
        }
        gate.open(pending)
        if pending:
            await on_waiting(list(pending))

        def resumable(sessions: tuple[str, ...] = tuple(taken_over.values())) -> bool:
            browsers_back = browsers is None or all(browsers.ready(s) for s in sessions)
            return gate.all_decided() and browsers_back

        expired: set[uuid.UUID] = set()
        try:
            await workflow.wait_condition(resumable, timeout=wait_limit)
        except TimeoutError:
            if gate.undecided():
                expired = set(
                    await workflow.execute_activity_method(
                        ApprovalActivities.expire,
                        ExpireApprovalsInput(approval_ids=gate.undecided()),
                        start_to_close_timeout=ACTIVITY_TIMEOUT,
                        retry_policy=ACTIVITY_RETRY,
                    )
                )
        answers = gate.results(expired)
        answers.calls = {
            call_id: BROWSER_RETURNED
            if browsers is None or browsers.ready(session)
            else BROWSER_NOT_RETURNED
            for call_id, session in taken_over.items()
        }
        gate.clear()
        result = await agent.run(
            message_history=result.all_messages(),
            deferred_tool_results=answers,
            deps=deps,
            usage_limits=limits,
        )
    return result
