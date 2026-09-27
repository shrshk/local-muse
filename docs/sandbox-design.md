# Sandbox design

## Invariants

- **Only sandboxd holds the Docker socket.** Not backend, not worker, not web.
- A sandbox has **no network, no credentials, no Docker socket, no host mounts**.
- **Only `/workspace` is writable** (plus a size-limited tmpfs at `/tmp`).
- **Constraints are enforced by sandboxd on create and cannot be overridden by callers.** The API
  has no options passthrough.

## sandboxd

A small FastAPI service in its own image and container.

- Networks: `sandbox-control` only (`internal: true`). Only `worker` is also attached.
- Every request needs `Authorization: Bearer $SANDBOXD_TOKEN`, so a network mistake does not
  silently open it.
- Its own container: `cap_drop: ALL`, `no-new-privileges`, read-only rootfs, 256 MB.
- Runs as root inside its container, only to open the socket (see threat-model residual risks).

## API

```text
GET    /health                                                   → {docker: ok|error}
POST   /sandboxes                    {topic_id}                  → {sandbox_id}
POST   /sandboxes/{id}/exec          {cmd, timeout_s, cwd}       → {stdout, stderr, exit_code, truncated}
PUT    /sandboxes/{id}/files/{path}  body                        → ok
GET    /sandboxes/{id}/files/{path}                              → body
GET    /sandboxes/{id}/files?path=                               → listing
POST   /sandboxes/{id}/stage         {artifact_id}               → ok
DELETE /sandboxes/{id}                                           container destroyed, volume kept
DELETE /sandboxes/{id}/volume                                    explicit, approval-gated upstream
```

Implemented in Phase 5 (below).

## Container constraints (fixed in sandboxd)

```text
image          local-muse-sandbox:<pinned>
user           sandbox (uid 10001)
cap_drop       ALL
security_opt   no-new-privileges:true
read_only      true
tmpfs          /tmp (size-limited)
volumes        ws-<topic_id> → /workspace (rw); nothing else
network_mode   none
pids_limit     256
cpus           2
mem_limit      4g
env            none beyond a fixed PATH/HOME
```

Never mounted: `/var/run/docker.sock`, `~`, `~/.ssh`, `~/.aws`, `~/Documents`, any host path.

## Lifecycle

```text
container         ephemeral
workspace volume  durable, one per topic (ws-<topic_id>)
topic memory      Postgres
workflow state    Temporal
```

Topic start → create container, attach volume → run → pause → destroy container, keep volume
→ resume → fresh container, same volume.

## Dependencies without network

- Fat image: Python 3.12, numpy, pandas, polars, matplotlib, requests (inert), beautifulsoup4,
  lxml, pyarrow, openpyxl, jq, ripgrep, git, curl (inert), Node LTS. Listed in
  `sandbox/Dockerfile`.
- Trusted stager: `sandbox.stage(artifact_id)` copies an artifact obtained by a trusted tool into
  `/workspace/incoming/`. `sandbox.stage_package` is registered and returns "not available".
- No outbound network for convenience, ever.

## Implementation (Phase 5)

- `sandboxd/src/sandboxd/constraints.py` is the single place the container spec lives
  (`create_kwargs`). Plus: `init` (tini), `/tmp` tmpfs is `noexec,nosuid,size=256m`, env is only
  `HOME=/workspace`, label `local-muse.sandbox=1`.
- Ids: the sandbox id is the topic id (or the conversation id for the coordinator). Container
  `lm-sbx-<id>`, volume `lm-ws-<id>`. `POST /sandboxes` is get-or-create; a stopped container is
  replaced.
- Capacity: at most 2 running containers. At capacity the least recently used idle container is
  evicted (volume kept, so nothing is lost); 409 only when every running sandbox is busy. Use
  tracking is in memory; after a sandboxd restart untracked sandboxes count as oldest.
- Exec runs `timeout -s KILL <t> sh -c <cmd>` as uid 10001; stdout/stderr truncated at 64 KB each.
- Files: paths are resolved inside `/workspace` (`paths.resolve`), 10 MB cap; writes are tar
  uploads owned by 10001; listing via `find -maxdepth 1`.
- Stage: `POST /sandboxes/{id}/stage {filename, content_b64}` writes `incoming/<safe-name>`. Only
  the worker's `sandbox.stage` executor calls it, with bytes from the artifact store (worker-only
  volume `artifacts`). AUTHENTICATED/SECRET artifacts are refused until Phase 8 adds approvals.
- Request bodies are `extra="forbid"`: a create with `privileged`, `network_mode`, `volumes`,
  `image` or `user` is a 422.
- Tools (all through the gateway): `sandbox.exec` (≤120 s, not retried), `sandbox.write_file`,
  `sandbox.read_file`, `sandbox.list`, `sandbox.stage`, `sandbox.stage_package` (always refuses).
- Lifecycle: TopicWorkflow's `finally` runs `sandbox.release` (container destroyed, volume kept,
  `sandboxes.status=stopped`) on every outcome; a conversation releases its sandbox when it idles
  out. `DELETE /sandboxes/{id}/volume` removes the workspace.
- Image: `sandbox/Dockerfile` → `local-muse-sandbox:1` (0.94 GB), built by `make sandbox-image`
  (Compose profile `images`).

Verified by automated tests (see progress.md): uid 10001, CapEff 0, no docker socket, no host
paths in mounts, DNS/TCP/curl fail, only `lo` up and no routes, no secrets in env, read-only
`/usr` and `/etc`, `/tmp` noexec, `/workspace` persists across recreation, pids.max 256 and fork
bomb stopped, memory.max 4 GiB and OOM kill, exec timeout, override and escape refusals, LRU
eviction at capacity with the evicted workspace intact.
