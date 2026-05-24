"""
Helpers to run subprocesses and tear down entire process trees on timeout.

External MaxSAT binaries (CASHW, Open-WBO, …) are often left running as orphans
when a parent Python worker is killed without signaling the solver's process group.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from typing import List, Optional, Tuple


def isolate_process_session() -> None:
    """Make the current process a new session leader (Linux/macOS)."""
    if sys.platform == "win32":
        return
    try:
        os.setsid()
    except OSError:
        pass


def kill_process_tree(pid: int, *, grace_sec: float = 2.0) -> None:
    """
    Send SIGTERM then SIGKILL to ``pid`` and its process group.

    If ``pid`` shares our process group (e.g. pool worker), only ``pid`` is
    signaled so we do not kill sibling workers.
    """
    if pid <= 0:
        return
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        return

    my_pgid = os.getpgid(os.getpid())
    use_group = pgid > 0 and pgid != my_pgid

    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            if use_group:
                os.killpg(pgid, sig)
            else:
                os.kill(pid, sig)
        except ProcessLookupError:
            return
        if sig == signal.SIGTERM and grace_sec > 0:
            time.sleep(grace_sec)
            try:
                if use_group:
                    os.killpg(pgid, 0)
                else:
                    os.kill(pid, 0)
            except ProcessLookupError:
                return


def run_subprocess_captured(
    cmd: List[str],
    *,
    cwd: Optional[str] = None,
    timeout_sec: Optional[float] = None,
) -> Tuple[str, str, int]:
    """
    Run ``cmd``; return ``(stdout, stderr, returncode)``.

  On timeout, kills the solver process tree and raises ``subprocess.TimeoutExpired``.
    """
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        kill_process_tree(proc.pid)
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            kill_process_tree(proc.pid, grace_sec=0)
        raise
    return stdout or "", stderr or "", int(proc.returncode or 0)
