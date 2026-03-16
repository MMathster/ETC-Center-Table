# ETC Center Table

This repository compiles ETC centers from 36 University of Evansville pages, filters barycentric coordinates, and computes parametric Cartesian outputs (`x(t)`, `y(t)`).

## New pipeline architecture (decoupled)

To avoid notebook memory bottlenecks, the project now includes a staged pipeline scaffold:

1. `scripts/01_extract_bary.py` — extract + deduplicate barycentric expressions.
2. `scripts/02_compute_cartesian.py` — compute symbolic `x(t), y(t)` on deduplicated tasks.
3. `scripts/03_build_final_tables.py` — compile final JSON/CSV assets.

Supporting modules live in `src/`, and data artifacts are staged in:

- `data/01_raw/`
- `data/02_intermediate/`
- `data/03_compiled/`

See `docs/pipeline_architecture.md` for the full plan.
