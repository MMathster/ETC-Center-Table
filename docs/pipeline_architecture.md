# ETC Center Table Decoupled Pipeline Plan

## Objective
Process large ETC barycentric catalogs without notebook memory saturation by splitting extraction, solving, and compilation into independent resumable scripts connected by JSON contracts.

## Pipeline stages

### 1) Extraction & Registry (`scripts/01_run_extraction.py`)
- Input: parsed center rows (example: `data/raw_html/parsed_centers.json`).
- Responsibilities:
  - normalize bary strings (`clean_bary`),
  - deduplicate to unique expressions,
  - produce center-to-expression index.
- Outputs:
  - `data/math_registry.json` (expression -> list of center ids),
  - `data/center_index.json` (center -> expression list + funcs metadata).

### 2) Compute Engine (`scripts/02_run_computation.py`)
- Input: `data/math_registry.json`.
- Responsibilities:
  - solve only unique expressions,
  - persist solutions to JSON cache,
  - support backend tuning for throughput and memory stability.
- Output: `data/solution_cache.json`.
- Runtime controls:
  - `--backend loky|multiprocessing`
  - `--batch-size` (loky dispatch granularity)
  - `--maxtasksperchild` (multiprocessing worker reset cadence)

### 3) Final Compiler (`scripts/03_build_final_output.py`)
- Inputs: `data/center_index.json`, `data/solution_cache.json`.
- Responsibilities:
  - assemble per-center chosen equations,
  - export final JSON + CSV,
  - generate chunked JSON for front-end loading.
- Outputs:
  - `data/03_compiled/etc_centers_final.json`
  - `data/03_compiled/etc_centers_final.csv`
  - `data/03_compiled/chunks/etc_data_chunk_*.json`

## Why this architecture improves performance
- **Memory isolation:** each stage exits and releases memory before the next stage starts.
- **Dedup-first solving:** expensive symbolic work runs once per unique expression.
- **Crash-safe resume:** `solution_cache.json` persists solved expressions between runs.
- **Deploy-friendly outputs:** chunked JSON can be served directly by static hosting.

## Next migration milestones
1. Port full Section 11 symbolic logic from notebook into `src/geometry_logic.py`.
2. Port parsing/extraction logic into ingestion scripts for real ETC page snapshots.
3. Add diagnostics: cache hit ratio, fail buckets, and tasks/sec per backend.
4. Add regression tests for parsing and deterministic solver outputs.


## Anti-stall strategy for SymPy black holes

Phase 2 includes explicit controls to prevent one pathological center from stalling the full run:

- strict per-task timeout via `--timeout-seconds`,
- optional canary mode (`--canary-limit`) for first-N sequential trace,
- complexity-based ordering (`bary_complexity`) to solve/cache easy expressions first,
- deterministic algebra policy (prefer `cancel`/rational forms; avoid global `simplify` loops in pipeline code).

Conway helpers and rational Thales substitutions are hosted in `src/geometry_logic.py` (`to_conway`, `get_thales_funcs`) to support incremental migration of notebook Section 11 logic.
