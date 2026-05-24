"""
Run external MaxSAT binaries (WCNF on disk, parse ``o`` / ``v`` lines).
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

_COMINISATPS_OPTIMAL_RE = re.compile(r"optimal:\s*(\d+)", re.IGNORECASE)

from pysat.formula import WCNF

from .maxsat_registry import (
    MaxSATBinarySpec,
    MaxSATPlatformError,
    assert_runnable,
    ensure_executable,
    get_spec,
    maxsat_runnable_on_host,
    platform_mismatch_message,
    resolve_executable,
)
from .maxsat_solver import WCNFBuilder
from .subprocess_utils import run_subprocess_captured


def parse_o_v_lines(stdout: str) -> Tuple[Optional[int], Optional[List[int]]]:
    """
    Parse competition-style output: ``o <cost>`` and ``v <lits...>``.
    """
    cost: Optional[int] = None
    model: Optional[List[int]] = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("o "):
            try:
                cost = int(line.split()[1])
            except (IndexError, ValueError):
                pass
        elif line.startswith("v "):
            tail = line[2:].strip()
            if tail and tail.split()[0] == "0":
                continue
            if tail and set(tail) <= {"0", "1"}:
                model = [
                    (idx + 1) if bit == "1" else -(idx + 1)
                    for idx, bit in enumerate(tail)
                ]
                continue
            lits: List[int] = []
            for tok in tail.split():
                if tok in ("0", ""):
                    continue
                lits.append(int(tok))
            if lits:
                model = lits
    return cost, model


def parse_cominisatps_optimal(stdout: str) -> Tuple[Optional[int], Optional[List[int]]]:
    """
    Parse COMiniSatPS / glucose_release stats (``c ... optimal: <cost>, maxsat: ...``).
    """
    cost: Optional[int] = None
    for line in stdout.splitlines():
        if "optimal:" not in line:
            continue
        m = _COMINISATPS_OPTIMAL_RE.search(line)
        if m:
            cost = int(m.group(1))
            break
    return cost, None


def build_command(
    spec: MaxSATBinarySpec,
    exe: Path,
    wcnf_path: Path,
    *,
    out_path: Optional[Path] = None,
) -> List[str]:
    def _map(tok: str) -> str:
        if tok == "{exe}":
            return str(exe)
        if tok == "{wcnf}":
            return str(wcnf_path)
        if tok == "{out}":
            if out_path is None:
                raise ValueError(f"Solver {spec.solver_type} requires {{out}} path")
            return str(out_path)
        return tok

    return [_map(tok) for tok in spec.command]


def run_external_maxsat(
    builder: WCNFBuilder,
    solver_type: str,
    *,
    timeout_sec: Optional[float] = None,
    work_dir: Optional[Path] = None,
    keep_wcnf: bool = False,
) -> Tuple[Optional[int], Optional[List[int]], str]:
    """
    Write WCNF, invoke external solver, return ``(cost, model, stdout)``.
    """
    spec = get_spec(solver_type)
    if not maxsat_runnable_on_host(solver_type):
        raise MaxSATPlatformError("solver not available on this host")
    exe = resolve_executable(solver_type)
    ensure_executable(exe)
    assert_runnable(exe)

    wcnf_text = _builder_to_dimacs(builder)

    needs_out = "{out}" in spec.command
    if work_dir is not None:
        work_dir.mkdir(parents=True, exist_ok=True)
        wcnf_path = work_dir / "instance.wcnf"
        wcnf_path.write_text(wcnf_text, encoding="utf-8")
        cleanup = not keep_wcnf
        out_path = (work_dir / "result.out") if needs_out else None
        cleanup_out = False
    else:
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".wcnf",
            delete=False,
            encoding="utf-8",
        )
        tmp.write(wcnf_text)
        tmp.close()
        wcnf_path = Path(tmp.name)
        cleanup = not keep_wcnf
        if needs_out:
            out_tmp = tempfile.NamedTemporaryFile(
                suffix=".out",
                delete=False,
            )
            out_tmp.close()
            out_path = Path(out_tmp.name)
            cleanup_out = True
        else:
            out_path = None
            cleanup_out = False

    cmd = build_command(spec, exe, wcnf_path, out_path=out_path)
    proc_returncode = 0
    try:
        try:
            stdout, stderr, proc_returncode = run_subprocess_captured(
                cmd,
                cwd=str(exe.parent),
                timeout_sec=timeout_sec,
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(
                f"MaxSAT solver {solver_type} timed out after {timeout_sec}s."
            ) from e
        except OSError as e:
            if getattr(e, "errno", None) == 8:  # ENOEXEC / Exec format error
                hint = platform_mismatch_message(exe)
                raise MaxSATPlatformError(
                    hint or "solver not available on this host"
                ) from e
            raise
    finally:
        if cleanup:
            wcnf_path.unlink(missing_ok=True)
        if cleanup_out and out_path is not None:
            out_path.unlink(missing_ok=True)

    combined = stdout + ("\n" + stderr if stderr else "")

    if spec.output_format == "cominisatps_optimal":
        cost, model = parse_cominisatps_optimal(combined)
        if cost is not None:
            return cost, model, combined
        raise RuntimeError(
            f"MaxSAT solver {solver_type} did not report optimal cost.\n"
            f"Command: {' '.join(cmd)}\n"
            f"Output tail:\n{combined[-2000:]}"
        )

    if proc_returncode != 0 and "o " not in stdout:
        raise RuntimeError(
            f"MaxSAT solver {solver_type} exited {proc_returncode}.\n"
            f"Command: {' '.join(cmd)}\n"
            f"Output tail:\n{combined[-2000:]}"
        )

    if spec.output_format == "o_v_lines":
        return (*parse_o_v_lines(combined), combined)
    if spec.output_format == "result_file":
        if out_path is None or not out_path.is_file():
            cost, model = parse_o_v_lines(combined)
            if cost is not None and model is not None:
                return cost, model, combined
            raise RuntimeError(
                f"MaxSAT solver {solver_type} did not write result file {out_path!r}.\n"
                f"Command: {' '.join(cmd)}\n"
                f"Output tail:\n{combined[-2000:]}"
            )
        file_text = out_path.read_text(encoding="utf-8", errors="replace")
        if proc_returncode != 0 and "o " not in file_text:
            raise RuntimeError(
                f"MaxSAT solver {solver_type} exited {proc_returncode}.\n"
                f"Command: {' '.join(cmd)}\n"
                f"Output tail:\n{combined[-2000:]}"
            )
        return (*parse_o_v_lines(file_text), combined)
    raise ValueError(f"Unsupported output_format {spec.output_format!r}")


def wcnf_to_dimacs(wcnf: WCNF) -> str:
    """
    DIMACS WCNF for competition binaries (Open-WBO, CASHW).

    PySAT's ``to_dimacs()`` uses ``h`` lines; Open-WBO expects a ``p wcnf`` header and
    hard clauses weighted with ``topw``.
    """
    nhard = len(wcnf.hard)
    nsoft = len(wcnf.soft)
    if nhard + nsoft == 0:
        return f"p wcnf {wcnf.nv} 0 1\n"
    topw = wcnf.topw
    if hasattr(topw, "is_finite") and not topw.is_finite():  # type: ignore[union-attr]
        topw = sum(int(w) for w in wcnf.wght) + 1
    else:
        topw = int(topw)
        if topw <= 0:
            topw = sum(int(w) for w in wcnf.wght) + 1
    lines = [f"p wcnf {wcnf.nv} {nhard + nsoft} {topw}"]
    for cl in wcnf.hard:
        lits = " ".join(str(lit) for lit in cl)
        lines.append(f"{topw} {lits} 0")
    for cl, w in zip(wcnf.soft, wcnf.wght):
        lits = " ".join(str(lit) for lit in cl)
        lines.append(f"{int(w)} {lits} 0")
    return "\n".join(lines) + "\n"


def _builder_to_dimacs(builder: WCNFBuilder) -> str:
    return wcnf_to_dimacs(builder.wcnf)
