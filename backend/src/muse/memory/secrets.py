"""Heuristic secret detection for anything headed into memory. Not complete; a backstop only."""

import re

_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),  # OpenAI/Anthropic-style keys
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key id
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),  # GitHub tokens
    re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}"),  # Slack tokens
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),  # JWT
    re.compile(r"(?i)\b(password|passwd|secret|api[_ -]?key|token)\b\s*[:=]\s*\S+"),
    re.compile(r"\b[A-Za-z0-9+/_-]{40,}\b"),  # long opaque token
]


def looks_like_secret(text: str) -> bool:
    return any(p.search(text) for p in _PATTERNS)
