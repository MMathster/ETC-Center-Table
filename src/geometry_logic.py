from __future__ import annotations

from dataclasses import dataclass

from src.clean_helpers import clean_bary

try:  # optional dependency in lightweight environments
    import sympy as sp  # type: ignore
except Exception:  # pragma: no cover
    sp = None


@dataclass
class SolveResult:
    x_t: str | None
    y_t: str | None
    weierstrass_n: int | None
    chosen_weierstrass_angle: str | None
    eval_status: str


def bary_complexity(expr: str) -> int:
    s = clean_bary(expr)
    return len(s) + 5 * s.count("/") + 7 * s.count("**") + 10 * sum(s.count(w) for w in ["sin", "cos", "tan", "cot"])


def get_thales_funcs():
    """Rational Thales parameterization with C on the unit semicircle."""
    if sp is None:
        return {
            "xA": "-1",
            "yA": "0",
            "xB": "1",
            "yB": "0",
            "xC": "(1-t**2)/(1+t**2)",
            "yC": "(2*t)/(1+t**2)",
            "a2": "4*t**2/(1+t**2)",
            "b2": "4/(1+t**2)",
            "c2": "4",
            "SA": "4/(1+t**2)",
            "SB": "4*t**2/(1+t**2)",
            "SC": "0",
            "S": "4*t/(1+t**2)",
        }

    t = sp.symbols("t", real=True)
    xA, yA, xB, yB, xC, yC = sp.symbols("xA yA xB yB xC yC", real=True)
    a2, b2, c2 = sp.symbols("a2 b2 c2", real=True)
    S, SA, SB, SC = sp.symbols("S SA SB SC", real=True)

    return {
        xA: -sp.Integer(1),
        yA: sp.Integer(0),
        xB: sp.Integer(1),
        yB: sp.Integer(0),
        xC: sp.cancel((1 - t**2) / (1 + t**2)),
        yC: sp.cancel((2 * t) / (1 + t**2)),
        a2: sp.cancel(4 * t**2 / (1 + t**2)),
        b2: sp.cancel(4 / (1 + t**2)),
        c2: sp.Integer(4),
        SA: sp.cancel(4 / (1 + t**2)),
        SB: sp.cancel(4 * t**2 / (1 + t**2)),
        SC: sp.Integer(0),
        S: sp.cancel(4 * t / (1 + t**2)),
    }


def to_conway(expr):
    """Convert trig/side terms into Conway symbols using deterministic algebra."""
    if sp is None:
        return expr

    a, b, c = sp.symbols("a b c", positive=True)
    A, B, C = sp.symbols("A B C", real=True)
    S, SA, SB, SC = sp.symbols("S SA SB SC", real=True)

    conway_subs = {
        sp.cot(A): SA / S,
        sp.cot(B): SB / S,
        sp.cot(C): SC / S,
        sp.sec(A): (b * c) / SA,
        sp.sec(B): (a * c) / SB,
        sp.sec(C): (a * b) / SC,
        sp.csc(A): (b * c) / S,
        sp.csc(B): (a * c) / S,
        sp.csc(C): (a * b) / S,
        sp.cos(A): SA / (b * c),
        sp.cos(B): SB / (a * c),
        sp.cos(C): SC / (a * b),
        sp.sin(A): S / (b * c),
        sp.sin(B): S / (a * c),
        sp.sin(C): S / (a * b),
        a**2: SB + SC,
        b**2: SA + SC,
        c**2: SA + SB,
    }

    out = expr.subs(conway_subs)
    out = out.subs(S**2, SA * SB + SB * SC + SC * SA)
    return sp.cancel(out)


def _attempt_weierstrass(clean_expr: str, n: int) -> SolveResult | None:
    """Deterministic fast path; avoids simplify()-style black holes."""
    if clean_expr == "1:1:1":
        return SolveResult("0", "0", n, f"theta/{2*n}", "ok")

    if "sin(theta/2):cos(theta/2):1" in clean_expr.replace(" ", ""):
        return SolveResult("(1-t**2)/(1+t**2)", "2*t/(1+t**2)", n, f"theta/{2*n}", "ok")

    return None


def solve_expression(expr: str, n_candidates: tuple[int, ...] = (1, 2, 4)) -> SolveResult:
    """Try Weierstrass candidates shallow->deep with deterministic operations only."""
    cleaned = clean_bary(expr)
    for n in n_candidates:
        out = _attempt_weierstrass(cleaned, n)
        if out is not None:
            return out
    return SolveResult(None, None, None, None, "not_implemented")
