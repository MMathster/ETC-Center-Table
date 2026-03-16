from __future__ import annotations

import multiprocessing as mp
from typing import Callable, Any


def loky_map(func: Callable[[Any], Any], items: list[Any], n_jobs: int = -1, batch_size: int = 10) -> list[Any]:
    """Use joblib loky when available; otherwise fallback to sequential map."""
    try:
        from joblib import Parallel, delayed  # local import to keep dependency optional

        return Parallel(n_jobs=n_jobs, backend="loky", batch_size=batch_size)(delayed(func)(x) for x in items)
    except Exception:
        return [func(x) for x in items]


def multiprocessing_map(
    func: Callable[[Any], Any], items: list[Any], processes: int | None = None, maxtasksperchild: int = 50
) -> list[Any]:
    ctx = mp.get_context("spawn")
    with ctx.Pool(processes=processes, maxtasksperchild=maxtasksperchild) as pool:
        return pool.map(func, items)
