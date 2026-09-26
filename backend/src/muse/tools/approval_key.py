"""approval_key: identity of an action's exact contents. Nothing non-deterministic goes in."""

import hashlib
import json
from typing import Any

from muse.tools.schema import ActionProposal


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_approval_key(
    *,
    tool: str,
    args: dict[str, Any],
    destination: str | None,
    credential_ref: str | None,
    user_id: str,
) -> str:
    payload = {
        "tool": tool,
        "args": args,
        "destination": destination,
        "credential_ref": credential_ref,
        "user_id": user_id,
    }
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def approval_key_for(proposal: ActionProposal) -> str:
    return compute_approval_key(
        tool=proposal.tool,
        args=proposal.args,
        destination=proposal.destination,
        credential_ref=proposal.credential_ref,
        user_id=str(proposal.user_id),
    )
