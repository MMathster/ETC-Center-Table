#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.weierstrass_solver import solve_task


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 2: Solve x(t), y(t) for deduplicated tasks")
    parser.add_argument("--in-file", default="data/02_intermediate/unique_math_tasks.json")
    parser.add_argument("--out-file", default="data/02_intermediate/solved_math_cache.json")
    args = parser.parse_args()

    in_file = Path(args.in_file)
    out_file = Path(args.out_file)

    data = json.loads(in_file.read_text(encoding="utf-8"))
    solved = {}

    for h, payload in data.get("tasks", {}).items():
        result = solve_task(payload.get("clean_bary", ""))
        solved[h] = {
            "x_t": result.x_t,
            "y_t": result.y_t,
            "weierstrass_n": result.weierstrass_n,
            "deepest_angle_den": result.deepest_angle_den,
            "eval_status": result.eval_status,
        }

    out = {"meta": {"version": 1}, "solved": solved}
    out_file.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote solved cache entries: {len(solved)}")


if __name__ == "__main__":
    main()
