#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.clean_helpers import clean_bary


def _load_centers(path: Path) -> list[dict]:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("centers", [])
    return [
        {"center_id": "X1", "bary_list": ["sin(theta/2):cos(theta/2):1"]},
        {"center_id": "X2", "bary_list": ["1:1:1"]},
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 1: Build deduplicated math registry")
    parser.add_argument("--input", default="data/raw_html/parsed_centers.json")
    parser.add_argument("--registry", default="data/math_registry.json")
    parser.add_argument("--index", default="data/center_index.json")
    args = parser.parse_args()

    centers = _load_centers(Path(args.input))
    registry: dict[str, list[str]] = {}
    index: list[dict] = []

    for row in centers:
        cid = row.get("center_id")
        cleaned_list = []
        for raw in row.get("bary_list", []):
            c = clean_bary(raw)
            if not c:
                continue
            cleaned_list.append(c)
            registry.setdefault(c, [])
            if cid not in registry[c]:
                registry[c].append(cid)
        index.append({"center_id": cid, "expressions": cleaned_list, "funcs": row.get("funcs", {})})

    reg_out = {"meta": {"version": 1, "unique_expressions": len(registry)}, "registry": registry}
    idx_out = {"meta": {"version": 1, "centers": len(index)}, "centers": index}

    reg_path = Path(args.registry)
    idx_path = Path(args.index)
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    idx_path.parent.mkdir(parents=True, exist_ok=True)
    reg_path.write_text(json.dumps(reg_out, indent=2), encoding="utf-8")
    idx_path.write_text(json.dumps(idx_out, indent=2), encoding="utf-8")

    print(f"Centers processed: {len(index)}")
    print(f"Unique expressions: {len(registry)}")


if __name__ == "__main__":
    main()
