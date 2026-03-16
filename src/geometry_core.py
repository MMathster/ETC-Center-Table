from __future__ import annotations


def placeholder_geometry_context() -> dict[str, str]:
    """Placeholder for shared symbolic geometry definitions.

    Move notebook geometry constants/substitutions here in incremental refactors.
    """
    return {
        "A": "(1,0)",
        "B": "(-1,0)",
        "C": "(cos(theta), sin(theta))",
    }
