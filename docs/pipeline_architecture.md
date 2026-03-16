# ETC Center Table Decoupled Pipeline Plan

## Why move away from monolithic notebooks
Large SymPy workloads mixed with scraping/parsing in one Jupyter runtime can cause memory churn, slow garbage collection, and poor restartability. The repository should separate concerns into resumable phases with persistent JSON caches.

## Three-phase pipeline

### Phase 1 — Extraction and deduplication (`scripts/01_extract_bary.py`)
- Read/scrape ETC source pages.
- Extract center IDs, barycentric expression lists, and custom function definitions.
- Normalize/clean barycentric strings.
- Deduplicate expression workloads using stable hashes.
- Write:
  - `data/02_intermediate/raw_centers.json`
  - `data/02_intermediate/unique_math_tasks.json`

### Phase 2 — Symbolic compute engine (`scripts/02_compute_cartesian.py`)
- Read `unique_math_tasks.json` only.
- Compute `x(t)`, `y(t)` with Weierstrass policies and complexity tie-breaks.
- Parallelize on deduplicated task list (loky-first fallback strategy).
- Persist each solved task incrementally (resume-safe).
- Write:
  - `data/02_intermediate/solved_math_cache.json`

### Phase 3 — Portfolio/table compiler (`scripts/03_build_final_tables.py`)
- Join center-to-hash mappings with solved cache.
- Build final compiled outputs for analytics + website loading.
- Write:
  - `data/03_compiled/etc_centers_final.json`
  - `data/03_compiled/etc_centers_final.csv`
  - optional chunked JSON files for front-end pagination/lazy loading.

## Data contracts (JSON)

### `raw_centers.json`
Dictionary of center records with references to expression hashes and metadata.

### `unique_math_tasks.json`
Deduplicated expression task registry keyed by hash.

### `solved_math_cache.json`
Persistent solved equation cache keyed by hash, including diagnostics (`weierstrass_n`, evaluation status, timing).

## Operational recommendations
- Keep notebooks for exploration/validation only.
- Run phase scripts from CLI with explicit I/O paths.
- Save progress frequently in phase 2 to tolerate interruptions.
- Add small monitoring stats (tasks/sec, cache hit rate, fail counts) to each phase log.

## Next implementation steps
1. Move reusable SymPy helpers from notebook into `src/geometry_core.py` and `src/weierstrass_solver.py`.
2. Add unit tests for parsing + denominator detection.
3. Add benchmark mode over a 500-task sample to tune backend/chunk size.
4. Add chunked JSON compiler for the website data path.
