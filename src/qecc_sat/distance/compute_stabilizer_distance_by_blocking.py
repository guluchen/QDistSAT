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
    CARD_SUPPORTED_SOLVERS,
    NATIVE_ONLY_CARD_SOLVERS,
    XOR_SUPPORTED_SOLVERS,
    tseitin_xor_clause_count,
)
from .build_distance_constraints import *
from .compute_logical_basis import *

def min_distance_quantum_stabilizer_blocking(
    S: List[List[Union[int, float]]],
    solver_type: SolverType = SolverType.GLUCOSE3,
    max_distance: Optional[int] = None,
    *,
    debug: bool = False,
    stats: Optional[Dict[str, int]] = None,
    show_block_clauses: bool = False,
    per_k_records: Optional[List[Dict[str, Any]]] = None,
    setup_timing_out: Optional[Dict[str, float]] = None,
    logical_basis_override: Optional[List[List[int]]] = None,
) -> Optional[int]:
    """
    Compute min distance via blocking strategy (no CardEnc):
    1. Solve without weight constraint → get P in N(S)\\S, use its weight as initial min
    2. Add block clause, solve again (incremental)
    3. If new solution weight > min: block w_i for first w qubits in support (error-weight vars)
    4. If new solution weight <= min: update min, add full block clause
    5. Repeat until UNSAT → return min weight

    If ``per_k_records`` is set, appends one row per ``solve()`` call (column ``k`` = round
    index 1..r; ``time_base_sec`` only on round 1 — initial CNF build). No cardinality clauses
    (``clauses_cardinality`` = 0).
    """
    m, cols = _matrix_shape(S)
    if m == 0 or cols % 2 != 0:
        return None
    n = cols // 2
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
        if setup_timing_out is not None:
            _t_lb = time.perf_counter()
        logical_basis = logical_basis_symplectic(S, n)
        if setup_timing_out is not None:
            setup_timing_out["logical_basis_symplectic_sec"] = time.perf_counter() - _t_lb
    if not logical_basis:
        return None

    n_vars_xz = 2 * n
    w_start = n_vars_xz + 1
    a_start = w_start + n
    n_logicals = len(logical_basis)

    if show_block_clauses:
        print("\n--- Variable roles (blocking formula) ---")
        print("  x_i (var 1..n):      X part of Pauli on qubit i")
        print("  z_i (var n+1..2n):   Z part of Pauli on qubit i")
        print("  w_i (var 2n+1..3n):  error weight on qubit i, w_i = x_i ∨ z_i")
        print("  a_j:                 ⟨P,Lj⟩=1 for logical j (OR of logicals)")
        print("--- Block clauses ---\n")

    def _xor_clause_count(lits: List[int], value: bool) -> int:
        if solver_type in XOR_SUPPORTED_SOLVERS:
            return 1
        return tseitin_xor_clause_count(lits, value)

    t_build_start = time.perf_counter()
    c_comm, c_p0, c_log, c_wdef = 0, 0, 0, 0
    solver = get_solver(solver_type=solver_type)

    # Commutation: P in S⊥
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
            c_comm += 1
            continue
        solver.add_xor_clause(lits, value=False)
        c_comm += _xor_clause_count(lits, False)

    solver.add_clause(list(range(1, n_vars_xz + 1)))
    c_p0 = 1

    # ⟨P,Lj⟩=1 for at least one j
    for idx, L in enumerate(logical_basis):
        lits_L = [i + 1 for i in range(n) if L[n + i] % 2 == 1]
        lits_L += [n + 1 + i for i in range(n) if L[i] % 2 == 1]
        a_j = a_start + idx
        if lits_L:
            solver.add_xor_clause(lits_L + [a_j], value=False)
            c_log += _xor_clause_count(lits_L + [a_j], False)
        else:
            solver.add_clause([-a_j])
            c_log += 1

    solver.add_clause(list(range(a_start, a_start + len(logical_basis))))
    c_log += 1

    # w_i = x_i ∨ z_i
    for i in range(n):
        xi, zi, wi = 1 + i, n + 1 + i, w_start + i
        solver.add_clause([-wi, xi, zi])
        solver.add_clause([-xi, wi])
        solver.add_clause([-zi, wi])
    c_wdef = 3 * n

    t_build_end = time.perf_counter()
    build_time_sec = t_build_end - t_build_start
    c_card = 0

    def _record_blocking_round(
        round_idx: int,
        sat: bool,
        solve_sec: float,
        nv: Optional[int],
        nc: Optional[int],
        *,
        bounds_str: str = "",
    ) -> None:
        if round_idx == 1:
            tb, te, bld = build_time_sec, 0.0, build_time_sec
        else:
            tb, te, bld = 0.0, 0.0, 0.0
        row: Dict[str, Any] = {
            "k": round_idx,
            "sat": sat,
            "time_base_sec": tb,
            "time_cardenc_sec": te,
            "build_time_sec": bld,
            "time_sec": solve_sec,
            "nof_vars": nv,
            "nof_clauses": nc,
            "clauses_commutation": c_comm,
            "clauses_p_nonzero": c_p0,
            "clauses_logical": c_log,
            "clauses_weight_def": c_wdef,
            "clauses_cardinality": c_card,
        }
        if bounds_str:
            row["bounds_str"] = bounds_str
        _append_per_k_row(per_k_records, row)

    def _weight_from_model(model: Optional[List[int]]) -> int:
        if not model:
            return 0
        model_set = set(model)
        return sum(1 for i in range(n) if (w_start + i) in model_set)

    def _support_from_model(model: Optional[List[int]]) -> List[int]:
        """Indices i where w_i=1, sorted by i (qubit index)."""
        if not model:
            return []
        model_set = set(model)
        return sorted(i for i in range(n) if (w_start + i) in model_set)

    def _critical_vars_and_lits(
        model: Optional[List[int]],
        support: List[int],
        w: int,
    ) -> List[int]:
        """
        Variables corresponding to the first w error weights (not first w vars by index).
        Error weight for qubit i is w_i. Block w_i for the first w qubits in support.
        """
        if not model or w <= 0:
            return []
        model_set = set(model)
        # First w error weights = w_i for first w qubits in support
        first_error_qubits = support[:w]
        critical_vars = [w_start + i for i in first_error_qubits]
        # Literals false in current model (for blocking clause)
        return [
            (-v if v in model_set else v)
            for v in critical_vars
        ]

    round_idx = 0
    nv0, nc0 = _solver_formula_stats(solver)
    t_solve = time.perf_counter()
    result = bool(solver.solve())
    solve_sec = time.perf_counter() - t_solve
    round_idx += 1
    if result:
        model = solver.get_model()
        w0 = _weight_from_model(model)
        bs0 = _bounds_str_scan_lb_ub(1, w0)
    else:
        model = None
        bs0 = "[?,∞]"
    _record_blocking_round(
        round_idx, result, solve_sec, nv0, nc0, bounds_str=bs0
    )
    if not result:
        solver.delete()
        return None

    min_weight = _weight_from_model(model)
    block_clause_count = 0
    if debug:
        print(f"[DEBUG] blocking: initial weight = {min_weight}")

    # Block this solution (full block)
    block_clause = [-lit for lit in model]
    solver.add_clause(block_clause)
    block_clause_count += 1
    if show_block_clauses:
        names = [_lit_to_name_blocking(-lit, n, w_start, a_start, n_logicals) for lit in model]
        print(f"  [1] full block ({len(block_clause)} lits): ({names[0]} ∨ ... ∨ {names[-1]})")

    while True:
        nv, nc = _solver_formula_stats(solver)
        t_solve = time.perf_counter()
        result = bool(solver.solve())
        solve_sec = time.perf_counter() - t_solve
        round_idx += 1
        if result:
            model = solver.get_model()
            weight = _weight_from_model(model)
            support = _support_from_model(model)
            ub_best = min(min_weight, weight)
            bs = f"[1,{ub_best}]"
        else:
            model = None
            weight = 0
            support = []
            bs = _bounds_str_scan_lb_ub(min_weight, min_weight)
        _record_blocking_round(
            round_idx, result, solve_sec, nv, nc, bounds_str=bs
        )
        if not result:
            if stats is not None:
                stats["block_clause_count"] = block_clause_count
            solver.delete()
            return min_weight

        if weight > min_weight:
            block_lits = _critical_vars_and_lits(model, support, min_weight)
            if block_lits:
                solver.add_clause(block_lits)
                block_clause_count += 1
                if show_block_clauses:
                    names = [_lit_to_name_blocking(lit, n, w_start, a_start, n_logicals) for lit in block_lits]
                    print(f"  [{block_clause_count}] partial (w_i for first {min_weight} in support): ({' ∨ '.join(names)})")
            if debug:
                print(f"[DEBUG] blocking: weight={weight} > min={min_weight}, blocked {len(block_lits)} critical vars")
        else:
            # weight <= min_weight: update min, add full block
            min_weight = weight
            block_clause = [-lit for lit in model]
            solver.add_clause(block_clause)
            block_clause_count += 1
            if show_block_clauses:
                names = [_lit_to_name_blocking(-lit, n, w_start, a_start, n_logicals) for lit in model]
                print(f"  [{block_clause_count}] full block (new min={min_weight}): ({names[0]} ∨ ... ∨ {names[-1]})")
            if debug:
                print(f"[DEBUG] blocking: new min_weight = {min_weight}")

