from __future__ import annotations

import concurrent.futures
import functools
import multiprocessing as mp
import os
import signal
from typing import Callable, Any


def strict_timeout(seconds: float = 5.0):
    """Decorator to cap function runtime.

    On POSIX, uses SIGALRM for hard timeout semantics per call.
    On non-POSIX, falls back to thread-based timeout.
    """

    def decorator(func: Callable[..., Any]):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if os.name == "posix":
                def _handler(signum, frame):
                    raise TimeoutError(f"timeout>{seconds}s")

                prev = signal.signal(signal.SIGALRM, _handler)
                signal.setitimer(signal.ITIMER_REAL, seconds)
                try:
                    return func(*args, **kwargs)
                except TimeoutError:
                    return {"status": "timeout", "timeout_seconds": seconds}
                finally:
                    signal.setitimer(signal.ITIMER_REAL, 0)
                    signal.signal(signal.SIGALRM, prev)

            # Cross-platform fallback (soft timeout)
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            future = executor.submit(func, *args, **kwargs)
            try:
                return future.result(timeout=seconds)
            except concurrent.futures.TimeoutError:
                return {"status": "timeout", "timeout_seconds": seconds}
            except Exception as exc:  # pragma: no cover - defensive path
                return {"status": f"error:{exc}"}
            finally:
                executor.shutdown(wait=False, cancel_futures=True)

        return wrapper

    return decorator


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
