#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.geometry_logic import solve_expression, bary_complexity
from src.parallel_utils import loky_map, multiprocessing_map, strict_timeout


@strict_timeout(seconds=5.0)
def _timed_solve(expr: str):
    result = solve_expression(expr)
    return {
        "x_t": result.x_t,
        "y_t": result.y_t,
        "weierstrass_n": result.weierstrass_n,
        "chosen_weierstrass_angle": result.chosen_weierstrass_angle,
        "eval_status": result.eval_status,
    }


def _worker(payload: tuple[str, float]) -> tuple[str, dict]:
    expr, timeout_seconds = payload
    t0 = time.perf_counter()

    # bind timeout dynamically per invocation
    timed = strict_timeout(seconds=timeout_seconds)(lambda e: _timed_solve.__wrapped__(e))
    out = timed(expr)

    if isinstance(out, dict) and out.get("status") == "timeout":
        return expr, {
            "x_t": None,
            "y_t": None,
            "weierstrass_n": None,
            "chosen_weierstrass_angle": None,
            "eval_status": "timeout",
            "seconds": round(time.perf_counter() - t0, 6),
        }

    if isinstance(out, dict) and out.get("status", "").startswith("error:"):
        return expr, {
            "x_t": None,
            "y_t": None,
            "weierstrass_n": None,
            "chosen_weierstrass_angle": None,
            "eval_status": out["status"],
            "seconds": round(time.perf_counter() - t0, 6),
        }

    out["seconds"] = round(time.perf_counter() - t0, 6)
    return expr, out


def run_canary_test(expressions: list[str], timeout_seconds: float, limit: int = 20) -> None:
    print(f"🚀 Starting Canary Test on first {min(limit, len(expressions))} expressions")
    for i, expr in enumerate(expressions[:limit], 1):
        print(f"[{i}] Attempting ({len(expr)} chars): {expr[:120]}", flush=True)
        _, result = _worker((expr, timeout_seconds))
        print(f"    -> {result.get('eval_status')} in {result.get('seconds')}s", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 2: Solve deduplicated expression registry")
    parser.add_argument("--registry", default="data/math_registry.json")
    parser.add_argument("--cache", default="data/solution_cache.json")
    parser.add_argument("--backend", choices=["loky", "multiprocessing"], default="loky")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--maxtasksperchild", type=int, default=50)
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--canary-limit", type=int, default=0)
    parser.add_argument("--descending-complexity", action="store_true")
    args = parser.parse_args()

    reg = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    expressions = list(reg.get("registry", {}).keys())

    cache_path = Path(args.cache)
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    else:
        cache = {"meta": {"version": 1}, "solved": {}}

    solved = cache.get("solved", {})
    pending = [expr for expr in expressions if expr not in solved]
    pending.sort(key=bary_complexity, reverse=args.descending_complexity)

    print(f"Registry expressions: {len(expressions)}")
    print(f"Cache hits: {len(expressions) - len(pending)}")
    print(f"Pending: {len(pending)}")

    if args.canary_limit > 0:
        run_canary_test(pending, timeout_seconds=args.timeout_seconds, limit=args.canary_limit)

    t0 = time.perf_counter()
    results: list[tuple[str, dict]] = []
    work_items = [(expr, args.timeout_seconds) for expr in pending]

    if work_items:
        if args.backend == "loky":
            results = loky_map(_worker, work_items, batch_size=args.batch_size)
        else:
            results = multiprocessing_map(_worker, work_items, maxtasksperchild=args.maxtasksperchild)

    for expr, payload in results:
        solved[expr] = payload

    elapsed = max(time.perf_counter() - t0, 1e-9)
    rate = len(results) / elapsed

    status_counts: dict[str, int] = {}
    for payload in solved.values():
        st = payload.get("eval_status", "unknown")
        status_counts[st] = status_counts.get(st, 0) + 1

    output = {
        "meta": {
            "version": 2,
            "backend": args.backend,
            "batch_size": args.batch_size,
            "maxtasksperchild": args.maxtasksperchild,
            "timeout_seconds": args.timeout_seconds,
            "descending_complexity": args.descending_complexity,
            "last_run_seconds": round(elapsed, 4),
            "last_run_rate": round(rate, 4),
            "status_counts": status_counts,
        },
        "solved": solved,
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(output, indent=2), encoding="utf-8")

    print(f"Solved this run: {len(results)}")
    print(f"Total solved in cache: {len(solved)}")
    print(f"Run rate (expr/sec): {rate:.3f}")
    print(f"Status counts: {status_counts}")


if __name__ == "__main__":
    main()
