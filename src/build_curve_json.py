#!/usr/bin/env python3
"""
scripts/build_curve_json.py
===========================
Convert the ETC computation output (CSV or JSON) into a lightweight JSON
file that the JSXGraph viewer (docs/curves.html) can fetch and render.

Usage:
    python scripts/build_curve_json.py
    python scripts/build_curve_json.py --input data/03_compiled/etc_centers_final.csv
                                       --output docs/data/curves.json
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path


# ── SymPy → JavaScript expression converter ───────────────────────────────────

def sympy_to_js(expr: str) -> str:
    """
    Convert a SymPy expression string to an evaluable JavaScript expression.
    The variable 't' is the Weierstrass parameter; no other free symbols allowed.
    """
    if not expr or expr.strip() in ("None", "nan", "oo", "zoo", ""):
        return "NaN"
    s = str(expr).strip()
    # Reject complex / infinite results
    if re.search(r"\bI\b|\bzoo\b|\boo\b", s):
        return "NaN"
    # Function names
    s = re.sub(r"\bsqrt\(", "Math.sqrt(", s)
    s = re.sub(r"\bcbrt\(", "Math.cbrt(", s)
    s = re.sub(r"\babs\(", "Math.abs(", s)
    s = re.sub(r"\bsin\(", "Math.sin(", s)
    s = re.sub(r"\bcos\(", "Math.cos(", s)
    s = re.sub(r"\btan\(", "Math.tan(", s)
    s = re.sub(r"\bexp\(", "Math.exp(", s)
    s = re.sub(r"\blog\(", "Math.log(", s)
    s = re.sub(r"\batan\(", "Math.atan(", s)
    s = re.sub(r"\bpi\b", "Math.PI", s)
    # ** is valid ES2016+ (exponentiation operator)
    return s


def t_range(n: int, steps: int = 200) -> list[float]:
    """
    Return a list of t values for the Weierstrass parameter t = tan(θ/(2n))
    as θ sweeps (0, π).  Excludes the degenerate endpoints.
    """
    eps = 1e-4
    t_max = math.tan(math.pi / (2 * n)) - eps
    return [eps + (t_max - eps) * i / (steps - 1) for i in range(steps)]


def evaluate_curve(x_js: str, y_js: str, n: int,
                   steps: int = 200) -> list[tuple[float, float]]:
    """
    Numerically evaluate the parametric curve at `steps` t-values.
    Returns a list of (x, y) pairs (skipping NaN/infinite points).
    """
    pts: list[tuple[float, float]] = []
    # Build a local evaluator using Python (mirrors what JS will do)
    import math as _m
    ns = {
        "t": 0.0, "sqrt": _m.sqrt, "cbrt": lambda v: _m.copysign(_m.pow(abs(v), 1/3), v),
        "abs": abs, "sin": _m.sin, "cos": _m.cos, "tan": _m.tan,
        "exp": _m.exp, "log": _m.log, "atan": _m.atan, "pi": _m.pi,
        "Math": type("M", (), {
            "sqrt": _m.sqrt, "abs": abs, "sin": _m.sin, "cos": _m.cos,
            "tan": _m.tan, "exp": _m.exp, "log": _m.log, "atan": _m.atan,
            "PI": _m.pi, "cbrt": lambda v: _m.copysign(_m.pow(abs(v), 1/3), v),
        })(),
    }
    # Convert JS back to Python-evaluable (Math. prefix)
    x_py = x_js.replace("Math.sqrt", "sqrt").replace("Math.abs", "abs") \
                .replace("Math.sin", "sin").replace("Math.cos", "cos") \
                .replace("Math.tan", "tan").replace("Math.exp", "exp") \
                .replace("Math.log", "log").replace("Math.atan", "atan") \
                .replace("Math.PI", "pi").replace("Math.cbrt", "cbrt")
    y_py = y_js.replace("Math.sqrt", "sqrt").replace("Math.abs", "abs") \
                .replace("Math.sin", "sin").replace("Math.cos", "cos") \
                .replace("Math.tan", "tan").replace("Math.exp", "exp") \
                .replace("Math.log", "log").replace("Math.atan", "atan") \
                .replace("Math.PI", "pi").replace("Math.cbrt", "cbrt")

    for t_val in t_range(n, steps):
        ns["t"] = t_val
        try:
            xv = float(eval(x_py, {"__builtins__": {}}, ns))
            yv = float(eval(y_py, {"__builtins__": {}}, ns))
            if (math.isfinite(xv) and math.isfinite(yv)
                    and abs(xv) <= 10 and abs(yv) <= 10):
                pts.append((round(xv, 6), round(yv, 6)))
        except Exception:
            pass
    return pts


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",  default="data/03_compiled/etc_centers_final.csv")
    parser.add_argument("--output", default="docs/data/curves.json")
    parser.add_argument("--steps",  type=int, default=200,
                        help="Number of t-sample points per curve")
    parser.add_argument("--limit",  type=int, default=0,
                        help="Only process first N centers (0 = all)")
    args = parser.parse_args()

    in_path  = Path(args.input)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Read input (CSV or JSON)
    rows: list[dict] = []
    if in_path.suffix == ".csv":
        with in_path.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    else:
        data = json.loads(in_path.read_text(encoding="utf-8"))
        rows = data.get("centers", data.get("rows", []))

    if args.limit:
        rows = rows[:args.limit]

    curves: list[dict] = []
    ok = skipped = 0

    for row in rows:
        cid    = row.get("center_id", row.get("center", "?"))
        name   = row.get("name", "")
        x_raw  = row.get("x_t", row.get("x(t)", ""))
        y_raw  = row.get("y_t", row.get("y(t)", ""))
        status = row.get("eval_status", row.get("status", ""))
        n_raw  = row.get("weierstrass_n", row.get("n", "1"))
        expr   = row.get("expression", row.get("barycentric", ""))

        if status != "ok" or not x_raw or x_raw in ("None", ""):
            skipped += 1
            continue

        try:
            n = int(float(n_raw)) if n_raw and n_raw not in ("None", "") else 1
        except ValueError:
            n = 1

        x_js = sympy_to_js(x_raw)
        y_js = sympy_to_js(y_raw)

        # Pre-compute the point cloud for fast rendering
        pts = evaluate_curve(x_js, y_js, n, steps=args.steps)
        if not pts:
            skipped += 1
            continue

        curves.append({
            "id":     cid,
            "name":   name,
            "bary":   expr,
            "n":      n,
            "x_js":   x_js,   # kept for dynamic JS re-evaluation if needed
            "y_js":   y_js,
            "pts":    pts,     # pre-computed [(x,y), ...] — fast load in browser
        })
        ok += 1

    out_path.write_text(
        json.dumps({"meta": {"total": ok, "steps": args.steps}, "curves": curves},
                   separators=(",", ":")),   # compact — no whitespace
        encoding="utf-8",
    )
    print(f"Done: {ok} curves written to {out_path}  ({skipped} skipped)")
    print(f"File size: {out_path.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
