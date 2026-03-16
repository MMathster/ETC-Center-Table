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

from src.geometry_logic import solve_expression
from src.parallel_utils import loky_map, multiprocessing_map


def _worker(expr: str) -> tuple[str, dict]:
    t0 = time.perf_counter()
    result = solve_expression(expr)
    return expr, {
        "x_t": result.x_t,
        "y_t": result.y_t,
        "weierstrass_n": result.weierstrass_n,
        "chosen_weierstrass_angle": result.chosen_weierstrass_angle,
        "eval_status": result.eval_status,
        "seconds": round(time.perf_counter() - t0, 6),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 2: Solve deduplicated expression registry")
    parser.add_argument("--registry", default="data/math_registry.json")
    parser.add_argument("--cache", default="data/solution_cache.json")
    parser.add_argument("--backend", choices=["loky", "multiprocessing"], default="loky")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--maxtasksperchild", type=int, default=50)
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

    print(f"Registry expressions: {len(expressions)}")
    print(f"Cache hits: {len(expressions) - len(pending)}")
    print(f"Pending: {len(pending)}")

    t0 = time.perf_counter()
    results: list[tuple[str, dict]] = []
    if pending:
        if args.backend == "loky":
            results = loky_map(_worker, pending, batch_size=args.batch_size)
        else:
            results = multiprocessing_map(_worker, pending, maxtasksperchild=args.maxtasksperchild)

    for expr, payload in results:
        solved[expr] = payload

    elapsed = max(time.perf_counter() - t0, 1e-9)
    rate = len(results) / elapsed

    output = {
        "meta": {
            "version": 1,
            "backend": args.backend,
            "batch_size": args.batch_size,
            "maxtasksperchild": args.maxtasksperchild,
            "last_run_seconds": round(elapsed, 4),
            "last_run_rate": round(rate, 4),
        },
        "solved": solved,
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(output, indent=2), encoding="utf-8")

    print(f"Solved this run: {len(results)}")
    print(f"Total solved in cache: {len(solved)}")
    print(f"Run rate (expr/sec): {rate:.3f}")


if __name__ == "__main__":
    main()
