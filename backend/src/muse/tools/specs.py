"""The registered tool set. The only module that imports executors."""

from typing import Any

from pydantic import BaseModel

from muse.browser.controller import BrowserFacts
from muse.browser.netguard import domain_of
from muse.policy.classification import (
    Classification,
    DataClassification,
    RiskClass,
    SideEffectClass,
)
from muse.tools.executors import browser, clock, goals, outbox, profile, sandbox, topics
from muse.tools.registry import ToolRegistry
from muse.tools.schema import (
    Classifier,
    ExecContext,
    Executor,
    RetryPolicy,
    ToolServices,
    ToolSpec,
)


def _read_only(_: Any, __: ExecContext, ___: ToolServices) -> Classification:
    return Classification(
        risk=RiskClass.READ_ONLY,
        side_effect=SideEffectClass.NONE,
        data_classification=DataClassification.PUBLIC,
    )


def _local_mutation(_: Any, __: ExecContext, ___: ToolServices) -> Classification:
    return Classification(
        risk=RiskClass.LOCAL_MUTATION,
        side_effect=SideEffectClass.NONE,
        data_classification=DataClassification.PERSONAL,
    )


def _sandbox_write(_: Any, __: ExecContext, ___: ToolServices) -> Classification:
    return Classification(
        risk=RiskClass.LOCAL_MUTATION,
        side_effect=SideEffectClass.LOCAL_FILE_WRITE,
        data_classification=DataClassification.PERSONAL,
    )


def _sandbox_read(_: Any, __: ExecContext, ___: ToolServices) -> Classification:
    return Classification(
        risk=RiskClass.READ_ONLY,
        side_effect=SideEffectClass.NONE,
        data_classification=DataClassification.PERSONAL,
    )


def _message_send(args: Any, _: ExecContext, ___: ToolServices) -> Classification:
    return Classification(
        risk=RiskClass.EXTERNAL_WRITE,
        side_effect=SideEffectClass.MESSAGE_SEND,
        data_classification=DataClassification.PERSONAL,
        destination=str(args.recipient),
    )


BROWSER_MUTATIONS = {"browser.click", "browser.fill", "browser.press", "browser.download"}


def _browser_classifier(tool: str) -> Classifier:
    """Facts come from the controller's own state (context, page domain, element name), not the
    model. `destination` is the target of a navigation, otherwise the current page's domain."""
    mutation = tool in BROWSER_MUTATIONS

    def classify(args: Any, ctx: ExecContext, services: ToolServices) -> Classification:
        key = ctx.topic_id or ctx.conversation_id
        element_id = getattr(args, "element_id", None)
        facts = services.browser.facts(key, element_id) if services.browser else BrowserFacts()
        url = getattr(args, "url", None)
        context = getattr(args, "context", None) or facts.context
        return Classification(
            risk=RiskClass.LOCAL_MUTATION if mutation else RiskClass.READ_ONLY,
            side_effect=SideEffectClass.NETWORK_WRITE if mutation else SideEffectClass.NETWORK_READ,
            data_classification=(
                DataClassification.AUTHENTICATED
                if context == "authenticated"
                else DataClassification.PUBLIC
            ),
            destination=domain_of(url) if url else facts.domain,
            browser_context=context,
            element_name=facts.element_name,
        )

    return classify


def _browser_spec(
    name: str,
    description: str,
    args_model: type[BaseModel],
    executor: Executor,
    *,
    idempotent: bool = False,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        args_model=args_model,
        classify=_browser_classifier(name),
        executor=executor,
        idempotent=idempotent,
        retry=RetryPolicy(max_attempts=3 if idempotent else 1),
    )


