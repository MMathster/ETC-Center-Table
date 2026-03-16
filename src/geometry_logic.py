from __future__ import annotations

from dataclasses import dataclass

from src.clean_helpers import clean_bary


@dataclass
class SolveResult:
    x_t: str | None
    y_t: str | None
    weierstrass_n: int | None
    chosen_weierstrass_angle: str | None
    eval_status: str


def _attempt_weierstrass(clean_expr: str, n: int) -> SolveResult | None:
    """Minimal deterministic solver stub for pipeline wiring.

    Replace this body with migrated Section 11 symbolic logic.
    """
    if clean_expr == "1:1:1":
        return SolveResult("0", "0", n, f"theta/{2*n}", "ok")
    if "sin(theta/2):cos(theta/2):1" in clean_expr.replace(" ", ""):
        return SolveResult("(1-t**2)/(1+t**2)", "2*t/(1+t**2)", n, f"theta/{2*n}", "ok")
    return None


def solve_expression(expr: str, n_candidates: tuple[int, ...] = (1, 2, 4)) -> SolveResult:
    """Try Weierstrass candidates and choose shallowest successful substitution."""
    cleaned = clean_bary(expr)
    for n in n_candidates:
        out = _attempt_weierstrass(cleaned, n)
        if out is not None:
            return out
    return SolveResult(None, None, None, None, "not_implemented")
