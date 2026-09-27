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
| `profile.remember` | LOCAL_MUTATION / NONE / PERSONAL, idempotent | same as `topic.start` |
| `sandbox.exec`, `sandbox.write_file`, `sandbox.stage`, `sandbox.stage_package` | LOCAL_MUTATION / LOCAL_FILE_WRITE / PERSONAL | rule 4 (`sandbox.*` ALLOW); staging AUTHENTICATED data needs approval (Phase 8) |
| `sandbox.read_file`, `sandbox.list` | READ_ONLY / NONE / PERSONAL | rule 4 |
| `browser.navigate`, `snapshot`, `screenshot`, `scroll`, `open_session`, `close_session` | READ_ONLY / NETWORK_READ / PUBLIC (AUTHENTICATED in an authenticated context) | browser rule: ALLOW (opening an authenticated session → approval) |
| `browser.click`, `fill`, `press`, `download` | LOCAL_MUTATION / NETWORK_WRITE, destination = page domain, element_name from the snapshot | browser rule: allowlisted research domain → ALLOW; escalation or not allowlisted → approval; authenticated → approval |

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

Phase 6 installed this table in `policy/engine.py` as ordered `Rule`s. The tool
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

## Implementation (Phase 6)

- Rules (first match wins): `secret` → DENY; `sandbox` → ALLOW; `browser` (open authenticated →
  approval; reads ALLOW; mutations: authenticated → approval, escalation heuristic → approval,
  allowlisted research domain → ALLOW, else approval); `named_allows` (`http.get`, `web.search`,
  `notify.user`, and the local assistant tools `clock.now`, `profile.remember`, `topic.start`);
  `approval_classes` (MESSAGE_SEND/REMOTE_UPDATE/PURCHASE/DELETE side effects, EXTERNAL_WRITE/
  SENSITIVE/DESTRUCTIVE risks); `read_only` (READ_ONLY with NONE/NETWORK_READ) → ALLOW; default →
  REQUIRE_APPROVAL. Unknown tools are denied by the gateway before a proposal exists (rule 1).
  There are no host/system tools to deny (rule 3).
- Browser rows key on trusted classification fields `browser_context`, `destination` (domain)
  and `element_name`, filled by browser tool classifiers in Phase 7. Escalation applies in both
  contexts (stricter than the spec's minimum). The allowlist (`domain_allowlist`, per user and
  context, matches parent domains) is read by the engine; its UI arrives with Phase 7.
- `Decision` carries the matching rule name; it is logged with every tool call.

### Approval flow

1. Gateway: REQUIRE_APPROVAL → records the action (`pending_approval`) and an `approvals` row
   (PENDING, `approval_key`, human summary, `expires_at`, `workflow_id`), audits
   `approval.requested`, and the tool raises PydanticAI `ApprovalRequired(approval_id)`.
2. The run ends with `DeferredToolRequests`; the workflow (`workflows/approvals.py`) opens the
   gate, publishes `approval.required`, and waits durably (timer = approval TTL, default 7 days).
3. `POST /api/approvals/{id}/decision {decision, approval_key}`: 404 unless the caller owns it;
   a non-PENDING approval returns `changed: false` (no-op); a different key → 409; expired → 409.
   Otherwise the API sends the `decide_approval` Update.
4. The Update validator rejects approvals the workflow is not waiting on or has decided; the
   handler records the decision with a conditional update (still PENDING, same key, unexpired),
   so at most one of two racing decisions applies. The action row becomes approved/denied.
5. When all are decided (or the timer fires and `approval.expire` marks them EXPIRED), the agent
   re-runs with `DeferredToolResults` (True, or ToolDenied with a reason).
6. The approved tool call reaches the gateway again: an APPROVED, unused approval for the same
   key in the same workflow is consumed and the executor runs under the original `action_id`.
   A retry after a crash mid-execution re-runs only idempotent executors (same `action_id`).
   Different arguments → different key → a new approval.

Stub external tool for tests and demos: `outbox.send` (EXTERNAL_WRITE / MESSAGE_SEND, destination
= recipient) writes to `outbox`, idempotent on `action_id`.
