"""Trusted tool registry: lookup, argument validation, classification, proposal building."""

import datetime as dt
import uuid
from collections.abc import Iterable

from pydantic import BaseModel

from muse.tools.approval_key import compute_approval_key
from muse.tools.schema import ActionProposal, ExecContext, ToolSpec


class ToolRegistry:
    def __init__(self, specs: Iterable[ToolSpec]) -> None:
        self._specs: dict[str, ToolSpec] = {}
        for spec in specs:
            if spec.name in self._specs:
                raise ValueError(f"duplicate tool {spec.name}")
            self._specs[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def specs(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def propose(self, spec: ToolSpec, args: BaseModel, ctx: ExecContext) -> ActionProposal:
        classification = spec.classify(args, ctx)
        canonical_args = args.model_dump(mode="json")
        credential_ref = None
        return ActionProposal(
            action_id=uuid.uuid4(),
            approval_key=compute_approval_key(
                tool=spec.name,
                args=canonical_args,
                destination=classification.destination,
                credential_ref=credential_ref,
                user_id=str(ctx.user_id),
            ),
            actor_id=ctx.actor_id,
            user_id=ctx.user_id,
            conversation_id=ctx.conversation_id,
            topic_id=ctx.topic_id,
            tool=spec.name,
            args=canonical_args,
            risk=classification.risk,
            side_effect=classification.side_effect,
            required_permissions=classification.required_permissions,
            data_classification=classification.data_classification,
            destination=classification.destination,
            credential_ref=credential_ref,
            created_at=dt.datetime.now(dt.UTC),
            browser_context=classification.browser_context,
            element_name=classification.element_name,
        )
