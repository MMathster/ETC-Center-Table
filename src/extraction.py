from __future__ import annotations

import hashlib
from typing import Iterable


def normalize_bary(expr: str) -> str:
    """Normalize whitespace for stable hashing/deduplication."""
    return " ".join(expr.split())


def bary_hash(expr: str) -> str:
    norm = normalize_bary(expr)
    digest = hashlib.sha256(norm.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def dedupe_expressions(expressions: Iterable[str]) -> dict[str, str]:
    """Return hash -> normalized expression map."""
    out: dict[str, str] = {}
    for expr in expressions:
        h = bary_hash(expr)
        out.setdefault(h, normalize_bary(expr))
    return out
