#!/usr/bin/env python3
"""
Benchmark SAT solver performance on a CSS code from parity-check matrices.

Default instance: BB_72_12_6 (data/matrices/BB_72_12_6_Hx.txt, _Hz.txt).

Tests each solver and cardinality encoding; reports time, vars, clauses.
MaxSAT backends (``rc2-*``, ``open-wbo``, …) use one optimization pass
instead of scanning k=1..D.

Usage:
  python benchmarks/benchmark_solver_performance.py
  python benchmarks/benchmark_solver_performance.py --timeout 300   # override per-config limit
  # Default: 180s (3 min) wall-clock timeout per configuration
  python benchmarks/benchmark_solver_performance.py --quick   # SC_9_1_3, d=3
  python benchmarks/benchmark_solver_performance.py --stem SC_9_1_3 -d 3 --solvers rc2-g3 maxcdcl distqldpc
  python benchmarks/benchmark_solver_performance.py --stem BB_72_12_6 -d 6 --solvers codedistance  # optional pip [comparison]
  python benchmarks/benchmark_solver_performance.py --stem BB_72_12_6 -d 6
  python benchmarks/benchmark_solver_performance.py --stem BB_144_12_12 -d 12
  python benchmarks/benchmark_solver_performance.py --stems BB_72_12_6 BB_90_8_10
  python benchmarks/benchmark_solver_performance.py --stems-dir data/matrices
  python benchmarks/benchmark_solver_performance.py --encodings seqcounter log
  python benchmarks/benchmark_solver_performance.py -j 4              # 4 parallel configs
  python benchmarks/benchmark_solver_performance.py --auto-jobs       # ~half of idle CPUs (default)
  python benchmarks/benchmark_solver_performance.py --jobs 1          # sequential
  python benchmarks/benchmark_solver_performance.py --css-split --tanner-pruning
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from multiprocessing import Process, Queue
from pathlib import Path
from queue import Empty
from typing import Any, Iterable, List, Optional

from pysat.card import EncType
from qecc_sat import DEFAULT_MATRIX_DIR
from qecc_sat.literature_distances import LITERATURE_BB_DISTANCES
from qecc_sat.io import build_s_from_hx_hz, load_matrix, resolve_precomputed_logical_basis
from qecc_sat.codedistance_runner import (
    CODEDISTANCE_BENCH_CONFIGS,
    CODEDISTANCE_SOLVER,
    codedistance_available,
    codedistance_install_hint,
    codedistance_pip_install_hint,
    codedistance_missing_status,
    codedistance_prerequisite,
    codedistance_solver_id,
    explain_codedistance_failure,
    expand_codedistance_solver_requests,
    is_codedistance_solver,
    resolve_codedistance_config_id,
    run_codedistance,
)
from qecc_sat.distqldpc_runner import (
    DISTQLDPC_BENCH_CONFIGS,
    DISTQLDPC_SOLVER,
    distqldpc_available,
    distqldpc_install_hint,
    distqldpc_missing_status,
    format_distance_bounds,
    run_distqldpc,
)
from qecc_sat.maxsat_registry import external_maxsat_skip_reason, maxsat_runnable_on_host
from qecc_sat.maxsat_solver import is_external_maxsat_solver, is_maxsat_solver
from qecc_sat.sat_solver import NATIVE_ONLY_CARD_SOLVERS, XOR_SUPPORTED_SOLVERS, SolverType
from qecc_sat.subprocess_utils import isolate_process_session, kill_process_tree
from qecc_sat.qecc_distance import (
    min_distance_quantum_css_split_or_logicals,
    min_distance_quantum_stabilizer_or_logicals,
    symplectic_from_css_nbit_rows,
)

DEFAULT_STEM = "BB_72_12_6"
DEFAULT_MAX_DISTANCE = 6
DEFAULT_BENCHMARK_TIMEOUT_SEC = 180.0  # 3 min per (solver, encoding) config
DEFAULT_ENCODINGS = ["seqcounter", "kmtotalizer"]
# minisatgh is listed by PySAT but often not built (NoSuchSolverError on macOS).
DEFAULT_BENCHMARK_SOLVERS = [
    s.value for s in SolverType if s != SolverType.MINISAT_GH
]


def _default_benchmark_solvers() -> list[str]:
    """Default --solvers list (always includes DistQLDPC reference runs)."""
    names = list(DEFAULT_BENCHMARK_SOLVERS)
    if DISTQLDPC_SOLVER not in names:
        names.append(DISTQLDPC_SOLVER)
    return names

# Grouped for --help / --list-solvers (names are case-insensitive on the CLI).
_SOLVER_GROUPS: tuple[tuple[str, tuple[SolverType, ...]], ...] = (
    (
        "SAT/CDCL (PySAT)",
        (
            SolverType.MINISAT22,
            SolverType.GLUCOSE3,
            SolverType.GLUCOSE4,
            SolverType.GLUCOSE42,
            SolverType.CADICAL103,
            SolverType.CADICAL153,
            SolverType.CADICAL195,
            SolverType.LINGELING,
            SolverType.MAPLESAT,
            SolverType.MERGESAT3,
            SolverType.MINICARD,
            SolverType.GLUECARD3,
            SolverType.GLUECARD4,
            SolverType.CRYPTOSAT,
        ),
    ),
    (
        "SMT (native XOR + cardinality)",
        (SolverType.Z3PY, SolverType.CVC5),
    ),
    (
        "MaxSAT (PySAT RC2)",
        (
            SolverType.RC2_G3,
            SolverType.RC2_G4,
            SolverType.RC2_MINISAT22,
            SolverType.RC2_CADICAL195,
            SolverType.RC2_CRYPTOSAT,
            SolverType.RC2_GLUCOSE42,
        ),
    ),
    (
        "MaxSAT (external; need bin/maxsat install)",
        (
            SolverType.CASHW_COREPLUS,
            SolverType.CASHW_COREPLUS_MSE22,
            SolverType.EVALMAXSAT,
            SolverType.MAXCDCL,
            SolverType.OPEN_WBO,
        ),
    ),
)
# Not a SolverType; use ``--solvers distqldpc`` (needs ``--bench`` install).
_DISTQLDPC_GROUP_TITLE = "Reference (DistQLDPC binary)"
_CODEDISTANCE_GROUP_TITLE = "Reference (codeDistancePYPI; optional pip)"
# In SolverType but omitted from default benchmark runs.
_EXTRA_SOLVER_NAMES = (SolverType.MINISAT_GH.value,)


def _format_solver_names_help() -> str:
    """Compact solver list for argparse ``--solvers`` help."""
    parts: list[str] = []
    for title, members in _SOLVER_GROUPS:
        names = ", ".join(s.value for s in members)
        parts.append(f"{title}: {names}")
    parts.append(f"{_DISTQLDPC_GROUP_TITLE}: {DISTQLDPC_SOLVER}")
    cd_names = ", ".join(codedistance_solver_id(cid) for cid, _, _ in CODEDISTANCE_BENCH_CONFIGS)
    parts.append(f"{_CODEDISTANCE_GROUP_TITLE}: {CODEDISTANCE_SOLVER} or {cd_names}")
    parts.append(
        f"Also defined but not in default benchmark: {', '.join(_EXTRA_SOLVER_NAMES)}"
    )
    parts.append(
        "Names are case-insensitive. External MaxSAT entries are skipped when the "
        "binary is missing on this host (see --list-solvers). Default: all except "
        "minisatgh."
    )
    return " ".join(parts)


def _print_solver_names(*, runnable_external: bool) -> None:
    """Print grouped solver names; mark external binaries missing on this host."""
    print("Solver names for --solvers (case-insensitive):", flush=True)
    for title, members in _SOLVER_GROUPS:
        print(f"\n{title}:", flush=True)
        for st in members:
            note = ""
            if is_external_maxsat_solver(st):
                ok = maxsat_runnable_on_host(st.value)
                if runnable_external:
                    note = "  [installed]" if ok else "  [not installed — skipped in benchmark]"
                elif not ok:
                    note = "  [not installed]"
            print(f"  {st.value}{note}", flush=True)
    print(f"\n{_DISTQLDPC_GROUP_TITLE}:", flush=True)
    dq_note = (
        "  [installed]"
        if distqldpc_available()
        else "  [not installed — run: python3 scripts/download_maxsat_solvers.py --bench]"
    )
    cfg = ", ".join(c for c, _ in DISTQLDPC_BENCH_CONFIGS)
    print(f"  {DISTQLDPC_SOLVER}{dq_note}  (configs: {cfg})", flush=True)
    cd_note = (
        "  [installed]"
        if codedistance_available()
        else "  [not installed — pip install -e \".[comparison]\"]"
    )
    print(f"\n{_CODEDISTANCE_GROUP_TITLE}:", flush=True)
    for cid, method, _extra in CODEDISTANCE_BENCH_CONFIGS:
        print(f"  {codedistance_solver_id(cid)}{cd_note}  ({method}, Z-distance)", flush=True)
    print(f"  {CODEDISTANCE_SOLVER}  (runs all four cd-* above)", flush=True)
    print(f"\nNot in default benchmark: {', '.join(_EXTRA_SOLVER_NAMES)}", flush=True)
    print(
        "\nMaxSAT solvers use one optimization pass (encoding shown as maxsat). "
        f"{DISTQLDPC_SOLVER} runs -no-card and -card-mto per stem; "
        f"codeDistance backends use cd-* / {CODEDISTANCE_SOLVER} (Z-distance via CSScodeDistance); "
        "parses c d_lb / c d_ub from stdout. Others use each --encodings value.",
        flush=True,
    )


ENC_MAP = {
    "seqcounter": EncType.seqcounter,
    "kmtotalizer": EncType.kmtotalizer,
    "mtotalizer": EncType.mtotalizer,
    "totalizer": EncType.totalizer,
}

_CNF_CLAUSE_STAT_KEYS = (
    "clauses_p_nonzero",
    "clauses_weight_def",
    "clauses_cardinality",
    "clauses_dynamic_deficit",
)
_ALL_CLAUSE_STAT_KEYS = (
    "clauses_commutation",
    "clauses_logical",
    *_CNF_CLAUSE_STAT_KEYS,
)


def independent_rows_gf2(rows: list[list[int]]) -> list[list[int]]:
    """Return a row basis with the same GF(2) span, preserving input row representatives."""
    if not rows:
        return []
    n = len(rows[0])
    basis: list[list[int]] = []
    pivots: list[int] = []
    reduced: list[list[int]] = []
    for original in rows:
        row = [int(v) % 2 for v in original]
        if len(row) != n:
            raise ValueError(f"row length {len(row)} != {n}")
        work = row[:]
        for pivot, red in zip(pivots, reduced):
            if work[pivot]:
                work = [(a ^ b) for a, b in zip(work, red)]
        try:
            pivot = next(i for i, value in enumerate(work) if value)
        except StopIteration:
            continue
        for idx, red in enumerate(reduced):
            if red[pivot]:
                reduced[idx] = [(a ^ b) for a, b in zip(red, work)]
        insert_at = 0
        while insert_at < len(pivots) and pivots[insert_at] < pivot:
            insert_at += 1
        pivots.insert(insert_at, pivot)
        reduced.insert(insert_at, work)
        basis.append(row)
    return basis


def reduce_css_logical_basis(
    logical_basis: Optional[list[list[int]]],
    n: int,
) -> Optional[list[list[int]]]:
    """Reduce precomputed CSS logical rows without mixing pure Z and pure X sectors."""
    if logical_basis is None:
        return None
    z_rows: list[list[int]] = []
    x_rows: list[list[int]] = []
    mixed_rows: list[list[int]] = []
    for row in logical_basis:
        if len(row) != 2 * n:
            raise ValueError(f"logical row length {len(row)} != 2n={2 * n}")
        x_part = [int(v) % 2 for v in row[:n]]
        z_part = [int(v) % 2 for v in row[n:]]
        if any(x_part) and any(z_part):
            mixed_rows.append(x_part + z_part)
        elif any(z_part):
            z_rows.append(z_part)
        elif any(x_part):
            x_rows.append(x_part)
    if mixed_rows:
        return independent_rows_gf2(mixed_rows)
    return symplectic_from_css_nbit_rows(
        independent_rows_gf2(z_rows),
        independent_rows_gf2(x_rows),
        n,
    )


def _resolve_clause_count(
    stats: dict[str, Any], solver_type: SolverType
) -> tuple[Optional[int], bool]:
    """
    Return (clause count, is_approximate).

    PySAT CryptoMiniSat does not implement ``nof_clauses()``. For native-XOR solvers,
    fall back to summed CNF-only bookkeeping (excludes native XOR constraints).
    """
    nc = stats.get("nof_clauses")
    if nc is not None:
        return int(nc), False

    if solver_type in XOR_SUPPORTED_SOLVERS:
        keys = _CNF_CLAUSE_STAT_KEYS
        if not any(stats.get(k) is not None for k in keys):
            return None, False
        est = sum(int(stats.get(k) or 0) for k in keys)
        est += 1  # (a1 ∨ … ∨ a_k) at least one ⟨P,Lj⟩ = 1
        return est, True

    if not any(stats.get(k) is not None for k in _ALL_CLAUSE_STAT_KEYS):
        return None, False
    return sum(int(stats.get(k) or 0) for k in _ALL_CLAUSE_STAT_KEYS), True


def estimate_idle_cores(*, sample_sec: float = 0.35) -> tuple[int, int, str]:
    """
    Return ``(idle_count, total_logical_cpus, note)``.

  Uses ``psutil`` when installed (per-CPU utilization). Otherwise estimates from
  ``os.getloadavg()`` on Unix, or falls back to half of ``os.cpu_count()``.
    """
    try:
        import psutil  # type: ignore[import-untyped]

        total = int(psutil.cpu_count(logical=True) or 1)
        per = psutil.cpu_percent(interval=sample_sec, percpu=True)
        if not per:
            busy = float(psutil.cpu_percent(interval=0))
            idle = max(1, int(round(total * (1.0 - busy / 100.0))))
            return idle, total, f"psutil aggregate {100.0 - busy:.0f}% idle"
        idle = sum(1 for u in per if float(u) < 20.0)
        idle = max(1, min(total, idle))
        return idle, total, f"psutil {idle}/{total} cores <20% busy"
    except ImportError:
        pass

    total = int(os.cpu_count() or 1)
    if hasattr(os, "getloadavg"):
        load1 = float(os.getloadavg()[0])
        busy = min(total, max(0, int(load1 + 0.999)))
        idle = max(1, total - busy)
        return idle, total, f"loadavg(1m)={load1:.2f} -> ~{idle}/{total} idle"

    idle = max(1, total // 2)
    return idle, total, f"no psutil/loadavg; assume {idle}/{total} idle"


def choose_parallel_workers(
    jobs_arg: Optional[int],
    *,
    auto_jobs: bool,
) -> tuple[int, str]:
    """Workers for ``ProcessPoolExecutor`` (each job may still use a subprocess timeout)."""
    if jobs_arg is not None:
        w = max(1, int(jobs_arg))
        return w, f"--jobs {w}"
    if auto_jobs:
        idle, total, note = estimate_idle_cores()
        w = max(1, idle // 2)
        return w, f"auto-jobs: {note}; workers={w} (half of idle)"
    return 1, "sequential (use --auto-jobs or --jobs N>1 for parallelism)"


@dataclass(frozen=True)
class _BenchmarkJob:
    solver_name: str
    encoding_key: str
    cardinality_method: str
    display_encoding: str


def _codedistance_job(config_id: str) -> _BenchmarkJob:
    method, _extra = next(
        (m, e) for cid, m, e in CODEDISTANCE_BENCH_CONFIGS if cid == config_id
    )
    return _BenchmarkJob(
        codedistance_solver_id(config_id),
        config_id,
        config_id,
        method,
    )


def _is_serial_benchmark_job(job: _BenchmarkJob) -> bool:
    return job.solver_name == DISTQLDPC_SOLVER or is_codedistance_solver(
        job.solver_name
    )


def _collect_benchmark_jobs(
    solvers_to_test: Iterable[str],
    encodings_to_test: List[str],
) -> list[_BenchmarkJob]:
    jobs: list[_BenchmarkJob] = []
    for sname in solvers_to_test:
        if sname.lower() == DISTQLDPC_SOLVER:
            for config_id, _flags in DISTQLDPC_BENCH_CONFIGS:
                jobs.append(
                    _BenchmarkJob(
                        DISTQLDPC_SOLVER,
                        config_id,
                        config_id,
                        config_id,
                    )
                )
            continue
        cid = resolve_codedistance_config_id(sname)
        if cid is not None:
            jobs.append(_codedistance_job(cid))
            continue
        try:
            st = SolverType(sname.lower())
        except ValueError:
            print(f"# Skip unknown solver: {sname}", file=sys.stderr, flush=True)
            continue
        if is_external_maxsat_solver(st) and not maxsat_runnable_on_host(st.value):
            print(
                f"# Skip {sname}: {external_maxsat_skip_reason(st.value)}",
                file=sys.stderr,
                flush=True,
            )
            continue
        if is_maxsat_solver(st):
            jobs.append(
                _BenchmarkJob(
                    sname.lower(),
                    "seqcounter",
                    "maxsat",
                    "maxsat",
                )
            )
            continue
        for enc_name in encodings_to_test:
            if enc_name == "log":
                jobs.append(
                    _BenchmarkJob(sname.lower(), "seqcounter", "log", "log")
                )
                continue
            if enc_name not in ENC_MAP:
                print(
                    f"# Skip unknown encoding: {enc_name}",
                    file=sys.stderr,
                    flush=True,
                )
                continue
            if st in NATIVE_ONLY_CARD_SOLVERS:
                if enc_name != "seqcounter":
                    continue
                jobs.append(
                    _BenchmarkJob(
                        sname.lower(), enc_name, "standard", "native"
                    )
                )
            else:
                jobs.append(
                    _BenchmarkJob(
                        sname.lower(), enc_name, "standard", enc_name
                    )
                )
    return jobs


def _css_split_card_label(
    css_split_cardinality: str,
    *,
    enable_stopping_closure: bool,
    enable_dynamic_deficit: bool,
) -> str:
    label = f"css-{css_split_cardinality}"
    if enable_stopping_closure and enable_dynamic_deficit:
        return f"{label}+tanner"
    if enable_stopping_closure:
        return f"{label}+closure"
    if enable_dynamic_deficit:
        return f"{label}+deficit"
    return label


def _distqldpc_cli_flags(config_id: str) -> tuple[str, ...]:
    for cid, flags in DISTQLDPC_BENCH_CONFIGS:
        if cid == config_id:
            return flags
    raise ValueError(f"Unknown DistQLDPC config {config_id!r}")


def _run_distqldpc_job(
    stem: str,
    matrix_dir: Path,
    timeout_sec: Optional[float],
    config_id: str,
) -> dict:
    result = {
        "solver": DISTQLDPC_SOLVER,
        "cardinality": config_id,
        "encoding": config_id,
        "ok": False,
        "time_sec": None,
        "result": None,
        "vars": None,
        "clauses": None,
        "clauses_approx": False,
        "error": None,
        "d_lb": None,
        "d_ub": None,
    }
    try:
        dq = run_distqldpc(
            stem,
            matrix_dir,
            cpu_lim_sec=timeout_sec,
            capture_stats=True,
            cli_flags=_distqldpc_cli_flags(config_id),
        )
        result["time_sec"] = round(dq.elapsed_sec, 3)
        if dq.nof_vars is not None:
            result["vars"] = dq.nof_vars
        if dq.nof_clauses is not None:
            result["clauses"] = dq.nof_clauses
            result["clauses_approx"] = dq.clauses_approx
        if not dq.proved:
            result["d_lb"] = dq.d_lb
            result["d_ub"] = dq.d_ub
        formatted = dq.format_result()
        if formatted is not None:
            result["result"] = formatted
        if dq.proved:
            result["ok"] = True
        elif dq.timed_out or (timeout_sec and dq.elapsed_sec >= float(timeout_sec) * 0.95):
            result["error"] = "timeout"
        elif formatted is not None:
            result["error"] = "bounds"
        else:
            result["error"] = f"exit {dq.returncode}"[:60]
    except FileNotFoundError as e:
        result["error"] = distqldpc_missing_status()
        if str(e).strip():
            print(f"# {e}", file=sys.stderr, flush=True)
    except Exception as e:
        result["error"] = str(e).replace("\n", " ")[:60]
    return result


def _run_codedistance_job(
    hx: list[list[int]],
    hz: list[list[int]],
    timeout_sec: Optional[float],
    config_id: str,
) -> dict:
    method, extra = next(
        (m, e) for cid, m, e in CODEDISTANCE_BENCH_CONFIGS if cid == config_id
    )
    sid = codedistance_solver_id(config_id)
    result: dict = {
        "solver": sid,
        "cardinality": config_id,
        "encoding": method,
        "ok": False,
        "time_sec": None,
        "result": None,
        "vars": None,
        "clauses": None,
        "clauses_approx": False,
        "error": None,
        "d_lb": None,
        "d_ub": None,
    }
    if not codedistance_available():
        result["error"] = codedistance_missing_status()
        return result
    pre = codedistance_prerequisite(config_id)
    if pre is not None:
        result["error"] = pre[0]
        print(f"# {pre[1]}", file=sys.stderr, flush=True)
        return result
    try:
        cd = run_codedistance(
            hx,
            hz,
            method=method,
            extra_params=extra,
            timeout_sec=timeout_sec,
            component="Z",
        )
        result["time_sec"] = round(cd.elapsed_sec, 3)
        formatted = cd.format_result()
        if formatted is not None:
            result["result"] = formatted
        if cd.ok:
            result["ok"] = True
        elif cd.error:
            status, detail = explain_codedistance_failure(config_id, cd.error)
            result["error"] = status[:60]
            print(f"# {detail}", file=sys.stderr, flush=True)
        elif timeout_sec and cd.elapsed_sec >= float(timeout_sec) * 0.95:
            result["error"] = "timeout"
        else:
            result["error"] = "no distance"
    except ImportError:
        result["error"] = codedistance_missing_status()
    except Exception as e:
        status, detail = explain_codedistance_failure(config_id, str(e))
        result["error"] = status[:60]
        print(f"# {detail}", file=sys.stderr, flush=True)
    return result


def _execute_benchmark_job(
    s: list[list[int]],
    hx: Optional[list[list[int]]],
    hz: Optional[list[list[int]]],
    n: int,
    max_distance: int,
    job: _BenchmarkJob,
    timeout_sec: Optional[float],
    logical_basis_override: Optional[list[list[int]]],
    use_solve_limited_interrupt: bool,
    use_css_split: bool,
    css_split_cardinality: str,
    enable_stopping_closure: bool,
    enable_dynamic_deficit: bool,
    dynamic_block_limit: int,
    *,
    stem: str,
    matrix_dir: Path,
) -> dict:
    if job.solver_name == DISTQLDPC_SOLVER:
        r = _run_distqldpc_job(stem, matrix_dir, timeout_sec, job.encoding_key)
        return r
    if is_codedistance_solver(job.solver_name):
        cid = resolve_codedistance_config_id(job.solver_name)
        if cid is None:
            raise ValueError(f"Unknown codeDistance config for {job.solver_name!r}")
        if hx is None or hz is None:
            raise ValueError("codeDistance jobs require Hx and Hz matrices")
        return _run_codedistance_job(hx, hz, timeout_sec, cid)
    st = SolverType(job.solver_name)
    enc = ENC_MAP.get(job.encoding_key)
    r = run_one(
        s,
        n,
        max_distance,
        st,
        enc,
        timeout_sec,
        hx=hx,
        hz=hz,
        cardinality_method=job.cardinality_method,
        logical_basis_override=logical_basis_override,
        use_solve_limited_interrupt=use_solve_limited_interrupt,
        use_css_split=use_css_split,
        css_split_cardinality=css_split_cardinality,
        enable_stopping_closure=enable_stopping_closure,
        enable_dynamic_deficit=enable_dynamic_deficit,
        dynamic_block_limit=dynamic_block_limit,
    )
    r["encoding"] = job.display_encoding
    return r


def _default_max_distance(stem: str) -> int:
    """Literature ``d`` for known BB stems; else ``DEFAULT_MAX_DISTANCE``."""
    spec_d = LITERATURE_BB_DISTANCES.get(stem)
    if spec_d is not None:
        return int(spec_d)
    return DEFAULT_MAX_DISTANCE


def _resolve_stem_targets(args: argparse.Namespace) -> list[tuple[str, Path, int]]:
    """
    Build the list of ``(stem, matrix_dir, max_distance)`` to benchmark.

    Priority: ``--quick`` > ``--stems-dir`` > ``--stems`` > single ``--stem``.
    """
    if args.quick:
        return [("SC_9_1_3", Path(args.benchmark_dir), 3)]

    pairs: list[tuple[str, Path]] = []
    if args.stems_dir is not None:
        d = Path(args.stems_dir)
        if not d.is_dir():
            raise SystemExit(f"--stems-dir is not a directory: {d}")
        suffix = "_Hx.txt"
        found = sorted(
            {
                p.name[: -len(suffix)]
                for p in d.glob(f"*{suffix}")
                if (d / f"{p.name[: -len(suffix)]}_Hz.txt").is_file()
            }
        )
        if not found:
            raise SystemExit(
                f"No matching *_Hx.txt + *_Hz.txt pairs in {d}"
            )
        pairs = [(name, d) for name in found]
    elif args.stems:
        md = Path(args.benchmark_dir)
        pairs = [(s, md) for s in args.stems]
    else:
        pairs = [(args.stem, Path(args.benchmark_dir))]

    targets: list[tuple[str, Path, int]] = []
    seen: set[str] = set()
    for stem, mdir in pairs:
        if stem in seen:
            continue
        seen.add(stem)
        d_val = (
            args.max_distance
            if args.max_distance is not None
            else _default_max_distance(stem)
        )
        targets.append((stem, mdir, d_val))
    return targets


def _latest_scan_progress(progress_q: Queue) -> Optional[dict[str, Any]]:
    latest: Optional[dict[str, Any]] = None
    while True:
        try:
            latest = progress_q.get_nowait()
        except Empty:
            break
    return latest


def _format_partial_distance(partial: Optional[dict[str, Any]]) -> Optional[str]:
    """Format best distance known when a run stops early (timeout)."""
    if not partial:
        return None
    return format_distance_bounds(
        witness=partial.get("witness_d"),
        lb=partial.get("scan_lb"),
    )


def _benchmark_worker(
    q: Queue,
    progress_q: Queue,
    s: list[list[int]],
    hx: Optional[list[list[int]]],
    hz: Optional[list[list[int]]],
    solver_name: str,
    encoding_name: str,
    max_distance: int,
    cardinality_method: str,
    logical_basis_override: Optional[list[list[int]]],
    use_solve_limited_interrupt: bool,
    use_css_split: bool,
    css_split_cardinality: str,
    enable_stopping_closure: bool,
    enable_dynamic_deficit: bool,
    dynamic_block_limit: int,
    timeout_sec: Optional[float] = None,
) -> None:
    """Subprocess worker: one (solver, encoding, cardinality) distance run."""
    isolate_process_session()
    if use_solve_limited_interrupt:
        os.environ["QEECC_SAT_SOLVE_LIMITED_INTERRUPT"] = "1"
    try:
        solver_type = SolverType(solver_name)
        encoding = ENC_MAP.get(encoding_name, EncType.seqcounter)
        stats: dict[str, Any] = {}
        t0 = time.perf_counter()
        if use_css_split:
            if hx is None or hz is None:
                raise ValueError("--css-split requires Hx/Hz matrices")
            d = min_distance_quantum_css_split_or_logicals(
                hx,
                hz,
                solver_type=solver_type,
                max_distance=max_distance,
                encoding=encoding,
                stats=stats,
                sector_cardinality=css_split_cardinality,
                parallel_css_sectors=False,
                logical_basis_override=logical_basis_override,
                enable_stopping_closure=enable_stopping_closure,
                enable_dynamic_deficit=enable_dynamic_deficit,
                dynamic_block_limit=dynamic_block_limit,
            )
        else:
            d = min_distance_quantum_stabilizer_or_logicals(
                s,
                solver_type=solver_type,
                max_distance=max_distance,
                encoding=encoding,
                stats=stats,
                cardinality_encoding="log" if cardinality_method == "log" else "standard",
                logical_basis_override=logical_basis_override,
                progress_q=progress_q,
                timeout_sec=timeout_sec,
            )
        elapsed = time.perf_counter() - t0
        nclauses, clauses_approx = _resolve_clause_count(stats, solver_type)
        q.put(
            (
                "ok",
                d,
                elapsed,
                stats.get("nof_vars"),
                nclauses,
                clauses_approx,
            )
        )
    except Exception as e:
        q.put(("err", str(e)[:80]))


def _run_in_subprocess_with_timeout(
    s: list[list[int]],
    hx: Optional[list[list[int]]],
    hz: Optional[list[list[int]]],
    solver_name: str,
    encoding_name: str,
    max_distance: int,
    cardinality_method: str,
    timeout_sec: float,
    logical_basis_override: Optional[list[list[int]]],
    use_solve_limited_interrupt: bool,
    use_css_split: bool,
    css_split_cardinality: str,
    enable_stopping_closure: bool,
    enable_dynamic_deficit: bool,
    dynamic_block_limit: int,
) -> tuple[
    Optional[int],
    Optional[float],
    Optional[str],
    Optional[int],
    Optional[int],
    bool,
    Optional[dict[str, Any]],
]:
    """
    Wall-clock timeout via subprocess terminate/kill.

    SIGALRM cannot interrupt blocking PySAT/CryptoSAT solve(); this does.
    The worker calls ``setsid()`` so external MaxSAT children share its
    process group and are killed with ``kill_process_tree``.
    """
    q: Queue = Queue()
    progress_q: Queue = Queue()
    p = Process(
        target=_benchmark_worker,
        args=(
            q,
            progress_q,
            s,
            hx,
            hz,
            solver_name,
            encoding_name,
            max_distance,
            cardinality_method,
            logical_basis_override,
            use_solve_limited_interrupt,
            use_css_split,
            css_split_cardinality,
            enable_stopping_closure,
            enable_dynamic_deficit,
            dynamic_block_limit,
            timeout_sec,
        ),
    )
    p.start()
    deadline = time.monotonic() + float(timeout_sec)
    stashed: Optional[tuple[Any, ...]] = None
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        p.join(timeout=min(0.25, remaining))
        while True:
            try:
                stashed = q.get_nowait()
            except Empty:
                break
        if not p.is_alive():
            break
    if p.is_alive():
        kill_process_tree(p.pid)
        p.join(timeout=2)
        partial = _latest_scan_progress(progress_q)
        return None, None, "timeout", None, None, False, partial
    p.join()
    while True:
        try:
            stashed = q.get_nowait()
        except Empty:
            break
    if stashed is None:
        return None, None, "no result", None, None, False, None
    if stashed[0] == "ok":
        approx = bool(stashed[5]) if len(stashed) > 5 else False
        return stashed[1], stashed[2], None, stashed[3], stashed[4], approx, None
    return None, None, stashed[1], None, None, False, None


def load_matrix_css(
    stem: str,
    matrix_dir: Path,
    *,
    reduce_dependent_rows: bool = False,
) -> tuple[
    list[list[int]],
    list[list[int]],
    list[list[int]],
    int,
    Optional[list[list[int]]],
    dict[str, tuple[int, int]],
]:
    """Load Hx/Hz, build S, return matrices, logicals, and optional row-reduction stats."""
    hx_path = matrix_dir / f"{stem}_Hx.txt"
    hz_path = matrix_dir / f"{stem}_Hz.txt"
    if not hx_path.is_file():
        raise FileNotFoundError(f"Missing {hx_path}")
    if not hz_path.is_file():
        raise FileNotFoundError(f"Missing {hz_path}")
    hx = load_matrix(str(hx_path))
    hz = load_matrix(str(hz_path))
    n = len(hx[0])
    if len(hz[0]) != n:
        raise ValueError(f"Hx cols {n} != Hz cols {len(hz[0])}")
    logical, _, err = resolve_precomputed_logical_basis(str(hx_path), n)
    if err == "missing":
        logical = None
    elif err == "incomplete":
        raise SystemExit(
            f"Incomplete precompute for {stem!r} in {matrix_dir} "
            f"(only one of Gx/Gz present). Run: precompute-logicals {stem}"
        )
    reduction_stats: dict[str, tuple[int, int]] = {}
    if reduce_dependent_rows:
        hx_before, hz_before = len(hx), len(hz)
        hx = independent_rows_gf2(hx)
        hz = independent_rows_gf2(hz)
        reduction_stats["Hx"] = (hx_before, len(hx))
        reduction_stats["Hz"] = (hz_before, len(hz))
        if logical is not None:
            logical_before = len(logical)
            logical = reduce_css_logical_basis(logical, n)
            reduction_stats["Gx/Gz"] = (
                logical_before,
                len(logical) if logical is not None else 0,
            )
    s = build_s_from_hx_hz(hx, hz)
    return s, hx, hz, n, logical, reduction_stats


def run_one(
    s: list[list[int]],
    n: int,
    max_distance: int,
    solver_type: SolverType,
    encoding: Optional[EncType],
    timeout_sec: Optional[float],
    *,
    hx: Optional[list[list[int]]] = None,
    hz: Optional[list[list[int]]] = None,
    cardinality_method: str = "standard",
    logical_basis_override: Optional[list[list[int]]] = None,
    use_solve_limited_interrupt: bool = False,
    use_css_split: bool = False,
    css_split_cardinality: str = "stepwise",
    enable_stopping_closure: bool = False,
    enable_dynamic_deficit: bool = False,
    dynamic_block_limit: int = 5000,
) -> dict:
    """Run min_distance for one (solver, encoding, cardinality method)."""
    if is_maxsat_solver(solver_type):
        card_label = "maxsat"
        encoding_name = "seqcounter"
    elif use_css_split:
        card_label = _css_split_card_label(
            css_split_cardinality,
            enable_stopping_closure=enable_stopping_closure,
            enable_dynamic_deficit=enable_dynamic_deficit,
        )
        encoding_name = next((k for k, v in ENC_MAP.items() if v == encoding), "seqcounter")
    elif cardinality_method == "log":
        card_label = "log"
        encoding_name = "seqcounter"
    elif encoding:
        use_native_card = solver_type in NATIVE_ONLY_CARD_SOLVERS
        encoding_name = next((k for k, v in ENC_MAP.items() if v == encoding), "?")
        card_label = "native" if use_native_card else encoding_name
    else:
        encoding_name = "seqcounter"
        card_label = encoding_name

    display_cardinality = card_label if use_css_split else cardinality_method
    result = {
        "solver": solver_type.value,
        "cardinality": display_cardinality,
        "encoding": card_label,
        "ok": False,
        "time_sec": None,
        "result": None,
        "vars": None,
        "clauses": None,
        "clauses_approx": False,
        "error": None,
    }

    try:
        if timeout_sec is not None and timeout_sec > 0:
            res, elapsed, err, nvars, nclauses, clauses_approx, partial = (
                _run_in_subprocess_with_timeout(
                    s,
                    hx,
                    hz,
                    solver_type.value,
                    encoding_name,
                    max_distance,
                    cardinality_method,
                    float(timeout_sec),
                    logical_basis_override,
                    use_solve_limited_interrupt,
                    use_css_split,
                    css_split_cardinality,
                    enable_stopping_closure,
                    enable_dynamic_deficit,
                    dynamic_block_limit,
                )
            )
            if err == "timeout":
                result["error"] = "timeout"
                result["time_sec"] = round(float(timeout_sec), 3)
                partial_res = _format_partial_distance(partial)
                if partial_res is not None:
                    result["result"] = partial_res
                if partial:
                    pv = partial.get("nof_vars")
                    pc = partial.get("nof_clauses")
                    if pv is not None:
                        result["vars"] = pv
                    if pc is not None:
                        result["clauses"] = pc
                        _, result["clauses_approx"] = _resolve_clause_count(
                            {"nof_clauses": pc}, solver_type
                        )
                return result
            if err:
                result["error"] = err[:60]
                return result
        else:
            stats: dict = {}
            t0 = time.perf_counter()
            if use_css_split:
                if hx is None or hz is None:
                    raise ValueError("--css-split requires Hx/Hz matrices")
                res = min_distance_quantum_css_split_or_logicals(
                    hx,
                    hz,
                    max_distance=max_distance,
                    solver_type=solver_type,
                    stats=stats,
                    encoding=ENC_MAP.get(encoding_name, EncType.seqcounter),
                    sector_cardinality=css_split_cardinality,
                    parallel_css_sectors=False,
                    logical_basis_override=logical_basis_override,
                    enable_stopping_closure=enable_stopping_closure,
                    enable_dynamic_deficit=enable_dynamic_deficit,
                    dynamic_block_limit=dynamic_block_limit,
                )
            else:
                res = min_distance_quantum_stabilizer_or_logicals(
                    s,
                    max_distance=max_distance,
                    solver_type=solver_type,
                    stats=stats,
                    encoding=ENC_MAP.get(encoding_name, EncType.seqcounter),
                    cardinality_encoding="log" if cardinality_method == "log" else "standard",
                    logical_basis_override=logical_basis_override,
                )
            elapsed = time.perf_counter() - t0
            nvars = stats.get("nof_vars")
            nclauses, clauses_approx = _resolve_clause_count(stats, solver_type)

        result["ok"] = True
        result["time_sec"] = round(elapsed, 3)
        result["result"] = res
        result["vars"] = nvars
        result["clauses"] = nclauses
        result["clauses_approx"] = clauses_approx
    except Exception as e:
        result["error"] = str(e).replace("\n", " ").strip()
    return result


def _run_one_stem_benchmark(
    *,
    args: argparse.Namespace,
    label: str,
    s: list[list[int]],
    hx: Optional[list[list[int]]],
    hz: Optional[list[list[int]]],
    n: int,
    logical_override: Optional[list[list[int]]],
    max_distance: int,
    timeout: float,
    workers: int,
    jobs: List["_BenchmarkJob"],
    enable_stopping_closure: bool,
    enable_dynamic_deficit: bool,
    stem: str,
    matrix_dir: Path,
) -> list[dict]:
    """Run the benchmark for a single stem: header → rows → summary."""
    print(f"Benchmark: {label}", flush=True)
    print(f"max_distance={max_distance}, timeout={timeout}s per config", flush=True)
    if args.css_split:
        pruning_parts = []
        if enable_stopping_closure:
            pruning_parts.append("stopping-closure")
        if enable_dynamic_deficit:
            pruning_parts.append(f"dynamic-deficit limit={args.dynamic_block_limit}")
        pruning_note = (
            f" with Tanner {' + '.join(pruning_parts)}" if pruning_parts else ""
        )
        print(
            f"# CSS split path enabled{pruning_note}; "
            f"sector_cardinality={args.css_split_cardinality}",
            flush=True,
        )
    print("=" * 100, flush=True)
    print(
        "# Clauses ~N: CNF-only estimate (weight/cardinality/OR); native XOR not counted "
        "(CryptoMiniSat has no nof_clauses).",
        flush=True,
    )
    print(
        "# Result: exact d if proved; on timeout, best progress (witness d or ≥lb from UNSAT scan); "
        f"{DISTQLDPC_SOLVER} uses the same Result format (exact d, or ≥lb / ≤ub / [lb,ub]); "
        "'-' if no progress.",
        flush=True,
    )
    print(
        f"{'Solver':<14} {'Strategy':<20} {'Time(s)':<10} "
        f"{'Vars':<8} {'Clauses':<10} {'Result':<8} {'Status'}",
        flush=True,
    )
    print("-" * 100, flush=True)

    use_css_for = lambda job: args.css_split and job.cardinality_method != "maxsat"
    by_job = _run_jobs_fixed_timeout(
        s=s,
        hx=hx,
        hz=hz,
        n=n,
        max_distance=max_distance,
        jobs=jobs,
        timeout=timeout,
        logical_override=logical_override,
        use_solve_limited_interrupt=args.solve_limited_interrupt,
        use_css_split=args.css_split,
        css_split_cardinality=args.css_split_cardinality,
        enable_stopping_closure=enable_stopping_closure,
        enable_dynamic_deficit=enable_dynamic_deficit,
        dynamic_block_limit=args.dynamic_block_limit,
        workers=workers,
        use_css_for=use_css_for,
        stem=stem,
        matrix_dir=matrix_dir,
        print_rows=True,
    )
    results = [by_job[_job_key_from_job(job)] for job in jobs]

    ok_count = sum(1 for r in results if r["ok"])
    print("-" * 100, flush=True)
    print(f"Completed: {ok_count}/{len(results)}", flush=True)
    if ok_count > 0:
        best = min(
            (r for r in results if r["ok"]),
            key=lambda x: x["time_sec"] or float("inf"),
        )
        print(
            f"Fastest:  {best['solver']} ({_result_strategy(best)}) "
            f"in {best['time_sec']:.3f}s",
            flush=True,
        )
    return results


def _job_key_from_job(job: _BenchmarkJob) -> tuple[str, str, str]:
    return (job.solver_name, job.cardinality_method, job.display_encoding)


def _run_jobs_fixed_timeout(
    *,
    s: list[list[int]],
    hx: Optional[list[list[int]]],
    hz: Optional[list[list[int]]],
    n: int,
    max_distance: int,
    jobs: List["_BenchmarkJob"],
    timeout: float,
    logical_override: Optional[list[list[int]]],
    use_solve_limited_interrupt: bool,
    use_css_split: bool,
    css_split_cardinality: str,
    enable_stopping_closure: bool,
    enable_dynamic_deficit: bool,
    dynamic_block_limit: int,
    workers: int,
    use_css_for,
    stem: str,
    matrix_dir: Path,
    print_rows: bool = True,
) -> dict[tuple[str, str, str], dict]:
    by_job: dict[tuple[str, str, str], dict] = {}
    if workers <= 1 or len(jobs) <= 1:
        for job in jobs:
            r = _execute_benchmark_job(
                s,
                hx,
                hz,
                n,
                max_distance,
                job,
                timeout,
                logical_override,
                use_solve_limited_interrupt,
                use_css_for(job),
                css_split_cardinality,
                enable_stopping_closure,
                enable_dynamic_deficit,
                dynamic_block_limit,
                stem=stem,
                matrix_dir=matrix_dir,
            )
            by_job[_job_key_from_job(job)] = r
            if print_rows:
                _print_result_row(r)
    else:
        serial_jobs = [j for j in jobs if _is_serial_benchmark_job(j)]
        pool_jobs = [j for j in jobs if not _is_serial_benchmark_job(j)]
        for job in serial_jobs:
            r = _execute_benchmark_job(
                s,
                hx,
                hz,
                n,
                max_distance,
                job,
                timeout,
                logical_override,
                use_solve_limited_interrupt,
                use_css_for(job),
                css_split_cardinality,
                enable_stopping_closure,
                enable_dynamic_deficit,
                dynamic_block_limit,
                stem=stem,
                matrix_dir=matrix_dir,
            )
            by_job[_job_key_from_job(job)] = r
            if print_rows:
                _print_result_row(r)
        if not pool_jobs:
            return by_job
        n_workers = min(workers, len(pool_jobs))
        with ProcessPoolExecutor(max_workers=n_workers) as pool:
            futures = {
                pool.submit(
                    _execute_benchmark_job,
                    s,
                    hx,
                    hz,
                    n,
                    max_distance,
                    job,
                    timeout,
                    logical_override,
                    use_solve_limited_interrupt,
                    use_css_for(job),
                    css_split_cardinality,
                    enable_stopping_closure,
                    enable_dynamic_deficit,
                    dynamic_block_limit,
                    stem=stem,
                    matrix_dir=matrix_dir,
                ): job
                for job in pool_jobs
            }
            for fut in as_completed(futures):
                job = futures[fut]
                try:
                    r = fut.result()
                except Exception as e:
                    r = {
                        "solver": job.solver_name,
                        "cardinality": job.cardinality_method,
                        "encoding": job.display_encoding,
                        "ok": False,
                        "time_sec": None,
                        "result": None,
                        "vars": None,
                        "clauses": None,
                        "clauses_approx": False,
                        "error": str(e).replace("\n", " ")[:60],
                    }
                by_job[_job_key_from_job(job)] = r
                if print_rows:
                    _print_result_row(r)
    return by_job


def _result_strategy(r: dict) -> str:
    """Single table label from internal cardinality + encoding fields."""
    card = r.get("cardinality") or ""
    enc = r.get("encoding") or ""
    if card == enc:
        return enc or card
    if card == "standard":
        return enc
    if enc == "standard":
        return card
    if card.startswith("css-"):
        return card
    return enc or card


def _print_result_row(r: dict) -> None:
    time_str = f"{r['time_sec']:.3f}" if r["time_sec"] is not None else "-"
    vars_str = str(r["vars"]) if r["vars"] is not None else "-"
    if r["clauses"] is not None:
        clauses_str = f"~{r['clauses']}" if r.get("clauses_approx") else str(r["clauses"])
    else:
        clauses_str = "-"
    res_str = str(r["result"]) if r["result"] is not None else "-"
    status = "OK" if r["ok"] else (r.get("error") or "?")
    print(
        f"{r['solver']:<14} {_result_strategy(r):<20} {time_str:<10} "
        f"{vars_str:<8} {clauses_str:<10} {res_str:<8} {status}",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=f"Benchmark SAT solvers (default: {DEFAULT_STEM} from data/matrices)"
    )
    parser.add_argument(
        "--stem",
        default=DEFAULT_STEM,
        metavar="STEM",
        help=f"Code stem for {{STEM}}_Hx.txt / _Hz.txt (default: {DEFAULT_STEM})",
    )
    parser.add_argument(
        "--stems",
        nargs="+",
        default=None,
        metavar="STEM",
        help="Run benchmark for multiple stems (loaded from --benchmark-dir); "
        "overrides --stem.",
    )
    parser.add_argument(
        "--stems-dir",
        type=Path,
        default=None,
        metavar="DIR",
        help="Run benchmark for every {STEM}_Hx.txt with matching _Hz.txt in DIR. "
        "DIR is also used as the matrix dir for those runs.",
    )
    parser.add_argument(
        "--benchmark-dir",
        type=Path,
        default=DEFAULT_MATRIX_DIR,
        metavar="DIR",
        help="Directory with parity-check matrices (default: data/matrices)",
    )
    parser.add_argument(
        "-d",
        "--d",
        "--max-distance",
        dest="max_distance",
        type=int,
        default=None,
        metavar="D",
        help="Scan weights 1..D. Default: literature d for known BB stems, "
        f"else {DEFAULT_MAX_DISTANCE}.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        metavar="SEC",
        help=f"Per-config wall-clock timeout in seconds (default: {int(DEFAULT_BENCHMARK_TIMEOUT_SEC)} = 3 min).",
    )
    parser.add_argument(
        "--solvers",
        nargs="*",
        default=None,
        metavar="NAME",
        help=_format_solver_names_help(),
    )
    parser.add_argument(
        "--list-solvers",
        action="store_true",
        help="Print all --solvers names (with external MaxSAT install status) and exit",
    )
    parser.add_argument(
        "--encodings",
        nargs="*",
        default=None,
        help="Encodings: seqcounter, kmtotalizer, mtotalizer, totalizer, log "
        f"(default: {','.join(DEFAULT_ENCODINGS)})",
    )
    parser.add_argument(
        "--cardinality-methods",
        nargs="*",
        default=None,
        choices=["standard", "log"],
        metavar="METHOD",
        help="Deprecated: use --encodings log. If set, adds extra runs beyond --encodings.",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Quick run: stem=BB_36_8_3 (QT_36_8_3), max-distance=3, timeout<=30s",
    )
    parser.add_argument(
        "--reduce-dependent-rows",
        action="store_true",
        help="Remove linearly dependent rows from Hx/Hz and precomputed Gx/Gz over GF(2)",
    )
    parser.add_argument(
        "--solve-limited-interrupt",
        action="store_true",
        help="Set QEECC_SAT_SOLVE_LIMITED_INTERRUPT=1 for PySAT backends",
    )
    parser.add_argument(
        "--css-split",
        action="store_true",
        help="Use CSS sector split SAT path for non-MaxSAT solvers (requires Hx/Hz matrices)",
    )
    parser.add_argument(
        "--css-split-cardinality",
        choices=["stepwise", "linear", "refine"],
        default="stepwise",
        help="CSS split sector strategy: stepwise ITotalizer by default; linear rebuilds per k",
    )
    parser.add_argument(
        "--tanner-pruning",
        action="store_true",
        help="Enable both --stopping-closure and --dynamic-deficit on CSS split paths",
    )
    parser.add_argument(
        "--stopping-closure",
        action="store_true",
        help="Enable static Tanner stopping-set closure clauses on CSS split paths",
    )
    parser.add_argument(
        "--dynamic-deficit",
        action="store_true",
        help="Enable dynamic Tanner deficit blocking clauses on CSS split paths",
    )
    parser.add_argument(
        "--dynamic-block-limit",
        type=int,
        default=5000,
        metavar="N",
        help="Maximum dynamic Tanner blocking clauses per bound round (default 5000)",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=None,
        metavar="N",
        help="Run up to N configs in parallel (default: auto from idle CPUs). "
        "Use --jobs 1 for sequential.",
    )
    parser.add_argument(
        "--auto-jobs",
        action="store_true",
        default=True,
        help="Pick workers ≈ half of idle logical CPUs (default on)",
    )
    parser.add_argument(
        "--no-auto-jobs",
        action="store_false",
        dest="auto_jobs",
        help="Do not auto-detect parallelism (sequential unless --jobs N>1)",
    )
    args = parser.parse_args()

    if args.list_solvers:
        _print_solver_names(runnable_external=True)
        return

    if args.solve_limited_interrupt:
        os.environ["QEECC_SAT_SOLVE_LIMITED_INTERRUPT"] = "1"
        print(
            "# QEECC_SAT_SOLVE_LIMITED_INTERRUPT=1",
            flush=True,
        )
    enable_stopping_closure = bool(args.tanner_pruning or args.stopping_closure)
    enable_dynamic_deficit = bool(args.tanner_pruning or args.dynamic_deficit)
    if (enable_stopping_closure or enable_dynamic_deficit) and not args.css_split:
        args.css_split = True
        print("# Tanner pruning options imply --css-split", flush=True)
    if (
        (enable_stopping_closure or enable_dynamic_deficit)
        and args.css_split_cardinality == "refine"
    ):
        raise SystemExit("--tanner-pruning supports --css-split-cardinality stepwise/linear, not refine")

    if args.quick:
        timeout = 30.0 if args.timeout is None else min(args.timeout, 30.0)
    else:
        timeout = (
            args.timeout
            if args.timeout is not None
            else DEFAULT_BENCHMARK_TIMEOUT_SEC
        )

    solvers_to_test = expand_codedistance_solver_requests(
        list(args.solvers or _default_benchmark_solvers())
    )
    if DISTQLDPC_SOLVER in solvers_to_test and not distqldpc_available():
        print(f"# Warning: {DISTQLDPC_SOLVER} listed but binary missing.", flush=True)
        print(f"# {distqldpc_install_hint()}", file=sys.stderr, flush=True)
    if (
        any(is_codedistance_solver(s) for s in solvers_to_test)
        and not codedistance_available(import_check=True)
    ):
        print(
            "# Warning: codeDistance comparison solver(s) listed but package missing.",
            flush=True,
        )
        print(f"# {codedistance_pip_install_hint()}", file=sys.stderr, flush=True)
    encodings_to_test = list(
        dict.fromkeys(args.encodings or DEFAULT_ENCODINGS)
    )
    if args.cardinality_methods:
        for m in args.cardinality_methods:
            if m == "log" and "log" not in encodings_to_test:
                encodings_to_test.append("log")
    if args.css_split and "log" in encodings_to_test:
        encodings_to_test = [e for e in encodings_to_test if e != "log"]
        print("# Skip --encodings log: CSS split Tanner pruning uses sector cardinality", flush=True)

    workers, workers_note = choose_parallel_workers(
        args.jobs, auto_jobs=args.auto_jobs
    )
    idle_hint = ""
    if args.auto_jobs and args.jobs is None:
        idle, total, _ = estimate_idle_cores()
        idle_hint = f" ({idle} idle / {total} logical CPUs)"
    jobs = _collect_benchmark_jobs(solvers_to_test, encodings_to_test)
    print(
        f"# Parallel: {workers} worker(s){idle_hint} — {workers_note}; "
        f"{len(jobs)} configuration(s) per stem",
        flush=True,
    )
    print(
        f"# Timeout: {timeout}s per config (subprocess terminate/kill at wall-clock limit; "
        "SIGALRM cannot stop blocking SAT solve).",
        flush=True,
    )

    targets = _resolve_stem_targets(args)
    if not targets:
        raise SystemExit("No stems resolved to run")

    summaries: list[tuple[str, int, int, Optional[float], Optional[str]]] = []
    for idx, (stem, matrix_dir, max_distance) in enumerate(targets):
        if idx > 0:
            print(flush=True)
        try:
            s_mat, hx, hz, n, logical_override, reduction_stats = load_matrix_css(
                stem,
                matrix_dir,
                reduce_dependent_rows=args.reduce_dependent_rows,
            )
        except FileNotFoundError as exc:
            print(f"# Skip {stem}: {exc}", flush=True)
            summaries.append((stem, 0, 0, None, None))
            continue
        label = (
            f"{stem}  (n={n}, Hx {len(hx)}x{n}, Hz {len(hz)}x{n})  "
            f"matrices: {matrix_dir / (stem + '_Hx.txt')}"
        )
        if reduction_stats:
            parts = [
                f"{name} {before}->{after}"
                for name, (before, after) in reduction_stats.items()
            ]
            print("# Reduced dependent rows: " + ", ".join(parts), flush=True)
        if logical_override is None:
            print(
                "# Note: no precomputed Gx/Gz; log/OR path uses on-the-fly logical basis.",
                flush=True,
            )
        else:
            print(
                f"# Precomputed logicals: {len(logical_override)} operators",
                flush=True,
            )

        results = _run_one_stem_benchmark(
            args=args,
            label=label,
            s=s_mat,
            hx=hx,
            hz=hz,
            n=n,
            logical_override=logical_override,
            max_distance=max_distance,
            timeout=timeout,
            workers=workers,
            jobs=jobs,
            enable_stopping_closure=enable_stopping_closure,
            enable_dynamic_deficit=enable_dynamic_deficit,
            stem=stem,
            matrix_dir=matrix_dir,
        )
        ok_count = sum(1 for r in results if r["ok"])
        best_time: Optional[float] = None
        best_label: Optional[str] = None
        if ok_count > 0:
            best = min(
                (r for r in results if r["ok"]),
                key=lambda x: x["time_sec"] or float("inf"),
            )
            best_time = best["time_sec"]
            best_label = f"{best['solver']} ({_result_strategy(best)})"
        summaries.append((stem, ok_count, len(results), best_time, best_label))

    if len(targets) > 1:
        print(flush=True)
        print("=" * 100, flush=True)
        print(f"# Multi-stem summary: {len(targets)} stems", flush=True)
        print(
            f"{'Stem':<24} {'OK/Total':<10} {'Best(s)':<10} {'Best config'}",
            flush=True,
        )
        for stem, ok, total, t, lbl in summaries:
            t_str = "-" if t is None else f"{t:.3f}"
            ok_total = f"{ok}/{total}"
            print(
                f"{stem:<24} {ok_total:<10} {t_str:<10} {lbl or '-'}",
                flush=True,
            )


if __name__ == "__main__":
    main()
