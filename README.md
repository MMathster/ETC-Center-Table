# ETC Center Table

## The Engineering Challenge: Optimization for Scale

Processing the ETC is not merely a math problem; it is a systems engineering problem. A naive approach using standard trigonometric simplification fails due to the exponential complexity of deep-nested identities.

**The Architecture Transition**
- **V1 (Baseline)**: Relied on sympy.trigsimp(). Throughput was $\sim 0.01$ centers/sec. Most tasks timed out or deadlocked the Python Global Interpreter Lock (GIL).
- **Current**: Implements a Zero-Trig Pipeline. By utilizing the Thales Configuration (mapping the triangle to a unit circumcircle with $C = \pi/2$) and Weierstrass Substitution, the pipeline bypasses trigonometry entirely.
- **Performance**: Current benchmarks show $1.0 – 2.5$ tasks/sec, a $250$-times improvement in throughput.

## Mathematical Background

To ensure every center is represented as a rational algebraic curve, the pipeline employs two primary transformations:

### The Thales-Right Configuration

For locus analysis, we define a specialized triangle where:

- **Vertices:** $A = (1,0)$, $B = (-1,0)$ and $C = \left(\cos\theta, \sin\theta\right)$
- This fixes the circumradius $R = 1$ and the hypotenuse $c = 2$, significantly reducing the degrees of freedom in the resulting barycentric expressions.

### Rational Representations

The half-angle substitution, also known as the Weierstrass substitution, is $t = \tan\frac{\theta}{2}$, where

$$
\left( \cos\theta, \sin\theta \right) \mapsto \left( \dfrac{1 - t^2}{1 + t^2}, \dfrac{2t}{1 + t^2} \right)
$$

which transforms equations, containing $\sin\theta$ and $\cos\theta$, into rational expressions. The pipeline dynamically chooses the minimal $n$ (the "Weierstrass Depth") required to clear all half-angle or quarter-angle identities found in the ETC source.

Since triangle side lengths are of the form $\sin\frac{\theta}{2}$ and $\cos\frac{\theta}{2}$, we can apply that idea for greater powers of $2$'s i.e. $\sin\frac{\theta}{4}$ and $\cos\frac{\theta}{8}$. For instance, if the "deepest" angle factor detected in the expression $\sin\frac{\theta}{2}\cos\frac{\theta}{4}$ is $4$, then the substitution $t = \tan\frac{\theta}{4 \cdot 2} = \tan\frac{\theta}{8}$. Extending this to mixed angle denominators, we can deduce that for the universal substitution $t = \tan\left(\frac{\theta}{p}\right)$ where $p$ is an integer,

- For angle powers of $2$'s only, $p = 2^{\mathrm{max} + 1}$, where $\max$ checks denominators. For instance, for expressions with the deepest factor $4$, like $\tan\frac{\theta}{4}\cos\frac{\theta}{2}$, we set $t = \tan\frac{\theta}{4 \cdot 2} = \tan\frac{\theta}{8}$.
- Otherwise, for angle powers of different prime factors, $p$ takes the least common demoninator of angle denominators. For instance, for expressions, like $\tan\frac{\theta}{3}\cos\frac{\theta}{2}$, we set $t = \tan\frac{\theta}{6}$.

## Filtering & Classification

The final stage of the repository allows for advanced querying of the generated dataset. Centers are not just listed; they are classified as searchable entities:

- **Degree Filtering**: Isolate "Linear" vs. "Cubic" vs. "High-order" loci.
- **Singularity Analysis**: Detect poles where $y(t) \to \infty$ (e.g., points at infinity).
- **Shape invariance**: Identify centers whose locus remains fixed regardless of the triangle's aspect ratio.

## 📈 Real-Time Monitoring

The pipeline includes a terminal-based monitoring system to track throughput and stability.

```bash
# Analyze the computation cache for bottlenecks
python scripts/analyze_cache.py

# Expected Output:
# 15000/62000 | ok=14850 | timeouts=150 | Rate: 2.15 tasks/sec
```

## External Resources

[![Launch Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/MMathster/ETC-Center-Table/HEAD?labpath=ETC_Center_Table_Thales.ipynb)

This repository computes ETC-center parametric outputs (`x(t)`, `y(t)`) using a decoupled JSON pipeline so symbolic workloads are resumable and memory-safe outside a monolithic notebook runtime.

## Run the Thales notebook with repository binding

- **JupyterLab (Binder):**
  [![View Notebook](https://img.shields.io/badge/Platform-Jupyter%20Labs-blue?logo=github)](https://mybinder.org/v2/gh/MMathster/ETC-Center-Table/HEAD?labpath=ETC_Center_Table_Thales.ipynb)
- **Classic Notebook (Binder):**
  [![View Notebook](https://img.shields.io/badge/GitHub-Notebook-blue?logo=github)](https://mybinder.org/v2/gh/MMathster/ETC-Center-Table/HEAD?filepath=ETC_Center_Table_Thales.ipynb)

> Important: run `ETC_Center_Table_Thales.ipynb` from this repository context (Binder or cloned repo root). Downloading and running the notebook in isolation will break imports/path-based access to `src/`, `scripts/`, and `data/`.

<hr>

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
     - `--backend loky|multiprocessing|pebble`
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
- On Windows, prefer `--backend pebble` for OS-level hard timeouts (thread-based timeouts can hang if SymPy gets stuck inside C-extensions).

Example:

```bash
python scripts/02_run_computation.py --backend pebble --timeout-seconds 5 --canary-limit 20
```

## Compatibility wrappers

The previous script names are kept as wrappers:

- `scripts/01_extract_bary.py` -> `01_run_extraction.py`
- `scripts/02_compute_cartesian.py` -> `02_run_computation.py`
- `scripts/03_build_final_tables.py` -> `03_build_final_output.py`

## Notes

- The current solver in `src/geometry_logic.py` is intentionally minimal wiring; migrate the full Section 11 SymPy pipeline into this module incrementally.
- See `docs/pipeline_architecture.md` for architecture and migration plan details.
