#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 3: Compile final center tables")
    parser.add_argument("--raw-centers", default="data/02_intermediate/raw_centers.json")
    parser.add_argument("--solved-cache", default="data/02_intermediate/solved_math_cache.json")
    parser.add_argument("--out-json", default="data/03_compiled/etc_centers_final.json")
    parser.add_argument("--out-csv", default="data/03_compiled/etc_centers_final.csv")
    args = parser.parse_args()

    raw = json.loads(Path(args.raw_centers).read_text(encoding="utf-8"))
    solved = json.loads(Path(args.solved_cache).read_text(encoding="utf-8")).get("solved", {})

    rows = []
    for center in raw.get("centers", []):
        hashes = center.get("bary_hashes", [])
        first = solved.get(hashes[0], {}) if hashes else {}
        rows.append(
            {
                "center_id": center.get("center_id"),
                "x_t": first.get("x_t"),
                "y_t": first.get("y_t"),
                "weierstrass_n": first.get("weierstrass_n"),
                "eval_status": first.get("eval_status"),
            }
        )

    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps({"meta": {"version": 1}, "centers": rows}, indent=2), encoding="utf-8")

    out_csv = Path(args.out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["center_id", "x_t", "y_t", "weierstrass_n", "eval_status"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Compiled centers: {len(rows)}")


if __name__ == "__main__":
    main()
