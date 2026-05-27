from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

try:
    from pysat.card import CardEnc, EncType, ITotalizer
except ImportError:
    CardEnc = None
    EncType = None
    ITotalizer = None

from ..log_encoding import add_log_atmost_k
from ..sat_solver import (
    get_solver,
    SolverType,
    CARD_SUPPORTED_SOLVERS,
    NATIVE_ONLY_CARD_SOLVERS,
    XOR_SUPPORTED_SOLVERS,
    tseitin_xor_clause_count,
)
from .prune_with_tanner_graph import (
    dynamic_deficit_blocking,
    inject_stopping_set_closure,
    tanner_neighbors,
)

def _solver_formula_stats(solver: Any) -> Tuple[Optional[int], Optional[int]]:
    """
    Return (nof_vars, nof_clauses) from the underlying SAT backend.
    Some backends (e.g. CryptoMiniSat via PySAT) return unusable values before the first
    ``solve()``; prefer calling this **after** ``solve()`` when recording stats.
    CryptoMiniSat may raise if ``nof_clauses()`` is unsupported — catch and return partials.
    """
    candidates = [solver, getattr(solver, "solver", None)]
    for obj in candidates:
        if obj is None:
            continue
        nv: Optional[int] = None
        nc: Optional[int] = None
        try:
            raw_v = obj.nof_vars()
            if raw_v is not None:
                nv = int(raw_v)
        except Exception:
            pass
        try:
            raw_c = obj.nof_clauses()
            if raw_c is not None:
                nc = int(raw_c)
        except Exception:
            pass
        if nv is not None or nc is not None:
            return nv, nc
    return None, None


def _append_per_k_row(
    per_k_records: Optional[List[Dict[str, Any]]], row: Dict[str, Any]
) -> None:
    if per_k_records is not None:
        per_k_records.append(row)


def _emit_scan_progress(
    progress_q: Optional[Any],
    *,
    completed_k: int,
    sat: bool,
    run_lb: int,
    nof_vars: Optional[int] = None,
    nof_clauses: Optional[int] = None,
) -> None:
    """Report SAT-scan progress (for benchmarks / timeout partial results)."""
    if progress_q is None:
        return
    try:
        progress_q.put(
            {
                "completed_k": completed_k,
                "witness_d": completed_k if sat else None,
                "scan_lb": completed_k if sat else run_lb,
                "nof_vars": nof_vars,
                "nof_clauses": nof_clauses,
            }
        )
    except Exception:
        pass


def _bounds_str_scan_lb_ub(lb: int, ub: Optional[int]) -> str:
    """Linear / stepwise scan: ``[lb,ub]``; unknown upper bound prints ``∞``."""
    if ub is None:
        return f"[{lb},∞]"
    return f"[{lb},{ub}]"


def _bounds_str_refine_card(
    ok: bool,
    wgt: int,
    bound: int,
    *,
    exact_if_unsat: Optional[int] = None,
) -> str:
    """One cardinality-bounded SAT check (refine / cap); optional exact distance on UNSAT."""
    if ok:
        return _bounds_str_scan_lb_ub(1, wgt)
    if exact_if_unsat is not None:
        return _bounds_str_scan_lb_ub(exact_if_unsat, exact_if_unsat)
    return f"[{bound + 1},∞]"


def _add_xor_clause(
    solver: Any,
    lits: List[int],
    *,
    value: bool = False,
    next_var_ref: Optional[List[int]] = None,
) -> None:
    """Add XOR; pass ``next_var_ref`` so Tseitin auxiliaries do not collide with CardEnc."""
    try:
        solver.add_xor_clause(lits, value=value, next_var_ref=next_var_ref)
    except TypeError:
        solver.add_xor_clause(lits, value=value)


def _matrix_shape(H: List[List[Any]]) -> tuple:
    """Return (nrows, ncols). Accept list of lists or list of tuples."""
    if not H:
        return 0, 0
    return len(H), len(H[0]) if H[0] is not None else 0


def _lit_to_name(lit: int, n: int, w_start: int) -> str:
    """Convert literal to human-readable name for formula display."""
    var = abs(lit)
    neg = "¬" if lit < 0 else ""
    if 1 <= var <= n:
        return f"{neg}x{var}"
    if n + 1 <= var <= 2 * n:
        return f"{neg}z{var - n}"
    if w_start <= var <= w_start + n - 1:
        return f"{neg}w{var - w_start + 1}"
    return f"{neg}v{var}"

def _minmax_before_deadline(deadline: Optional[float]) -> bool:
    return deadline is None or time.monotonic() < deadline


def _minmax_scan_cap(n: int, max_distance: Optional[int]) -> int:
    """Hamming / Pauli-weight scan cap: ``min(n, max_distance)`` with ``None`` → ``n``."""
    if max_distance is None:
        return n
    md = int(max_distance)
    if md < 1:
        md = 1
    return min(n, md)


