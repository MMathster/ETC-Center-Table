#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 3: Build final center assets from index + cache")
    parser.add_argument("--index", default="data/center_index.json")
    parser.add_argument("--cache", default="data/solution_cache.json")
    parser.add_argument("--out-json", default="data/03_compiled/etc_centers_final.json")
    parser.add_argument("--out-csv", default="data/03_compiled/etc_centers_final.csv")
    parser.add_argument("--chunk-size", type=int, default=1000)
    parser.add_argument("--chunk-dir", default="data/03_compiled/chunks")
    args = parser.parse_args()

    index = json.loads(Path(args.index).read_text(encoding="utf-8")).get("centers", [])
    solved = json.loads(Path(args.cache).read_text(encoding="utf-8")).get("solved", {})

    rows = []
    for c in index:
        expressions = c.get("expressions", [])
        chosen = solved.get(expressions[0], {}) if expressions else {}
        rows.append(
            {
                "center_id": c.get("center_id"),
                "expression": expressions[0] if expressions else None,
                "x_t": chosen.get("x_t"),
                "y_t": chosen.get("y_t"),
                "weierstrass_n": chosen.get("weierstrass_n"),
                "chosen_weierstrass_angle": chosen.get("chosen_weierstrass_angle"),
                "eval_status": chosen.get("eval_status"),
            }
        )

    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps({"meta": {"version": 1}, "centers": rows}, indent=2), encoding="utf-8")

    out_csv = Path(args.out_csv)
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["center_id"])
        writer.writeheader()
        writer.writerows(rows)

    chunk_dir = Path(args.chunk_dir)
    chunk_dir.mkdir(parents=True, exist_ok=True)
    for i in range(0, len(rows), args.chunk_size):
        chunk = rows[i : i + args.chunk_size]
        part = (i // args.chunk_size) + 1
        (chunk_dir / f"etc_data_chunk_{part}.json").write_text(
            json.dumps({"meta": {"part": part}, "centers": chunk}, indent=2),
            encoding="utf-8",
        )

    print(f"Compiled centers: {len(rows)}")


if __name__ == "__main__":
    main()
