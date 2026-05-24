from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

try:
    from pysat.card import CardEnc, EncType, ITotalizer
except ImportError:
    CardEnc = None
    EncType = None
    ITotalizer = None

from ..sat_solver import (
    get_solver,
    SolverType,
    NATIVE_ONLY_CARD_SOLVERS,
    XOR_SUPPORTED_SOLVERS,
    tseitin_xor_clause_count,
)
from .build_distance_constraints import *
from .compute_logical_basis import *
from .compute_distance_from_bottom import _min_distance_css_sector_or_logicals, _min_distance_css_sector_stepwise
from .compute_distance_from_top import _min_distance_css_sector_card_refine

def split_css_stabilizers(
    S: List[List[Union[int, float]]], n: int
) -> Optional[Tuple[List[List[int]], List[List[int]]]]:
    """
    If every row of S is purely X-type (Z-block zero) or purely Z-type (X-block zero),
    return (Hx, Hz) as list-of-rows over n bits. Otherwise return None (not a CSS row layout).
    """
    Hx: List[List[int]] = []
    Hz: List[List[int]] = []
    for row in S:
        if len(row) < 2 * n:
            return None
        rx = [int(row[i]) % 2 for i in range(n)]
        rz = [int(row[n + i]) % 2 for i in range(n)]
        x_zero = all(v == 0 for v in rx)
        z_zero = all(v == 0 for v in rz)
        if z_zero and any(rx):
            Hx.append(rx)
        elif x_zero and any(rz):
            Hz.append(rz)
        elif x_zero and z_zero:
            continue
        else:
            return None
    return Hx, Hz


def _logicals_pure_z_only(
    logical_basis: List[List[int]], n: int
) -> List[List[int]]:
    """Symplectic vectors with no X component (indices n..2n-1 all zero)."""
    return [L for L in logical_basis if all(L[n + j] % 2 == 0 for j in range(n))]


def _logicals_pure_x_only(
    logical_basis: List[List[int]], n: int
) -> List[List[int]]:
    """Symplectic vectors with no Z component (indices 0..n-1 all zero)."""
    return [L for L in logical_basis if all(L[j] % 2 == 0 for j in range(n))]


def _binary_matrix_equal(
    left: List[List[Union[int, float]]],
    right: List[List[Union[int, float]]],
) -> bool:
    """Return True when two parity-check matrices are identical over F_2."""
    if len(left) != len(right):
        return False
    left_bits = [[int(v) % 2 for v in row] for row in left]
    right_bits = [[int(v) % 2 for v in row] for row in right]
    return left_bits == right_bits


def _publish_css_split_formula_stats(stats: Dict[str, Any]) -> None:
    """Expose representative per-sector formula stats at the top level."""
    sector_stats = [
        value
        for key, value in stats.items()
        if key.startswith("css_") and key.endswith("_stats") and isinstance(value, dict)
    ]
    vars_seen = [
        int(value["nof_vars"])
        for value in sector_stats
        if value.get("nof_vars") is not None
    ]
    clauses_seen = [
        int(value["nof_clauses"])
        for value in sector_stats
        if value.get("nof_clauses") is not None
    ]
    if vars_seen:
        stats["nof_vars"] = max(vars_seen)
        stats["css_sector_nof_vars_max"] = max(vars_seen)
    if clauses_seen:
        stats["nof_clauses"] = max(clauses_seen)
        stats["css_sector_nof_clauses_max"] = max(clauses_seen)

    for clause_key in (
        "clauses_commutation",
        "clauses_p_nonzero",
        "clauses_logical",
        "clauses_weight_def",
        "clauses_cardinality",
        "clauses_dynamic_deficit",
    ):
        values = [
            int(value[clause_key])
            for value in sector_stats
            if value.get(clause_key) is not None
        ]
        if values:
            stats[clause_key] = max(values)