def _browser_specs() -> list[ToolSpec]:
    return [
        _browser_spec(
            "browser.open_session",
            "Open your browser session (research context: no cookies). "
            "Optional; navigate opens one.",
            browser.OpenArgs,
            browser.open_session,
        ),
        _browser_spec(
            "browser.navigate",
            "Open a public http(s) URL in your browser.",
            browser.NavigateArgs,
            browser.navigate,
            idempotent=True,
        ),
        _browser_spec(
            "browser.snapshot",
            "Read the current page: title, text excerpt, and interactive elements with ids. "
            "Element ids are only valid until the next snapshot or navigation.",
            browser.NoArgs,
            browser.snapshot,
            idempotent=True,
        ),
        _browser_spec(
            "browser.screenshot",
            "Save a screenshot of the page as an artifact.",
            browser.NoArgs,
            browser.screenshot,
            idempotent=True,
        ),
        _browser_spec(
            "browser.click", "Click an element by id.", browser.ElementArgs, browser.click
        ),
        _browser_spec(
            "browser.fill", "Type text into an input by id.", browser.FillArgs, browser.fill
        ),
        _browser_spec(
            "browser.press", "Press a key on an element by id.", browser.PressArgs, browser.press
        ),
        _browser_spec(
            "browser.scroll",
            "Scroll the page up or down.",
            browser.ScrollArgs,
            browser.scroll,
            idempotent=True,
        ),
        _browser_spec(
            "browser.download",
            "Download a file by clicking an element; saved as an artifact.",
            browser.ElementArgs,
            browser.download,
        ),
        _browser_spec(
            "browser.close_session",
            "Close your browser session.",
            browser.NoArgs,
            browser.close_session,
        ),
    ]


def build_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            ToolSpec(
                name="clock.now",
                description="Current date and time in a timezone.",
                args_model=clock.ClockNowArgs,
                classify=_read_only,
                executor=clock.now,
                retry=RetryPolicy(max_attempts=3),
                idempotent=True,
            ),
            ToolSpec(
                name="topic.start",
                description=(
                    "Start a background topic that works on one objective independently and "
                    "reports back when done. Use for longer, separable work. At most 3 at once."
                ),
                args_model=topics.TopicStartArgs,
                classify=_local_mutation,
                executor=topics.start,
            ),
            ToolSpec(
                name="goal.create",
                description=(
                    "Schedule a check for later: once (after_minutes or at) or recurring "
                    "(every_minutes). With a condition, the user is notified when it becomes "
                    "true; without one, when the result changes. E.g. 'check again tomorrow' = "
                    "after_minutes 1440."
                ),
                args_model=goals.GoalCreateArgs,
                classify=_local_mutation,
                executor=goals.create,
            ),
            ToolSpec(
                name="profile.remember",
                description=(
                    "Save a long-lived fact about the user (preferences, constraints, devices, "
                    "standing choices) to profile memory. Never store secrets or passwords."
                ),
                args_model=profile.RememberArgs,
                classify=_local_mutation,
                executor=profile.remember,
                idempotent=True,
            ),
            ToolSpec(
                name="outbox.send",
                description=(
                    "Send a message to someone by email address. Requires the user's approval "
                    "before it is sent."
                ),
                args_model=outbox.SendArgs,
                classify=_message_send,
                executor=outbox.send,
                idempotent=True,
            ),
            ToolSpec(
                name="sandbox.exec",
                description=(
                    "Run a shell command in your private sandbox (Linux, no network, "
                    f"preinstalled: {sandbox.PREINSTALLED}). Files persist in /workspace."
                ),
                args_model=sandbox.ExecArgs,
                classify=_sandbox_write,
                executor=sandbox.exec_cmd,
                timeout_s=sandbox.MAX_EXEC_SECONDS + 30,
            ),
            ToolSpec(
                name="sandbox.write_file",
                description="Write a text file in the sandbox /workspace.",
                args_model=sandbox.WriteFileArgs,
                classify=_sandbox_write,
                executor=sandbox.write_file,
                idempotent=True,
            ),
            ToolSpec(
                name="sandbox.read_file",
                description="Read a text file from the sandbox /workspace.",
                args_model=sandbox.PathArgs,
                classify=_sandbox_read,
                executor=sandbox.read_file,
                idempotent=True,
                retry=RetryPolicy(max_attempts=3),
            ),
            ToolSpec(
                name="sandbox.list",
                description="List a directory in the sandbox /workspace.",
                args_model=sandbox.PathArgs,
                classify=_sandbox_read,
                executor=sandbox.list_dir,
                idempotent=True,
                retry=RetryPolicy(max_attempts=3),
            ),
            ToolSpec(
                name="sandbox.stage",
                description="Copy an artifact you obtained earlier into /workspace/incoming/.",
                args_model=sandbox.StageArgs,
                classify=_sandbox_write,
                executor=sandbox.stage,
            ),
            ToolSpec(
                name="sandbox.stage_package",
                description="Install a package into the sandbox (not available in this version).",
                args_model=sandbox.StagePackageArgs,
                classify=_sandbox_write,
                executor=sandbox.stage_package,
            ),
            *_browser_specs(),
        ]
    )
