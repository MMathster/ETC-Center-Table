#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
import sys
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.geometry_logic import solve_expression, bary_complexity
from src.parallel_utils import loky_map, multiprocessing_map, strict_timeout


def _solve_payload(expr: str) -> dict:
    result = solve_expression(expr)
    return {
        "x_t": result.x_t,
        "y_t": result.y_t,
        "weierstrass_n": result.weierstrass_n,
        "chosen_weierstrass_angle": result.chosen_weierstrass_angle,
        "eval_status": result.eval_status,
    }


def _worker_soft_timeout(payload: tuple[str, float]) -> tuple[str, dict]:
    """Legacy worker path: uses strict_timeout (SIGALRM on POSIX, threads on Windows)."""
    expr, timeout_seconds = payload
    t0 = time.perf_counter()

    timed = strict_timeout(seconds=timeout_seconds)(_solve_payload)
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

    if isinstance(out, dict):
        out["seconds"] = round(time.perf_counter() - t0, 6)
        return expr, out

    return expr, {
        "x_t": None,
        "y_t": None,
        "weierstrass_n": None,
        "chosen_weierstrass_angle": None,
        "eval_status": "error:unexpected_return_type",
        "seconds": round(time.perf_counter() - t0, 6),
    }


def _pebble_entry(expr: str) -> dict:
    """Pure compute function for Pebble (must be picklable)."""
    return _solve_payload(expr)


def _run_pebble(
    expressions: list[str],
    timeout_seconds: float,
    max_workers: int,
    max_tasks: int,
    flush_every: int,
    solved: dict,
    cache_path: Path,
    base_meta: dict,
) -> list[tuple[str, dict]]:
    # Imported lazily so non-pebble usage doesn't require dependency.
    from concurrent.futures import TimeoutError as FutureTimeoutError

    from pebble import ProcessPool  # type: ignore
    from tqdm import tqdm  # type: ignore

    results: list[tuple[str, dict]] = []
    pending = [e for e in expressions if e not in solved]
    if not pending:
        return results

    cache_path.parent.mkdir(parents=True, exist_ok=True)

    # Create tasks one-by-one so results can stream back; a single pathological expr
    # can't block returning earlier successes.
    t_submit0 = time.perf_counter()
    with ProcessPool(max_workers=max_workers, max_tasks=max_tasks) as pool:
        futures = []
        for expr in pending:
            fut = pool.schedule(_pebble_entry, args=(expr,), timeout=timeout_seconds)
            futures.append((expr, fut))

        for i, (expr, fut) in enumerate(tqdm(futures, total=len(futures), desc="Computing expressions"), 1):
            t0 = time.perf_counter()
            try:
                out = fut.result()
                if not isinstance(out, dict):
                    payload = {
                        "x_t": None,
                        "y_t": None,
                        "weierstrass_n": None,
                        "chosen_weierstrass_angle": None,
                        "eval_status": "error:unexpected_return_type",
                    }
                else:
                    payload = out
            except FutureTimeoutError:
                payload = {
                    "x_t": None,
                    "y_t": None,
                    "weierstrass_n": None,
                    "chosen_weierstrass_angle": None,
                    "eval_status": "timeout",
                }
            except Exception as exc:
                payload = {
                    "x_t": None,
                    "y_t": None,
                    "weierstrass_n": None,
                    "chosen_weierstrass_angle": None,
                    "eval_status": f"error:{type(exc).__name__}:{exc}",
                }

            payload["seconds"] = round(time.perf_counter() - t0, 6)
            solved[expr] = payload
            results.append((expr, payload))

            if flush_every > 0 and (i % flush_every == 0):
                meta = dict(base_meta)
                meta.update(
                    {
                        "last_flush_idx": i,
                        "last_flush_seconds_since_submit": round(time.perf_counter() - t_submit0, 4),
                    }
                )
                cache_path.write_text(json.dumps({"meta": meta, "solved": solved}, indent=2), encoding="utf-8")

    return results


def run_canary_test(expressions: list[str], timeout_seconds: float, limit: int = 20) -> None:
    print(f"Starting Canary Test on first {min(limit, len(expressions))} expressions")
    for i, expr in enumerate(expressions[:limit], 1):
        print(f"[{i}] Attempting ({len(expr)} chars): {expr[:120]}", flush=True)
        _, result = _worker_soft_timeout((expr, timeout_seconds))
        print(f"    -> {result.get('eval_status')} in {result.get('seconds')}s", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 2: Solve deduplicated expression registry")
    parser.add_argument("--registry", default="data/math_registry.json")
    parser.add_argument("--cache", default="data/solution_cache.json")
    parser.add_argument("--backend", choices=["loky", "multiprocessing", "pebble"], default="loky")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--maxtasksperchild", type=int, default=50)
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--canary-limit", type=int, default=0)
    parser.add_argument("--descending-complexity", action="store_true")
    parser.add_argument("--max-workers", type=int, default=0, help="Override worker count for pebble backend (0=auto)")
    parser.add_argument("--pebble-max-tasks", type=int, default=50, help="Worker recycle threshold for pebble backend")
    parser.add_argument("--flush-every", type=int, default=200, help="Write cache every N expressions (pebble backend)")
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

    if args.canary_limit > 0 and pending:
        run_canary_test(pending, timeout_seconds=args.timeout_seconds, limit=args.canary_limit)

    t0 = time.perf_counter()
    results: list[tuple[str, dict]] = []
    work_items = [(expr, args.timeout_seconds) for expr in pending]

    if work_items:
        if args.backend == "loky":
            results = loky_map(_worker_soft_timeout, work_items, batch_size=args.batch_size)
            for expr, payload in results:
                solved[expr] = payload
        elif args.backend == "multiprocessing":
            results = multiprocessing_map(_worker_soft_timeout, work_items, maxtasksperchild=args.maxtasksperchild)
            for expr, payload in results:
                solved[expr] = payload
        else:
            try:
                import os

                max_workers = args.max_workers if args.max_workers > 0 else max(1, (os.cpu_count() or 8) - 1)
            except Exception:
                max_workers = 8

            base_meta = {
                "version": 2,
                "backend": args.backend,
                "batch_size": args.batch_size,
                "maxtasksperchild": args.maxtasksperchild,
                "timeout_seconds": args.timeout_seconds,
                "descending_complexity": args.descending_complexity,
                "max_workers": max_workers,
                "pebble_max_tasks": args.pebble_max_tasks,
                "flush_every": args.flush_every,
            }

            results = _run_pebble(
                expressions=pending,
                timeout_seconds=args.timeout_seconds,
                max_workers=max_workers,
                max_tasks=args.pebble_max_tasks,
                flush_every=args.flush_every,
                solved=solved,
                cache_path=cache_path,
                base_meta=base_meta,
            )

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
            "max_workers": args.max_workers,
            "pebble_max_tasks": args.pebble_max_tasks,
            "flush_every": args.flush_every,
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