def _minmax_append_row(
    rows_out: Optional[List[Dict[str, Any]]],
    row_k: int,
    sat: bool,
    solve_sec: float,
    refine_ctx: str,
    nv: Optional[int],
    nc: Optional[int],
) -> None:
    if rows_out is None:
        return
    rows_out.append(
        {
            "k": row_k,
            "sat": sat,
            "time_base_sec": None,
            "time_cardenc_sec": None,
            "build_time_sec": None,
            "time_sec": solve_sec,
            "nof_vars": nv,
            "nof_clauses": nc,
            "clauses_commutation": None,
            "clauses_p_nonzero": None,
            "clauses_logical": None,
            "clauses_weight_def": None,
            "clauses_cardinality": None,
            "refine_ctx": refine_ctx,
        }
    )


def _add_weight_atmost_k(
    solver: Any,
    w_lits: List[int],
    k: int,
    solver_type: SolverType,
    encoding: Any,
    top_id: int,
    next_id_ref: List[int],
    *,
    cardinality_encoding: str = "standard",
) -> int:
    """Add Σ w_i ≤ k. Returns clause count added (0 for native atmost)."""
    if k >= len(w_lits):
        return 0
    if cardinality_encoding in ("binary", "log"):
        ncl, _aux = add_log_atmost_k(solver, w_lits, k, next_id_ref)
        return ncl
    if solver_type in NATIVE_ONLY_CARD_SOLVERS:
        solver.add_atmost(w_lits, k)
        return 0
    card_top = next_id_ref[0] if next_id_ref else top_id
    card = CardEnc.atmost(
        lits=w_lits, bound=k, top_id=card_top, encoding=encoding
    )
    solver.add_clauses(card.clauses)
    if next_id_ref is not None and card.clauses:
        hi = max(abs(lit) for cl in card.clauses for lit in cl)
        next_id_ref[0] = max(next_id_ref[0], hi)
    return len(card.clauses)


def _stabilizer_or_logicals_solve_atmost_k(
    S: List[List[Union[int, float]]],
    logical_basis: List[List[int]],
    n: int,
    m: int,
    k: int,
    solver_type: SolverType,
    encoding: Any,
    *,
    w_start: int,
    a_start: int,
    top_id: int,
    cardinality_encoding: str = "standard",
    rows_out: Optional[List[Dict[str, Any]]] = None,
    row_k: int = 0,
    refine_ctx: str = "",
) -> Tuple[bool, int]:
    """
    One SAT call: OR-logicals + Σ w_i ≤ k. Returns (sat, Pauli_weight from w bits if sat else 0).
    If ``rows_out`` is set, appends one detail row (same keys as card_refine) with ``row_k`` / ``refine_ctx``.
    """
    n_vars_xz = 2 * n

    def _xor_clause_count(lits: List[int], value: bool) -> int:
        if solver_type in XOR_SUPPORTED_SOLVERS:
            return 1
        return tseitin_xor_clause_count(lits, value)

    solver = get_solver(solver_type=solver_type)
    for j in range(m):
        lits = []
        for i in range(n):
            if S[j][i] % 2 == 1:
                lits.append(n + 1 + i)
            if S[j][n + i] % 2 == 1:
                lits.append(1 + i)
        if not lits:
            continue
        if len(lits) == 1:
            solver.add_clause([-lits[0]])
            continue
        solver.add_xor_clause(lits, value=False)
    solver.add_clause(list(range(1, n_vars_xz + 1)))
    for idx, L in enumerate(logical_basis):
        lits_L = [i + 1 for i in range(n) if L[n + i] % 2 == 1]
        lits_L += [n + 1 + i for i in range(n) if L[i] % 2 == 1]
        a_j = a_start + idx
        if lits_L:
            solver.add_xor_clause(lits_L + [a_j], value=False)
        else:
            solver.add_clause([-a_j])
    solver.add_clause(list(range(a_start, a_start + len(logical_basis))))
    for i in range(n):
        xi, zi, wi = 1 + i, n + 1 + i, w_start + i
        solver.add_clause([-wi, xi, zi])
        solver.add_clause([-xi, wi])
        solver.add_clause([-zi, wi])
    w_lits = list(range(w_start, w_start + n))
    next_id_ref = [top_id]
    _add_weight_atmost_k(
        solver,
        w_lits,
        k,
        solver_type,
        encoding,
        top_id,
        next_id_ref,
        cardinality_encoding=cardinality_encoding,
    )
    nv, nc = _solver_formula_stats(solver)
    t_sv = time.perf_counter()
    ok = bool(solver.solve())
    solve_sec = time.perf_counter() - t_sv
    wgt = 0
    if ok:
        model = set(solver.get_model() or [])
        wgt = sum(1 for i in range(n) if (w_start + i) in model)
    _minmax_append_row(rows_out, row_k, ok, solve_sec, refine_ctx, nv, nc)
    solver.delete()
    return ok, wgt


