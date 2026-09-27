# Policy design

## ToolIntent vs ActionProposal

The model emits a `ToolIntent`. It is untrusted and carries only a tool name and args:

```python
class ToolIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str
    args: dict[str, Any]
```

`extra="forbid"` means a model that adds `risk` or `permissions` gets a validation error.

The trusted registry turns it into an `ActionProposal`, which is immutable and persisted:

```text
action_id, approval_key, actor_id, user_id, conversation_id, topic_id,
tool, args (validated, canonical), risk, side_effect, required_permissions,
data_classification, destination, credential_ref, created_at
```

## Classification is registry-owned

Each `ToolSpec` declares, in code, `args_model`, `classify(args, ctx) -> Classification`,
`executor`, `retry`, `idempotent`. The model never sets risk, side_effect, required_permissions
or data_classification. `classify` may use validated args and trusted context (browser context
type, target domain, element role/name), never model text.

Registry steps:

1. Unknown tool → DENY, audit.
2. Args fail `args_model` → tool error back to the model; nothing executes.
3. `classify(validated_args, ctx)`.
4. Build `ActionProposal` with `approval_key`.

Executors are private to the registry module. `ToolGateway.invoke(intent)` is the only public
path: registry → policy → executor → audit.

## Implementation (Phase 2)

- `tools/schema.py`: `ToolIntent` (`extra="forbid"`), `ToolSpec`, `ActionProposal` (frozen).
- `tools/registry.py`: lookup and `propose()`; computes `approval_key`.
- `tools/specs.py`: the only module that imports `tools/executors/`.
- `tools/gateway.py`: `ToolGateway.invoke()` — the only reader of `ToolSpec.executor`.
  Unknown tool → audit `tool.unknown`, no proposal. Bad args → audit `tool.invalid_args`, raise
  `InvalidToolArgs` → the agent sees a retry prompt (one repair attempt). Otherwise record
  `action.proposed` + `action.decided`, execute on ALLOW, record `action.executed|failed`.
- `agents/toolset.py`: a PydanticAI `FunctionToolset` generated from the registry. Each tool holds
  only name, description, JSON schema, and forwards `ToolIntent` to the gateway. PydanticAI's
  own arg validation is skipped so the registry is the single validator. It is a
  `FunctionToolset` so `TemporalAgent` can wrap each call in an activity (Phase 3).
- Model-facing names replace `.` with `_` (`clock.now` → `clock_now`); the registry name is the
  identity everywhere else.
- Boundary tests (`tests/boundary/test_tool_boundary.py`) enforce the import and attribute
  rules by AST, and that `ToolIntent` rejects classification fields.

### Tools registered so far

| Tool | Classification | Phase 6 note |
|---|---|---|
| `clock.now` | READ_ONLY / NONE / PUBLIC, idempotent | ALLOW |
| `topic.start` | LOCAL_MUTATION / NONE / PERSONAL | needs an explicit ALLOW rule, or the default sends it to REQUIRE_APPROVAL |

## Enums

```text
RiskClass           READ_ONLY LOCAL_MUTATION EXTERNAL_WRITE SENSITIVE_EXTERNAL_WRITE DESTRUCTIVE
SideEffectClass     NONE LOCAL_FILE_WRITE NETWORK_READ NETWORK_WRITE MESSAGE_SEND REMOTE_UPDATE
                    PURCHASE DELETE
DataClassification  PUBLIC PERSONAL AUTHENTICATED SECRET
```

## Rule table (first match wins)

| # | Condition | Decision |
|---|---|---|
| 1 | tool not registered | DENY |
| 2 | data_classification == SECRET | DENY |
| 3 | host/system action (not a registered tool) | DENY |
| 4 | `sandbox.*` (exec, read, write, list) | ALLOW |
| 5 | `browser.navigate/snapshot/screenshot/scroll`, research | ALLOW |
| 6 | `browser.click/fill/press`, research, domain allowlisted, no escalation match | ALLOW |
| 7 | `browser.click/fill/press`, research, domain not allowlisted | REQUIRE_APPROVAL |
| 8 | `browser.open_session(authenticated)` | REQUIRE_APPROVAL |
| 9 | `browser.*` mutation (click/fill/press/download), authenticated | REQUIRE_APPROVAL |
| 10 | `browser.navigate/snapshot`, authenticated | ALLOW, output tagged AUTHENTICATED |
| 11 | `http.get` (public) | ALLOW |
| 12 | `web.search` | ALLOW |
| 13 | `notify.user` (Telegram to owner) | ALLOW |
| 14 | side_effect ∈ {MESSAGE_SEND, REMOTE_UPDATE, PURCHASE, DELETE} | REQUIRE_APPROVAL |
| 15 | risk ∈ {EXTERNAL_WRITE, SENSITIVE_EXTERNAL_WRITE, DESTRUCTIVE} | REQUIRE_APPROVAL |
| 16 | default | REQUIRE_APPROVAL |

Phase 2 ships the engine returning ALLOW for everything (`policy/engine.py`); Phase 6 installs
this table. The tool
stack does not change between the two.

## Browser context rules

The same tool (`browser.click`) can expand a panel or confirm a purchase. Policy keys on:

- browser context: research vs authenticated;
- target domain vs `domain_allowlist` (starts empty);
- element accessible role and name.

Escalation heuristic: accessible name matching
`/buy|purchase|confirm|send|submit|pay|delete/i` → REQUIRE_APPROVAL regardless of allowlist.
This is a pattern list, not a guarantee; it is documented as incomplete.

AUTHENTICATED output is treated as PERSONAL for any onward action: writing it to a sandbox or
sending it anywhere external requires approval.

## approval_key

```python
approval_key = sha256(canonical_json({
    "tool": proposal.tool,
    "args": proposal.args,            # validated, sorted keys, no whitespace
    "destination": proposal.destination,
    "credential_ref": proposal.credential_ref,
    "user_id": str(proposal.user_id),
})).hexdigest()
```

**Excluded:** page snapshots, timestamps, model reasoning, `action_id`, any non-deterministic
context. Those go into `summary_for_human`, not identity.

- One approval grants exactly one `approval_key`. Different args → new approval.
- Retry of the same action reuses `action_id` and `approval_key` and does not re-prompt.
- A decision on a non-PENDING approval is a no-op. Expiry (7 days) → DENIED(expired).
