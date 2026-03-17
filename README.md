# ETC Center Table

[![Launch Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/MMathster/ETC-Center-Table/HEAD?labpath=ETC_Center_Table_Thales.ipynb)

This repository computes ETC-center parametric outputs (`x(t)`, `y(t)`) using a decoupled JSON pipeline so symbolic workloads are resumable and memory-safe outside a monolithic notebook runtime.

## Run the Thales notebook with repository binding

- **JupyterLab (Binder):** https://mybinder.org/v2/gh/MMathster/ETC-Center-Table/HEAD?labpath=ETC_Center_Table_Thales.ipynb
- **Classic Notebook (Binder):** https://mybinder.org/v2/gh/MMathster/ETC-Center-Table/HEAD?filepath=ETC_Center_Table_Thales.ipynb

> Important: run `ETC_Center_Table_Thales.ipynb` from this repository context (Binder or cloned repo root). Downloading and running the notebook in isolation will break imports/path-based access to `src/`, `scripts/`, and `data/`.

## Current progress

- The notebook (`ETC_Center_Table_Thales.ipynb`) is still present for research and validation.
- A repository-first 3-phase pipeline now exists for production-scale runs.

## 3-phase JSON pipeline

1. **Extraction/Registry**: `scripts/01_run_extraction.py`
   - Input: `data/raw_html/parsed_centers.json` (or your own parsed scrape output)
   - Output:
     - `data/math_registry.json` (clean expression -> list of X-centers)
     - `data/center_index.json` (center -> cleaned expressions)

2. **Parallel Compute Engine**: `scripts/02_run_computation.py`
   - Input: `data/math_registry.json`
   - Output: `data/solution_cache.json` (persistent solved expression cache)
   - Supports:
     - `--backend loky|multiprocessing`
     - `--batch-size` for loky throughput tuning
     - `--maxtasksperchild` for multiprocessing memory reset behavior

3. **Asset Compiler**: `scripts/03_build_final_output.py`
   - Inputs: `data/center_index.json`, `data/solution_cache.json`
   - Outputs:
     - `data/03_compiled/etc_centers_final.json`
     - `data/03_compiled/etc_centers_final.csv`
     - `data/03_compiled/chunks/etc_data_chunk_*.json`


## Black-hole protections (stalled batch mitigation)

`02_run_computation.py` now includes guardrails for pathological SymPy workloads:

- `--timeout-seconds` sets a strict per-expression timeout (default `5.0`).
- `--canary-limit` runs an early sequential canary probe and prints which expressions are being attempted.
- Complexity ordering is enabled before dispatch (`bary_complexity`) so easier expressions can be solved and cached first.
- `--maxtasksperchild` remains available for worker recycling in multiprocessing mode.

Example:

```bash
python scripts/02_run_computation.py --backend loky --timeout-seconds 5 --canary-limit 20
```

## Compatibility wrappers

The previous script names are kept as wrappers:

- `scripts/01_extract_bary.py` -> `01_run_extraction.py`
- `scripts/02_compute_cartesian.py` -> `02_run_computation.py`
- `scripts/03_build_final_tables.py` -> `03_build_final_output.py`

## Notes

- The current solver in `src/geometry_logic.py` is intentionally minimal wiring; migrate the full Section 11 SymPy pipeline into this module incrementally.
- See `docs/pipeline_architecture.md` for architecture and migration plan details.
