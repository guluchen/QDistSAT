"""
Run DistQLDPC and parse ``c d_lb`` / ``c d_ub`` / ``o`` lines from its stdout.

See https://github.com/guluchen/DistQLDPC
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import REPO_ROOT

DISTQLDPC_SOLVER = "distqldpc"
PUBLIC_BIN = REPO_ROOT / "bin" / "distqldpc"
VENDOR_BIN = REPO_ROOT / "vendor" / "DistQLDPC" / "bin" / "distqldpc"

_RE_D_LB = re.compile(r"^c\s+d_lb:\s*(\d+)\s*$", re.MULTILINE)
_RE_D_UB = re.compile(r"^c\s+d_ub:\s*(\d+)\s*$", re.MULTILINE)
_RE_D = re.compile(r"^c\s+d\s*:\s*(\d+)\s*$", re.MULTILINE)
_RE_O = re.compile(r"^o\s+(-?\d+)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class DistQLDPCResult:
    """Parsed DistQLDPC stdout."""

    d_lb: Optional[int]
    d_ub: Optional[int]
    d: Optional[int]
    o: Optional[int]
    stdout: str
    stderr: str
    returncode: int
    elapsed_sec: float
    timed_out: bool = False

    @property
    def proved(self) -> bool:
        if self.d is not None:
            return True
        return self.o is not None and self.o >= 0

    def format_result(self) -> Optional[str]:
        """Display string aligned with QDistSAT benchmark partial results."""
        if self.d is not None:
            return str(self.d)
        if self.o is not None and self.o >= 0:
            return str(self.o)
        if self.d_lb is not None and self.d_ub is not None:
            if self.d_lb == self.d_ub:
                return str(self.d_lb)
            return f"[{self.d_lb},{self.d_ub}]"
        if self.d_lb is not None:
            return f"≥{self.d_lb}"
        if self.d_ub is not None:
            return f"≤{self.d_ub}"
        return None


def _last_int(matches: list[re.Match[str]]) -> Optional[int]:
    if not matches:
        return None
    return int(matches[-1].group(1))


def parse_distqldpc_output(text: str) -> DistQLDPCResult:
    """Parse DistQLDPC progress lines (last ``d_lb`` / ``d_ub`` wins)."""
    return DistQLDPCResult(
        d_lb=_last_int(list(_RE_D_LB.finditer(text))),
        d_ub=_last_int(list(_RE_D_UB.finditer(text))),
        d=_last_int(list(_RE_D.finditer(text))),
        o=_last_int(list(_RE_O.finditer(text))),
        stdout=text,
        stderr="",
        returncode=0,
        elapsed_sec=0.0,
    )


def resolve_distqldpc_exe() -> Path:
    if PUBLIC_BIN.is_file():
        return PUBLIC_BIN
    if VENDOR_BIN.is_file():
        return VENDOR_BIN
    raise FileNotFoundError(
        "DistQLDPC not built. Run: python3 scripts/download_maxsat_solvers.py --bench"
    )


def distqldpc_available() -> bool:
    try:
        resolve_distqldpc_exe()
        return True
    except FileNotFoundError:
        return False


def run_distqldpc(
    stem: str,
    matrix_dir: Path,
    *,
    cpu_lim_sec: Optional[float] = None,
    verbose: bool = False,
) -> DistQLDPCResult:
    """
    Run ``bin/distqldpc`` on ``{matrix_dir}/{stem}`` (four matrix files).

    ``cpu_lim_sec`` maps to DistQLDPC ``-cpu-lim=`` (wall-clock SIGKILL).
    """
    exe = resolve_distqldpc_exe()
    prefix = matrix_dir / stem
    for suffix in ("_Hx.txt", "_Hz.txt", "_Gx.txt", "_Gz.txt"):
        if not (matrix_dir / f"{stem}{suffix}").is_file():
            raise FileNotFoundError(f"Missing {matrix_dir / (stem + suffix)}")

    cmd: list[str] = [str(exe)]
    if cpu_lim_sec is not None and cpu_lim_sec > 0:
        cmd.append(f"-cpu-lim={int(cpu_lim_sec)}")
    if verbose:
        cmd.append("-v")
    cmd.append(str(prefix))

    t0 = time.perf_counter()
    timed_out = False
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=cpu_lim_sec + 30 if cpu_lim_sec else None,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        out = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        err = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        elapsed = time.perf_counter() - t0
        parsed = parse_distqldpc_output(out)
        return DistQLDPCResult(
            d_lb=parsed.d_lb,
            d_ub=parsed.d_ub,
            d=parsed.d,
            o=parsed.o,
            stdout=out,
            stderr=err,
            returncode=-1,
            elapsed_sec=elapsed,
            timed_out=True,
        )
    elapsed = time.perf_counter() - t0
    parsed = parse_distqldpc_output(proc.stdout or "")
    return DistQLDPCResult(
        d_lb=parsed.d_lb,
        d_ub=parsed.d_ub,
        d=parsed.d,
        o=parsed.o,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        returncode=int(proc.returncode),
        elapsed_sec=elapsed,
        timed_out=timed_out,
    )
