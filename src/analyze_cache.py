#!/usr/bin/env python3
"""
scripts/analyze_cache.py
========================
Diagnostic script for solution_cache.json.

Usage:
    python scripts/analyze_cache.py
    python scripts/analyze_cache.py --cache data/solution_cache.json --top 20
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path


def analyze_cache(cache_path: str = "data/solution_cache.json", top_n: int = 10) -> None:
    path = Path(cache_path)
    if not path.exists():
        print(f"Error: {path} not found.")
        print("Run scripts/02_run_computation.py first to generate the cache.")
        return

    print(f"Loading {path} ...")
    with path.open(encoding="utf-8") as f:
        data = json.load(f)

    solved = data.get("solved", {})
    if not solved:
        print("Cache is empty — nothing to analyze.")
        return

    # ── Categorise ────────────────────────────────────────────────────────────
    ok_times: list[float] = []
    timeout_exprs: list[str] = []
    error_exprs:   list[tuple[str, str]] = []

    for expr, payload in solved.items():
        status = payload.get("eval_status", "")
        secs   = payload.get("seconds", 0.0)
        if status == "ok":
            ok_times.append(secs)
        elif status == "timeout":
            timeout_exprs.append(expr)
        elif status.startswith("error") or status.startswith("exc"):
            error_exprs.append((expr, status))

    total       = len(solved)
    ok_count    = len(ok_times)
    timeout_cnt = len(timeout_exprs)
    error_cnt   = len(error_exprs)
    other_cnt   = total - ok_count - timeout_cnt - error_cnt

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    print("=" * 50)
    print("  Pipeline Diagnostic Report")
    print("=" * 50)
    print(f"  Total processed : {total:,}")
    print(f"  Success (ok)    : {ok_count:,}  ({ok_count/total*100:.1f}%)")
    print(f"  Timeouts        : {timeout_cnt:,}  ({timeout_cnt/total*100:.1f}%)")
    print(f"  Errors          : {error_cnt:,}  ({error_cnt/total*100:.1f}%)")
    if other_cnt:
        print(f"  Other           : {other_cnt:,}  ({other_cnt/total*100:.1f}%)")
    print()

    # ── Compute-time stats for successful centers ─────────────────────────────
    if ok_times:
        ok_times.sort()
        mean_t   = statistics.mean(ok_times)
        median_t = statistics.median(ok_times)
        p90_t    = ok_times[int(ok_count * 0.90)]
        p99_t    = ok_times[min(int(ok_count * 0.99), ok_count - 1)]

        print("  Compute time (successful centers only):")
        print(f"    Mean          : {mean_t*1000:8.2f} ms")
        print(f"    Median        : {median_t*1000:8.2f} ms")
        print(f"    90th pct      : {p90_t*1000:8.2f} ms")
        print(f"    99th pct      : {p99_t*1000:8.2f} ms")
        print(f"    Slowest       : {ok_times[-1]*1000:8.2f} ms")

        # Estimated throughput
        # assume timeout_seconds from meta, default 5s
        timeout_s = data.get("meta", {}).get("timeout_seconds", 5.0)
        if timeout_cnt:
            # weighted average: ok centers at mean_t, timeouts burn timeout_s each
            effective_avg = (ok_count * mean_t + timeout_cnt * timeout_s) / total
        else:
            effective_avg = mean_t
        workers = data.get("meta", {}).get("max_workers", 8) or 8
        est_rate = workers / effective_avg if effective_avg > 0 else 0
        print()
        print(f"  Effective avg task time (incl. timeouts): {effective_avg*1000:.1f} ms")
        print(f"  Estimated throughput ({workers} workers)  : {est_rate:.1f} tasks/sec")

        if timeout_cnt > 0:
            drag = (timeout_cnt * timeout_s) / (ok_count * mean_t + timeout_cnt * timeout_s)
            print(f"  Timeout drag (fraction of wall-time): {drag*100:.1f}%")

        print()
        if mean_t > median_t * 3:
            print("  ⚠  HIGH VARIANCE: A few complex centers are dragging the mean up.")
            print("     Consider lowering --timeout-seconds to 3–5 to reduce drag.")
        else:
            print("  ✓  Variance is stable — compute times are consistent.")

    # ── Top slowest successful centers ────────────────────────────────────────
    if ok_times and top_n > 0:
        slow_list = sorted(
            [(p.get("seconds", 0), e) for e, p in solved.items() if p.get("eval_status") == "ok"],
            reverse=True,
        )
        print()
        print(f"  Slowest {top_n} successful centers:")
        for secs, expr in slow_list[:top_n]:
            print(f"    {secs*1000:7.1f} ms  {expr[:65]}")

    # ── Sample timeout expressions ────────────────────────────────────────────
    if timeout_exprs:
        print()
        print(f"  Sample timeout expressions (first {min(top_n, len(timeout_exprs))}):")
        for expr in timeout_exprs[:top_n]:
            print(f"    {expr[:70]}")

    # ── Error breakdown ───────────────────────────────────────────────────────
    if error_exprs:
        from collections import Counter
        err_types = Counter(status for _, status in error_exprs)
        print()
        print("  Error breakdown:")
        for err_type, count in err_types.most_common():
            print(f"    {count:4d}x  {err_type[:60]}")

    print()
    print("=" * 50)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze solution_cache.json")
    parser.add_argument("--cache", default="data/solution_cache.json")
    parser.add_argument("--top", type=int, default=10,
                        help="Number of slowest/sample expressions to show")
    args = parser.parse_args()
    analyze_cache(args.cache, args.top)
