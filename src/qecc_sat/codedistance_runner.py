"""
Optional [codeDistancePYPI](https://github.com/m-webster/codeDistancePYPI) backends for benchmarks.

Install: ``pip install -e ".[comparison]"`` (see README). External tools may still be required
per method (Gurobi, Magma, dist-m4ri binary).
"""

from __future__ import annotations

import contextlib
import importlib.util
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional

from . import REPO_ROOT

CODEDISTANCE_SOLVER = "codedistance"
CD_SOLVER_PREFIX = "cd-"

# (config_id, method name, extra params for CSScodeDistance)
CODEDISTANCE_BENCH_CONFIGS: tuple[tuple[str, str, dict[str, Any]], ...] = (
    ("gurobi", "GurobiDist", {}),
    ("mip-scip", "MIPDist", {"MIP_solver": "SCIP"}),
    ("m4ri-cc", "dist_m4ri_CC", {}),
    ("magma", "magmaMinWord", {}),
)

_CONFIG_BY_ID = {cid: (method, extra) for cid, method, extra in CODEDISTANCE_BENCH_CONFIGS}
_CONFIG_IDS = frozenset(_CONFIG_BY_ID)

# Defaults merged into CSScodeDistance params (codeDistance assumes keys like LOCheck exist).
_CODEDISTANCE_PARAM_DEFAULTS: dict[str, Any] = {
    "verbose": 0,
    "LOCheck": 0,
}