def min_distance_quantum_css_split_or_logicals(
    Hx: List[List[Union[int, float]]],
    Hz: List[List[Union[int, float]]],
    solver_type: SolverType = SolverType.GLUCOSE3,
    max_distance: Optional[int] = None,
    *,
    debug: bool = False,
    show_formula: bool = False,
    stats: Optional[Dict[str, int]] = None,
    encoding: Any = None,
    sector_cardinality: str = "stepwise",
    parallel_css_sectors: bool = True,
    per_sector_k_records: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    setup_timing_out: Optional[Dict[str, float]] = None,
    logical_basis_override: Optional[List[List[int]]] = None,
    on_css_refine_row: Optional[Callable[[Dict[str, Any]], None]] = None,
    enable_stopping_closure: bool = False,
    enable_dynamic_deficit: bool = False,
    dynamic_block_limit: int = 5000,
) -> Optional[int]:
    """
    CSS-only fast path: d = min(d_Z, d_X) via two smaller SAT problems.

    - Z sector: variables z_1..z_n (SAT vars 1..n), commutation Hx @ z = 0, logicals with
      only Z part (symplectic X block zero), cardinality on Hamming weight of z.
    - X sector: variables x_1..x_n, commutation Hz @ x = 0, logicals with only X part,
      cardinality on x.

    ``sector_cardinality``:
      - ``"linear"``: fresh SAT + CardEnc.atmost per k each sector.
      - ``"stepwise"``: ITotalizer + assumptions per sector when available; else linear.
      - ``"refine"``: witness refinement (Σv≤U−1) per sector, like full ``card_refine``.

    ``parallel_css_sectors``: if True (default), run the Z-sector and X-sector SAT branches
    concurrently when both have pure logicals (separate solver instances; wall time ~max of the two).
    Per-sector refine/stepwise detail dicts are not merged into ``stats`` in parallel mode; set False
    for sequential runs with full ``stats`` or if a backend is not thread-safe.

    If ``per_sector_k_records`` is a dict (e.g. ``{"z": [], "x": []}``), each sector run appends
    per-``k`` (or per-refinement-step) rows: ``linear`` and ``stepwise`` use the same keys as
    ``_min_distance_css_sector_or_logicals`` / ``_min_distance_css_sector_stepwise``; ``refine`` uses
    one row per SAT call (like ``min_distance_quantum_stabilizer_card_refine``).

    Full stabilizer matrix S = [Hx|0] over [0|Hz] is built only to compute logical_basis_symplectic,
    then filtered. If Hx or Hz is empty or a sector has no pure logicals, that sector is skipped.

    If ``logical_basis_override`` is set (rows of length ``2n``), skip building ``S`` and
    ``logical_basis_symplectic``; use the given symplectic rows (must match the same ``S``).

    If ``on_css_refine_row`` is set and ``sector_cardinality=="refine"``, called after each
    sector SAT round with the same row dict appended to ``per_sector_k_records``.

    Tanner pruning can be enabled for ``linear`` and ``stepwise`` sector scans with
    ``enable_stopping_closure`` and ``enable_dynamic_deficit``. It preserves the
    existing sector bit variables (SAT vars 1..n).
    """
    if CardEnc is None or EncType is None:
        raise ImportError("pysat.card (CardEnc) is required")
    if encoding is None:
        encoding = EncType.seqcounter

    if not Hx and not Hz:
        return None
    n = len(Hx[0]) if Hx else len(Hz[0]) if Hz else 0
    if n == 0:
        return None
    if max_distance is None:
        max_distance = n

    if logical_basis_override is not None:
        logical_basis = [[int(x) % 2 for x in row] for row in logical_basis_override]
        for row in logical_basis:
            if len(row) != 2 * n:
                raise ValueError(
                    f"logical_basis_override rows must have length 2n={2 * n}, got {len(row)}"
                )
        if setup_timing_out is not None:
            setup_timing_out["logical_basis_symplectic_sec"] = 0.0
    else:
        S = [list(row) + [0] * n for row in Hx] + [[0] * n + list(row) for row in Hz]
        if setup_timing_out is not None:
            _t_lb = time.perf_counter()
        logical_basis = logical_basis_symplectic(S, n)
        if setup_timing_out is not None:
            setup_timing_out["logical_basis_symplectic_sec"] = time.perf_counter() - _t_lb
    if not logical_basis:
        return None

    lz = _logicals_pure_z_only(logical_basis, n)
    lx = _logicals_pure_x_only(logical_basis, n)

    sc = sector_cardinality.lower()
    if sc not in ("linear", "stepwise", "refine"):
        raise ValueError(
            f"sector_cardinality must be 'linear', 'stepwise', or 'refine', got {sector_cardinality!r}"
        )

    use_stepwise = sc == "stepwise" and ITotalizer is not None

    def _sector_distance(
        H_p: List[List[Union[int, float]]],
        log_subset: List[List[int]],
        sector: str,
    ) -> Optional[int]:
        if not log_subset:
            return None
        if sc == "linear":
            pk = None
            if per_sector_k_records is not None:
                pk = per_sector_k_records.setdefault(sector, [])
            return _min_distance_css_sector_or_logicals(
                H_p, log_subset, n, sector, solver_type, max_distance, encoding,
                debug=debug, show_formula=show_formula, stats=None,
                per_k_records=pk,
                enable_stopping_closure=enable_stopping_closure,
                enable_dynamic_deficit=enable_dynamic_deficit,
                dynamic_block_limit=dynamic_block_limit,
            )
        if sc == "refine":
            st: Dict[str, int] = {}
            pk_rf = None
            if per_sector_k_records is not None:
                pk_rf = per_sector_k_records.setdefault(sector, [])
            d_rf = _min_distance_css_sector_card_refine(
                H_p, log_subset, n, sector, solver_type, max_distance, encoding,
                debug=debug, stats=st if stats is not None else None,
                per_k_records=pk_rf,
                on_refine_row=on_css_refine_row,
            )
            if stats is not None:
                stats[f"css_{sector}_refine_stats"] = st
            return d_rf
        if use_stepwise:
            st_sw: Dict[str, int] = {}
            pk_sw = None
            if per_sector_k_records is not None:
                pk_sw = per_sector_k_records.setdefault(sector, [])
            d_sw = _min_distance_css_sector_stepwise(
                H_p, log_subset, n, sector, solver_type, max_distance,
                debug=debug, stats=st_sw if stats is not None else None,
                per_k_records=pk_sw,
                enable_stopping_closure=enable_stopping_closure,
                enable_dynamic_deficit=enable_dynamic_deficit,
                dynamic_block_limit=dynamic_block_limit,
            )
            if stats is not None:
                stats[f"css_{sector}_stepwise_stats"] = st_sw
            return d_sw
        pk_fb = None
        if per_sector_k_records is not None:
            pk_fb = per_sector_k_records.setdefault(sector, [])
        return _min_distance_css_sector_or_logicals(
            H_p, log_subset, n, sector, solver_type, max_distance, encoding,
            debug=debug, show_formula=show_formula, stats=None,
            per_k_records=pk_fb,
            enable_stopping_closure=enable_stopping_closure,
            enable_dynamic_deficit=enable_dynamic_deficit,
            dynamic_block_limit=dynamic_block_limit,
        )

    same_xz_checks = bool(Hx and Hz and _binary_matrix_equal(Hx, Hz))
    dz = _sector_distance(Hx, lz, "z")
    dx = dz if same_xz_checks else _sector_distance(Hz, lx, "x")

    if stats is not None:
        stats["css_d_Z"] = dz
        stats["css_d_X"] = dx
        stats["css_split_reused_symmetric_sector"] = same_xz_checks
        stats["css_num_z_logicals"] = len(lz)
        stats["css_num_x_logicals"] = len(lx)
        if sc == "refine":
            stats["css_split_cardinality"] = "refine"
        elif sc == "linear":
            stats["css_split_cardinality"] = "linear"
        else:
            stats["css_split_cardinality"] = "stepwise" if use_stepwise else "linear"
        _publish_css_split_formula_stats(stats)

    candidates = [d for d in (dz, dx) if d is not None]
    if not candidates:
        return None
    return min(candidates)

