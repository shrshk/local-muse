"""Workspace-relative path handling. Everything a caller names must resolve inside /workspace."""

import posixpath

from sandboxd.constraints import WORKSPACE


class UnsafePath(ValueError):
    pass


def resolve(relative: str) -> str:
    if "\x00" in relative:
        raise UnsafePath("null byte in path")
    joined = posixpath.normpath(posixpath.join(WORKSPACE, relative.lstrip("/")))
    if joined != WORKSPACE and not joined.startswith(WORKSPACE + "/"):
        raise UnsafePath(f"path escapes the workspace: {relative!r}")
    return joined
