from __future__ import annotations

import re


def clean_bary(expr: str) -> str:
    """Normalize extracted barycentric text into a stable form."""
    if not isinstance(expr, str):
        return ""
    s = expr.strip()
    s = re.sub(r"\s+", " ", s)
    s = s.replace(" :", ":").replace(": ", ":")
    return s
