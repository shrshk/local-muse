"""Goals. GoalWorkflow (`goal-<id>`): a durable timer, then one check. GoalRunWorkflow: one check,
started by GoalWorkflow or by the goal's Temporal Schedule for recurring goals. No sleep loops."""

import asyncio
import uuid
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from muse.workflows.approvals import ApprovalGate, run_with_approvals

with workflow.unsafe.imports_passed_through():
    import annotated_types  # noqa: F401  # pydantic imports it lazily; keep it out of the sandbox
    from pydantic_ai.durable_exec.temporal import PydanticAIWorkflow
    from pydantic_ai.exceptions import AgentRunError
    from pydantic_ai.messages import ModelMessage, ModelRequest, SystemPromptPart
    from pydantic_ai.usage import UsageLimits

    from muse.activities.approvals import ApprovalActivities, ApprovalDecisionInput
    from muse.activities.browser import BrowserActivities, BrowserCloseInput
    from muse.activities.conversation import ConversationActivities
    from muse.activities.goals import (
        GoalActivities,
        GoalSpec,
        GoalStatusInput,
        RecordFailureInput,
        RecordObservationInput,
    )
    from muse.activities.sandbox import ReleaseSandboxInput, SandboxActivities
    from muse.agents.deps import AgentDeps
    from muse.agents.goal_checker import REQUEST_LIMIT
    from muse.agents.instances import GOAL_CHECKER
    from muse.modules.goals.goal_scheduler import GoalInput, GoalRunInput
    from muse.modules.goals.goals_schema import GoalStatus
    from muse.workflows.schema import APPROVAL_TIMEOUT_S, ProfileContextInput

TIMEOUT = timedelta(seconds=15)
RETRY = RetryPolicy(maximum_attempts=10, initial_interval=timedelta(seconds=1))


@workflow.defn(name="GoalWorkflow")
class GoalWorkflow:
    @workflow.run
    async def run(self, goal: GoalInput) -> None:
        delay = goal.fire_at - workflow.now()
        try:
            if delay > timedelta(0):
                await workflow.sleep(delay)  # a Temporal timer: survives any restart
            await workflow.execute_child_workflow(
                GoalRunWorkflow.run,
                GoalRunInput(goal_id=goal.goal_id),
                id=f"goal-{goal.goal_id}-run",
            )
        except asyncio.CancelledError:
            await workflow.execute_activity_method(
                GoalActivities.set_status,
                GoalStatusInput(goal_id=goal.goal_id, status=GoalStatus.CANCELLED),
                start_to_close_timeout=TIMEOUT,
                retry_policy=RETRY,
            )
            raise


@workflow.defn(name="GoalRunWorkflow")
class GoalRunWorkflow(PydanticAIWorkflow):
    __pydantic_ai_agents__ = (GOAL_CHECKER,)

    def __init__(self) -> None:
        self._gate = ApprovalGate()

    @workflow.update
    async def decide_approval(self, decision: ApprovalDecisionInput) -> bool:
        applied = await workflow.execute_activity_method(
            ApprovalActivities.record_decision,
            decision,
            start_to_close_timeout=TIMEOUT,
            retry_policy=RETRY,
        )
        if applied:
            self._gate.record(decision.approval_id, decision.approved)
        return applied

    @decide_approval.validator
    def _validate_decision(self, decision: ApprovalDecisionInput) -> None:
        self._gate.check(decision.approval_id)

    @workflow.run
    async def run(self, request: GoalRunInput) -> bool:
        goal = await workflow.execute_activity_method(
            GoalActivities.load,
            request.goal_id,
            start_to_close_timeout=TIMEOUT,
            retry_policy=RETRY,
        )
        if goal is None or not goal.active:
            return False
        # Patched: histories recorded before this activity existed replay without it.
        if workflow.patched("goal-run-progress"):
            await workflow.execute_activity_method(
                GoalActivities.mark_running,
                goal.goal_id,
                start_to_close_timeout=TIMEOUT,
                retry_policy=RETRY,
            )
        try:
            return await self._check(goal)
        finally:
            # A goal run owns its browser session and sandbox (keyed by goal id), like a topic.
            await workflow.execute_activity_method(
                BrowserActivities.close,
                BrowserCloseInput(session_id=goal.goal_id),
                start_to_close_timeout=TIMEOUT,
                retry_policy=RETRY,
            )
            await workflow.execute_activity_method(
                SandboxActivities.release,
                ReleaseSandboxInput(sandbox_id=goal.goal_id),
                start_to_close_timeout=TIMEOUT,
                retry_policy=RETRY,
            )

    async def _check(self, goal: GoalSpec) -> bool:
        profile = await workflow.execute_activity_method(
            ConversationActivities.profile_context,
            ProfileContextInput(user_id=goal.user_id),
            start_to_close_timeout=TIMEOUT,
            retry_policy=RETRY,
        )
        history: list[ModelMessage] = (
            [ModelRequest(parts=[SystemPromptPart(content=profile)])] if profile else []
        )
        deps = AgentDeps(
            user_id=goal.user_id,
            conversation_id=goal.conversation_id,
            turn_id=workflow.uuid4(),
            topic_id=goal.goal_id,
            actor_id=f"goal:{goal.goal_id}",
            trigger="event",
            workflow_id=workflow.info().workflow_id,
            approval_ttl_s=APPROVAL_TIMEOUT_S,
        )

        async def no_announcement(approval_ids: list[uuid.UUID]) -> None:
            return None

        try:
            result = await run_with_approvals(
                GOAL_CHECKER,
                goal_prompt(goal.objective, goal.condition),
                history,
                deps,
                UsageLimits(request_limit=REQUEST_LIMIT),
                self._gate,
                no_announcement,
                timedelta(seconds=APPROVAL_TIMEOUT_S),
            )
        except (AgentRunError, ActivityError) as exc:
            await workflow.execute_activity_method(
                GoalActivities.record_failure,
                RecordFailureInput(goal_id=goal.goal_id, error=type(exc).__name__),
                start_to_close_timeout=TIMEOUT,
                retry_policy=RETRY,
            )
            return False
        observation = result.output
        return await workflow.execute_activity_method(
            GoalActivities.record,
            RecordObservationInput(
                goal_id=goal.goal_id,
                value=observation.value,
                condition_met=observation.condition_met,
                summary=observation.summary,
            ),
            start_to_close_timeout=TIMEOUT,
            retry_policy=RETRY,
        )


def goal_prompt(objective: str, condition: str | None) -> str:
    text = f"Check: {objective}"
    return f"{text}\nCondition: {condition}" if condition else text
