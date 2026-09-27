"""The container constraints (spec §10.2). Applied on every create; callers cannot change them."""

from typing import Any

SANDBOX_UID = 10001
WORKSPACE = "/workspace"
LABEL = "local-muse.sandbox"

MAX_EXEC_SECONDS = 300
MAX_OUTPUT_BYTES = 64 * 1024
MAX_FILE_BYTES = 10 * 1024 * 1024


def container_name(key: str) -> str:
    return f"lm-sbx-{key}"


def volume_name(key: str) -> str:
    return f"lm-ws-{key}"


def create_kwargs(image: str, key: str) -> dict[str, Any]:
    return {
        "image": image,
        "name": container_name(key),
        "command": ["sleep", "infinity"],
        "detach": True,
        "init": True,
        "user": f"{SANDBOX_UID}:{SANDBOX_UID}",
        "working_dir": WORKSPACE,
        "environment": {"HOME": WORKSPACE},
        "labels": {LABEL: "1", f"{LABEL}.key": key},
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "read_only": True,
        "tmpfs": {"/tmp": "rw,noexec,nosuid,size=256m,mode=1777"},
        "volumes": {volume_name(key): {"bind": WORKSPACE, "mode": "rw"}},
        "network_mode": "none",
        "pids_limit": 256,
        "nano_cpus": 2_000_000_000,
        "mem_limit": "4g",
        "memswap_limit": "4g",
        "privileged": False,
    }
