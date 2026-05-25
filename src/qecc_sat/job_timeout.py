"""
Wall-clock timeouts for in-process solvers (PySAT, Gurobi, OR-Tools, …).

External binaries should use ``subprocess_utils.run_subprocess_captured`` instead
(subprocess is already an isolated PID).
"""

from __future__ import annotations

import time
from multiprocessing import Process, Queue
from typing import Any, Callable, Optional, TypeVar

from .subprocess_utils import isolate_process_session, kill_process_tree

T = TypeVar("T")


def _isolated_worker(
    q: Queue,
    target: Callable[..., T],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> None:
    isolate_process_session()
    try:
        q.put(("ok", target(*args, **kwargs)))
    except Exception as e:
        q.put(("err", str(e)))


def run_isolated_process(
    target: Callable[..., T],
    args: tuple[Any, ...],
    kwargs: Optional[dict[str, Any]] = None,
    *,
    timeout_sec: float,
    use_spawn: bool = True,
) -> tuple[Optional[T], Optional[str]]:
    """
    Run ``target`` in a disposable child process; kill the tree on wall-clock timeout.

    Returns ``(result, error)`` where ``error`` is ``None``, ``"timeout"``, or a short message.
    """
    if timeout_sec <= 0:
        return target(*args, **(kwargs or {})), None

    q: Queue = Queue()
    kw = kwargs or {}
    if use_spawn:
        try:
            import multiprocessing as mp

            ctx = mp.get_context("spawn")
            p = ctx.Process(target=_isolated_worker, args=(q, target, args, kw))
        except (TypeError, ValueError):
            p = Process(target=_isolated_worker, args=(q, target, args, kw))
    else:
        p = Process(target=_isolated_worker, args=(q, target, args, kw))

    p.start()
    deadline = time.monotonic() + float(timeout_sec)
    stashed: Optional[tuple[str, Any]] = None
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        p.join(timeout=min(0.25, remaining))
        while True:
            try:
                stashed = q.get_nowait()
            except Exception:
                break
        if not p.is_alive():
            break

    if p.is_alive():
        kill_process_tree(p.pid)
        p.join(timeout=2)
        return None, "timeout"

    p.join()
    while True:
        try:
            stashed = q.get_nowait()
        except Exception:
            break

    if stashed is None:
        return None, "no result"
    if stashed[0] == "ok":
        return stashed[1], None
    return None, str(stashed[1])[:200]
