from __future__ import annotations

from joblib import Parallel, delayed


def parallel_map(func, items, backend: str = "loky", n_jobs: int = -1):
    """Small reusable parallel helper for phase 2."""
    return Parallel(n_jobs=n_jobs, backend=backend)(delayed(func)(item) for item in items)
