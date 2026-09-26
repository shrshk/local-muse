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

Phase 1 ships `/health` only.

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