def _css_sector_solve_atmost_k(
    H_parity: List[List[Union[int, float]]],
    logical_subset: List[List[int]],
    n: int,
    sector: str,
    k: int,
    solver_type: SolverType,
    encoding: Any,
    *,
    a_start: int,
    top_id: int,
    rows_out: Optional[List[Dict[str, Any]]] = None,
    row_k: int = 0,
    refine_ctx: str = "",
    enable_stopping_closure: bool = False,
    enable_dynamic_deficit: bool = False,
    dynamic_block_limit: int = 5000,
) -> Tuple[bool, int]:
    """Sector OR-logicals + Hamming weight ≤ k on bits 1..n.

    When ``k >= n``, the cardinality constraint is vacuous; no at-most encoding is
    added so the CNF matches the first ``no_card`` solve in
    ``_min_distance_css_sector_card_refine`` for CARD-native solvers.
    """
    m = len(H_parity)
    k_log = len(logical_subset)

    def _xor_clause_count(lits: List[int], value: bool) -> int:
        if solver_type in XOR_SUPPORTED_SOLVERS:
            return 1
        return tseitin_xor_clause_count(lits, value)

    solver = get_solver(solver_type=solver_type)
    check_to_bits, bit_to_checks = tanner_neighbors(H_parity)
    for j in range(m):
        lits = [i + 1 for i in range(n) if int(H_parity[j][i]) % 2 == 1]
        if not lits:
            continue
        if len(lits) == 1:
            solver.add_clause([-lits[0]])
            continue
        solver.add_xor_clause(lits, value=False)
    if enable_stopping_closure:
        # These parity-implied clauses expose singleton checks directly to unit
        # propagation, shortening low-weight UNSAT proofs without changing the
        # existing bit variable numbering.
        inject_stopping_set_closure(solver, check_to_bits, lambda i: i + 1)
    solver.add_clause(list(range(1, n + 1)))
    for idx, L in enumerate(logical_subset):
        if sector == "z":
            lits_L = [i + 1 for i in range(n) if L[i] % 2 == 1]
        else:
            lits_L = [i + 1 for i in range(n) if L[n + i] % 2 == 1]
        a_j = a_start + idx
        if lits_L:
            solver.add_xor_clause(lits_L + [a_j], value=False)
        else:
            solver.add_clause([-a_j])
    solver.add_clause(list(range(a_start, a_start + k_log)))
    bit_lits = list(range(1, n + 1))
    if k < n:
        if solver_type in NATIVE_ONLY_CARD_SOLVERS:
            solver.add_atmost(bit_lits, k)
        else:
            card = CardEnc.atmost(
                lits=bit_lits, bound=k, top_id=top_id, encoding=encoding
            )
            solver.add_clauses(card.clauses)
    if enable_dynamic_deficit:
        dynamic_deficit_blocking(
            solver,
            k + 1,
            check_to_bits,
            bit_to_checks,
            lambda i: i + 1,
            limit=dynamic_block_limit,
        )
    nv, nc = _solver_formula_stats(solver)
    t_sv = time.perf_counter()
    ok = bool(solver.solve())
    solve_sec = time.perf_counter() - t_sv
    wgt = 0
    if ok:
        model = set(solver.get_model() or [])
        wgt = sum(1 for i in range(n) if (i + 1) in model)
    _minmax_append_row(rows_out, row_k, ok, solve_sec, refine_ctx, nv, nc)
    solver.delete()
    return ok, wgt

def _lit_to_name_blocking(lit: int, n: int, w_start: int, a_start: int, n_logicals: int) -> str:
    """Convert literal to name for blocking formula: x_i, z_i, w_i, a_j."""
    var = abs(lit)
    neg = "¬" if lit < 0 else ""
    if 1 <= var <= n:
        return f"{neg}x{var}"
    if n + 1 <= var <= 2 * n:
        return f"{neg}z{var - n}"
    if w_start <= var <= w_start + n - 1:
        return f"{neg}w{var - w_start + 1}"
    if a_start <= var <= a_start + n_logicals - 1:
        return f"{neg}a{var - a_start + 1}"
    return f"{neg}v{var}"


__all__ = [
    "_add_weight_atmost_k",
    "_add_xor_clause",
    "_append_per_k_row",
    "_bounds_str_refine_card",
    "_bounds_str_scan_lb_ub",
    "_css_sector_solve_atmost_k",
    "_emit_scan_progress",
    "_lit_to_name",
    "_lit_to_name_blocking",
    "_matrix_shape",
    "_minmax_append_row",
    "_minmax_before_deadline",
    "_minmax_scan_cap",
    "_solver_formula_stats",
    "_stabilizer_or_logicals_solve_atmost_k",
]

