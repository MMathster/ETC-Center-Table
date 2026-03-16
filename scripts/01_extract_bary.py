#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.extraction import dedupe_expressions


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 1: Extract and deduplicate barycentric tasks")
    parser.add_argument("--out-dir", default="data/02_intermediate", help="Output directory")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Placeholder expressions (replace with ETC scraping output)
    extracted = [
        "sin(theta/2):cos(theta/2):1",
        " sin(theta/2) : cos(theta/2) : 1 ",
    ]

    tasks = dedupe_expressions(extracted)

    raw_centers = {
        "meta": {"version": 1},
        "centers": [
            {
                "center_id": "X1",
                "bary_hashes": list(tasks.keys()),
                "funcs": {},
            }
        ],
    }
    unique_math_tasks = {
        "meta": {"version": 1},
        "tasks": {h: {"clean_bary": expr, "occurrences": 1} for h, expr in tasks.items()},
    }

    (out_dir / "raw_centers.json").write_text(json.dumps(raw_centers, indent=2), encoding="utf-8")
    (out_dir / "unique_math_tasks.json").write_text(json.dumps(unique_math_tasks, indent=2), encoding="utf-8")
    print(f"Wrote {len(tasks)} unique tasks to {out_dir}")


if __name__ == "__main__":
    main()
