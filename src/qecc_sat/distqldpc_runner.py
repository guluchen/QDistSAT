"""
Run DistQLDPC and parse ``c d_lb`` / ``c d_ub`` / ``o`` lines from its stdout.

See https://github.com/guluchen/DistQLDPC
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from . import REPO_ROOT

DISTQLDPC_SOLVER = "distqldpc"

# DistQLDPC CLI cardinality modes (see distqldpc.cc). Benchmark runs both.
DISTQLDPC_BENCH_CONFIGS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("no-card", ("-no-card",)),
    ("card-mto", ("-card-mto",)),  # MTO tree encoding (user-facing label: card-mto)
)

PUBLIC_BIN = REPO_ROOT / "bin" / "distqldpc"
VENDOR_BIN = REPO_ROOT / "vendor" / "DistQLDPC" / "bin" / "distqldpc"

_RE_D_LB = re.compile(r"^c\s+d_lb:\s*(\d+)\s*$", re.MULTILINE)
_RE_D_UB = re.compile(r"^c\s+d_ub:\s*(\d+)\s*$", re.MULTILINE)
_RE_D = re.compile(r"^c\s+d\s*:\s*(\d+)\s*$", re.MULTILINE)
_RE_O = re.compile(r"^o\s+(-?\d+)\s*$", re.MULTILINE)
# With ``-v``: final solver size and post-elimination CNF size (approximate for Clauses).
_RE_NOF_VARS = re.compile(r"vars\s+(\d+)\s+\(base\s+\d+", re.MULTILINE)
_RE_REDUCED_CLS = re.compile(
    r"Reduced to\s+\d+\s+vars,\s+(\d+)\s+cls\b", re.MULTILINE
)


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
    nof_vars: Optional[int] = None
    nof_clauses: Optional[int] = None
    clauses_approx: bool = False

    @property
    def proved(self) -> bool:
        if self.d is not None:
            return True
        return self.o is not None and self.o >= 0

    def format_result(self) -> Optional[str]:
        """Benchmark Result column: exact ``d`` only; else same as SAT partial (≥lb, ≤ub, [lb,ub])."""
        if self.proved:
            if self.d is not None:
                return str(self.d)
            if self.o is not None and self.o >= 0:
                return str(self.o)
        return format_distance_bounds(lb=self.d_lb, ub=self.d_ub)


def format_distance_bounds(
    *,
    lb: Optional[int] = None,
    ub: Optional[int] = None,
    witness: Optional[int] = None,
) -> Optional[str]:
    """Shared with SAT benchmark timeout formatting (``≥lb``, ``≤ub``, ``[lb,ub]``)."""
    if witness is not None:
        return str(int(witness))
    if lb is not None and ub is not None:
        if lb == ub:
            return str(int(lb))
        return f"[{int(lb)},{int(ub)}]"
    if lb is not None:
        return f"≥{int(lb)}"
    if ub is not None:
        return f"≤{int(ub)}"
    return None


def _last_int(matches: list[re.Match[str]]) -> Optional[int]:
    if not matches:
        return None
    return int(matches[-1].group(1))


def _parse_size_stats(text: str) -> tuple[Optional[int], Optional[int], bool]:
    """Extract ``nof_vars`` / ``nof_clauses`` from verbose DistQLDPC stdout."""
    var_matches = list(_RE_NOF_VARS.finditer(text))
    cls_matches = list(_RE_REDUCED_CLS.finditer(text))
    nof_vars = _last_int(var_matches)
    nof_clauses = _last_int(cls_matches)
    return nof_vars, nof_clauses, nof_clauses is not None


def parse_distqldpc_output(text: str) -> DistQLDPCResult:
    """Parse DistQLDPC progress lines (last ``d_lb`` / ``d_ub`` wins)."""
    nof_vars, nof_clauses, clauses_approx = _parse_size_stats(text)
    return DistQLDPCResult(
        d_lb=_last_int(list(_RE_D_LB.finditer(text))),
        d_ub=_last_int(list(_RE_D_UB.finditer(text))),
        d=_last_int(list(_RE_D.finditer(text))),
        o=_last_int(list(_RE_O.finditer(text))),
        stdout=text,
        stderr="",
        returncode=0,
        elapsed_sec=0.0,
        nof_vars=nof_vars,
        nof_clauses=nof_clauses,
        clauses_approx=clauses_approx,
    )


def _is_runnable_exe(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def repo_root_candidates() -> list[Path]:
    """Repo roots to search for ``bin/distqldpc`` (editable install, cwd, env)."""
    roots: list[Path] = []
    env_root = os.environ.get("QEECC_SAT_REPO_ROOT")
    if env_root:
        roots.append(Path(env_root).resolve())
    roots.append(REPO_ROOT.resolve())
    cwd = Path.cwd().resolve()
    for parent in [cwd, *cwd.parents][:8]:
        if (parent / "bin" / "maxsat" / "manifest.json").is_file():
            roots.append(parent)
            break
    seen: set[Path] = set()
    out: list[Path] = []
    for root in roots:
        if root not in seen:
            seen.add(root)
            out.append(root)
    return out


def distqldpc_exe_candidates() -> list[Path]:
    paths: list[Path] = []
    env_exe = os.environ.get("QEECC_SAT_DISTQLDPC")
    if env_exe:
        paths.append(Path(env_exe).expanduser())
    for root in repo_root_candidates():
        paths.append(root / "bin" / "distqldpc")
        paths.append(root / "vendor" / "DistQLDPC" / "bin" / "distqldpc")
    which = shutil.which("distqldpc")
    if which:
        paths.append(Path(which))
    # Defaults last (may be broken symlinks).
    paths.append(PUBLIC_BIN)
    paths.append(VENDOR_BIN)
    seen: set[Path] = set()
    out: list[Path] = []
    for path in paths:
        key = path.resolve() if path.exists() else path
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def distqldpc_install_hint() -> str:
    checked = ", ".join(str(p) for p in distqldpc_exe_candidates()[:4])
    return (
        "DistQLDPC binary not found. Build it from the repo root:\n"
        "  python3 scripts/install_distqldpc.py\n"
        "  python3 scripts/install_benchmark_deps.py --list   # should show distqldpc OK\n"
        "  ./bin/distqldpc data/matrices/LP_34_20_2           # smoke test\n"
        "Debian/Ubuntu deps: sudo apt install -y g++ make zlib1g-dev git\n"
        f"Checked: {checked}"
    )


def distqldpc_missing_status() -> str:
    """Short Status column text when the binary is absent."""
    return "distqldpc missing (python3 scripts/install_distqldpc.py)"


def resolve_distqldpc_exe() -> Path:
    for path in distqldpc_exe_candidates():
        if _is_runnable_exe(path):
            return path
    raise FileNotFoundError(distqldpc_install_hint())


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
    capture_stats: bool = False,
    cli_flags: Sequence[str] = (),
) -> DistQLDPCResult:
    """
    Run ``bin/distqldpc`` on ``{matrix_dir}/{stem}`` (four matrix files).

    ``cpu_lim_sec`` maps to DistQLDPC ``-cpu-lim=`` (wall-clock SIGKILL).
    ``cli_flags`` e.g. ``("-no-card",)`` or ``("-card-mto",)`` (see ``DISTQLDPC_BENCH_CONFIGS``).
    ``capture_stats`` adds ``-v`` so stdout includes ``vars`` / ``Reduced to … cls`` lines
    for benchmark Vars/Clauses columns (ignored if ``verbose`` is already set).
    """
    exe = resolve_distqldpc_exe()
    prefix = matrix_dir / stem
    for suffix in ("_Hx.txt", "_Hz.txt", "_Gx.txt", "_Gz.txt"):
        if not (matrix_dir / f"{stem}{suffix}").is_file():
            raise FileNotFoundError(f"Missing {matrix_dir / (stem + suffix)}")

    cmd: list[str] = [str(exe)]
    if cpu_lim_sec is not None and cpu_lim_sec > 0:
        cmd.append(f"-cpu-lim={int(cpu_lim_sec)}")
    if verbose or capture_stats:
        cmd.append("-v")
    for flag in cli_flags:
        if flag not in cmd:
            cmd.append(flag)
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
            nof_vars=parsed.nof_vars,
            nof_clauses=parsed.nof_clauses,
            clauses_approx=parsed.clauses_approx,
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
        nof_vars=parsed.nof_vars,
        nof_clauses=parsed.nof_clauses,
        clauses_approx=parsed.clauses_approx,
    )