def _is_runnable_exe(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def repo_root_candidates() -> list[Path]:
    """Repo roots for ``bin/dist_m4ri`` (editable install, cwd, env)."""
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
        if (parent / "bin" / "dist_m4ri").exists():
            roots.append(parent)
            break
    seen: set[Path] = set()
    out: list[Path] = []
    for root in roots:
        if root not in seen:
            seen.add(root)
            out.append(root)
    return out


def _dist_m4ri_candidates() -> list[Path]:
    paths: list[Path] = []
    env_exe = os.environ.get("QEECC_SAT_DIST_M4RI")
    if env_exe:
        paths.append(Path(env_exe).expanduser())
    for root in repo_root_candidates():
        paths.append(root / "bin" / "dist_m4ri")
        paths.append(root / "vendor" / "dist-m4ri" / "src" / "dist_m4ri")
    which = shutil.which("dist_m4ri")
    if which:
        paths.append(Path(which))
    return paths


def codedistance_solver_id(config_id: str) -> str:
    return f"{CD_SOLVER_PREFIX}{config_id}"


def is_codedistance_solver(name: str) -> bool:
    n = name.lower()
    if n == CODEDISTANCE_SOLVER:
        return True
    if not n.startswith(CD_SOLVER_PREFIX):
        return False
    return resolve_codedistance_config_id(n) is not None


def resolve_codedistance_config_id(solver_name: str) -> Optional[str]:
    """Map ``cd-gurobi``, ``gurobi``, or ``codedistance`` umbrella to a config id."""
    n = solver_name.lower().strip()
    if n == CODEDISTANCE_SOLVER:
        return None
    if n.startswith(CD_SOLVER_PREFIX):
        cid = n[len(CD_SOLVER_PREFIX) :]
    else:
        cid = n
    return cid if cid in _CONFIG_IDS else None


def expand_codedistance_solver_requests(solvers: list[str]) -> list[str]:
    """Expand ``codedistance`` to four ``cd-*`` entries; drop unknown cd names."""
    out: list[str] = []
    for s in solvers:
        sl = s.lower()
        if sl == CODEDISTANCE_SOLVER:
            for cid, _, _ in CODEDISTANCE_BENCH_CONFIGS:
                sid = codedistance_solver_id(cid)
                if sid not in out:
                    out.append(sid)
            continue
        cid = resolve_codedistance_config_id(sl)
        if cid is not None:
            sid = codedistance_solver_id(cid)
            if sid not in out:
                out.append(sid)
            continue
        out.append(s)
    return out


def codedistance_available(*, import_check: bool = False) -> bool:
    """
    Return whether the ``codedistance`` package is installed.

    By default only checks that the module can be found (fast; suitable for
    ``--list-solvers``). Pass ``import_check=True`` to actually import the
    package (slow: pulls in ortools, gurobipy, matplotlib, etc.).
    """
    if import_check:
        try:
            from codedistance import CSScodeDistance  # noqa: F401

            return True
        except ImportError:
            return False
    return importlib.util.find_spec("codedistance") is not None


def dist_m4ri_install_hint() -> str:
    return (
        "cd-m4ri-cc (dist_m4ri_CC): python3 scripts/install_dist_m4ri.py "
        "(needs gcc, make, libm4ri — Ubuntu: libm4ri-dev; macOS: brew install m4ri)"
    )


def resolve_dist_m4ri_executable() -> Optional[str]:
    for path in _dist_m4ri_candidates():
        if _is_runnable_exe(path):
            return str(path.resolve())
    return None


def _prepend_repo_bin_to_path() -> None:
    for root in repo_root_candidates():
        bin_dir = str((root / "bin").resolve())
        path = os.environ.get("PATH", "")
        if bin_dir not in path.split(os.pathsep):
            os.environ["PATH"] = bin_dir + (os.pathsep + path if path else "")


def magma_install_hint() -> str:
    return (
        "cd-magma (magmaMinWord): export QEECC_SAT_MAGMA=/path/to/magma executable, "
        "or MAGMA_HOME=/home/yfc/distanceLibTest, or add Magma's bin dir to PATH"
    )


def _magma_candidates() -> list[Path]:
    paths: list[Path] = []
    for env in ("QEECC_SAT_MAGMA", "MAGMA_BIN"):
        v = os.environ.get(env)
        if v:
            paths.append(Path(v).expanduser())
    for env_home in ("MAGMA_HOME", "MAGMA_ROOT"):
        home = os.environ.get(env_home)
        if home:
            base = Path(home).expanduser()
            for sub in ("", "magma", "bin", "Magma"):
                d = base / sub if sub else base
                paths.append(d / "magma")
                paths.append(d)
    for base in (Path.home() / "distanceLibTest",):
        if base.is_dir():
            for sub in ("", "magma", "bin", "Magma", "magma-2.28-14"):
                d = base / sub if sub else base
                paths.append(d / "magma")
                paths.append(d)
    which = shutil.which("magma")
    if which:
        paths.append(Path(which))
    seen: set[Path] = set()
    out: list[Path] = []
    for p in paths:
        rp = p.resolve() if p.exists() else p
        if rp not in seen:
            seen.add(rp)
            out.append(p)
    return out


def resolve_magma_executable() -> Optional[str]:
    for path in _magma_candidates():
        if _is_runnable_exe(path):
            return str(path.resolve())
    return None


def _prepend_magma_to_path() -> None:
    exe = resolve_magma_executable()
    if exe is None:
        return
    bin_dir = str(Path(exe).parent.resolve())
    path = os.environ.get("PATH", "")
    if bin_dir not in path.split(os.pathsep):
        os.environ["PATH"] = bin_dir + (os.pathsep + path if path else "")


def codedistance_pip_install_hint() -> str:
    return (
        'pip install -e ".[comparison]"  '
        "(or: python3 scripts/install_benchmark_deps.py)"
    )


def codedistance_install_hint() -> str:
    return (
        f"codeDistance comparison backends need: {codedistance_pip_install_hint()} "
        "(codedistance + ortools for MIPDist/SCIP). "
        "GurobiDist needs a Gurobi license; "
        f"dist_m4ri_CC needs dist-m4ri ({dist_m4ri_install_hint()}); "
        "magmaMinWord needs Magma on PATH. See codeDistancePYPI README."
    )


def codedistance_missing_status() -> str:
    return "codedistance missing"


def codedistance_prerequisite(config_id: str) -> Optional[tuple[str, str]]:
    """
    If an external tool is required but missing, return ``(short_status, detail_hint)``.
    """
    if config_id == "m4ri-cc":
        if resolve_dist_m4ri_executable() is None:
            return ("dist_m4ri not installed", dist_m4ri_install_hint())
    elif config_id == "magma":
        if resolve_magma_executable() is None:
            return ("magma not on PATH", magma_install_hint())
    return None


def explain_codedistance_failure(
    config_id: str,
    error: Optional[str] = None,
) -> tuple[str, str]:
    """
    Map exceptions from codedistance into a short Status column label and a longer hint.
    """
    pre = codedistance_prerequisite(config_id)
    if pre is not None:
        return pre
    msg = (error or "").strip()
    low = msg.lower()
    if "dist_m4ri" in low and (
        "no such file" in low or "not found" in low or "errno 2" in low
    ):
        return ("dist_m4ri not installed", dist_m4ri_install_hint())
    if "magma" in low and (
        "no such file" in low or "not found" in low or "errno 2" in low
    ):
        return ("magma not on PATH", magma_install_hint())
    if config_id == "gurobi" or "gurobi" in low:
        return (
            "Gurobi failed",
            f"cd-gurobi (GurobiDist): check Gurobi license / gurobipy install. ({msg[:120]})",
        )
    if config_id == "mip-scip" or "set_time_limit" in low:
        return (
            "MIPDist failed",
            "cd-mip-scip (MIPDist/SCIP): needs pip install ortools; "
            "if maxTime errors persist, report upstream codedistance issue",
        )
    if not msg:
        return ("no distance", "codeDistance returned no distance estimate")
    short = msg.replace("\n", " ")[:60]
    return (short, f"codeDistance ({config_id}): {msg[:200]}")


def _import_css_code_distance():
    from codedistance import CSScodeDistance

    return CSScodeDistance


@contextlib.contextmanager
def _suppress_gurobi_console() -> Iterator[None]:
    """Hide Gurobi license / parameter lines on stdout during GurobiDist."""
    try:
        import gurobipy as gp

        gp.setParam("OutputFlag", 0)
        gp.setParam("LogToConsole", 0)
    except Exception:
        pass
    with open(os.devnull, "w", encoding="utf-8") as devnull:
        with contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
            yield


@dataclass(frozen=True)
class CodedistanceResult:
    method: str
    d: Optional[int]
    n: Optional[int]
    k: Optional[int]
    elapsed_sec: float
    raw: Optional[dict[str, Any]] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.d is not None

    def format_result(self) -> Optional[str]:
        if self.d is None:
            return None
        return str(int(self.d))


def run_codedistance(
    hx: list[list[int]],
    hz: list[list[int]],
    *,
    method: str,
    extra_params: Optional[Mapping[str, Any]] = None,
    timeout_sec: Optional[float] = None,
    component: str = "Z",
    seed: Optional[int] = None,
) -> CodedistanceResult:
    """Run ``CSScodeDistance`` on parity checks (Z-distance by default)."""
    import numpy as np

    Hx = np.array(hx, dtype=np.int8)
    Hz = np.array(hz, dtype=np.int8)
    params: dict[str, Any] = {**_CODEDISTANCE_PARAM_DEFAULTS, **dict(extra_params or {})}
    if timeout_sec is not None:
        # OR-Tools MIPDist passes maxTime to Solver.set_time_limit (int64 seconds).
        params["maxTime"] = max(1, int(round(timeout_sec)))
    def _call() -> Any:
        CSScodeDistance = _import_css_code_distance()
        return CSScodeDistance(
            Hx,
            Hz,
            method=method,
            params=params,
            component=component,
            seed=seed,
        )

    if method == "dist_m4ri_CC":
        _prepend_repo_bin_to_path()
    if method == "magmaMinWord":
        _prepend_magma_to_path()

    t0 = time.perf_counter()
    try:
        if method == "GurobiDist":
            with _suppress_gurobi_console():
                out = _call()
        else:
            out = _call()
    except Exception as e:
        config_id = next(
            (cid for cid, m, _ in CODEDISTANCE_BENCH_CONFIGS if m == method),
            method,
        )
        short, _detail = explain_codedistance_failure(config_id, str(e))
        return CodedistanceResult(
            method=method,
            d=None,
            n=None,
            k=None,
            elapsed_sec=time.perf_counter() - t0,
            error=short,
        )
    elapsed = time.perf_counter() - t0
    d_val = out.get("d") if isinstance(out, dict) else None
    d_int: Optional[int] = None
    if d_val is not None:
        try:
            d_int = int(d_val)
        except (TypeError, ValueError):
            d_int = None
    n_val = out.get("n") if isinstance(out, dict) else None
    k_val = out.get("k") if isinstance(out, dict) else None
    return CodedistanceResult(
        method=method,
        d=d_int,
        n=int(n_val) if n_val is not None else None,
        k=int(k_val) if k_val is not None else None,
        elapsed_sec=elapsed,
        raw=out if isinstance(out, dict) else None,
    )
