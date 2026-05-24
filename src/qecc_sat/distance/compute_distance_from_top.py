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
from ..maxsat_solver import WCNFBuilder, minimize_soft_weight

def _min_distance_or_logicals_maxsat(
    S: List[List[Union[int, float]]],
    solver_type: SolverType,
    max_distance: int,
    logical_basis: List[List[int]],
    n: int,
    m: int,
    *,
    debug: bool = False,
    show_formula: bool = False,
    stats: Optional[Dict[str, int]] = None,
    timeout_sec: Optional[float] = None,
) -> Optional[int]:
    """Single RC2 solve: minimize sum of w_i subject to OR-logicals constraints."""
    n_vars_xz = 2 * n
    w_start = n_vars_xz + 1
    a_start = w_start + n
    top_id = a_start + len(logical_basis) - 1
    next_id_ref = [top_id]

    builder = WCNFBuilder()
    c_comm, c_p0, c_log, c_wdef = 0, 0, 0, 0

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
            builder.add_clause([-lits[0]])
            c_comm += 1
            continue
        builder.add_xor_clause(lits, value=False, next_var_ref=next_id_ref)
        c_comm += builder.xor_clause_count(lits, False)

    builder.add_clause(list(range(1, n_vars_xz + 1)))
    c_p0 = 1

    for idx, L in enumerate(logical_basis):
        lits_L = [i + 1 for i in range(n) if L[n + i] % 2 == 1]
        lits_L += [n + 1 + i for i in range(n) if L[i] % 2 == 1]
        a_j = a_start + idx
        if lits_L:
            builder.add_xor_clause(lits_L + [a_j], value=False, next_var_ref=next_id_ref)
            c_log += builder.xor_clause_count(lits_L + [a_j], False)
        else:
            builder.add_clause([-a_j])
            c_log += 1

    builder.add_clause(list(range(a_start, a_start + len(logical_basis))))
    c_log += 1

    for i in range(n):
        xi, zi, wi = 1 + i, n + 1 + i, w_start + i
        builder.add_clause([-wi, xi, zi])
        builder.add_clause([-xi, wi])
        builder.add_clause([-zi, wi])
        builder.add_soft_lit(-wi, weight=1)
    c_wdef = 3 * n

    if debug:
        print(
            f"[DEBUG] MaxSAT build: hard_clauses={builder.nof_hard_clauses()}, "
            f"soft_units={builder.nsoft}, nv={builder.nof_vars()}"
        )
    if show_formula:
        print("\n  --- OR-logicals MaxSAT (minimize sum w_i) ---")

    cost, _model, builder = minimize_soft_weight(
        builder, solver_type, max_weight=max_distance, timeout_sec=timeout_sec
    )
    if cost is None:
        return None

    if stats is not None:
        stats["nof_vars"] = builder.nof_vars()
        stats["nof_clauses"] = builder.nof_hard_clauses()
        stats["clauses_commutation"] = c_comm
        stats["clauses_p_nonzero"] = c_p0
        stats["clauses_logical"] = c_log
        stats["clauses_weight_def"] = c_wdef
        stats["clauses_cardinality"] = 0
        stats["maxsat_soft_units"] = builder.nsoft
        stats["maxsat_cost"] = cost
    return int(cost)

def _min_distance_css_sector_card_refine(
    H_parity: List[List[Union[int, float]]],
    logical_subset: List[List[int]],
    n: int,
    sector: str,
    solver_type: SolverType,
    max_distance: Optional[int],
    encoding: Any,
    *,
    debug: bool = False,
    stats: Optional[Dict[str, int]] = None,
    per_k_records: Optional[List[Dict[str, Any]]] = None,
    on_refine_row: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Optional[int]:
    """
    One CSS sector: same base CNF as _min_distance_css_sector_or_logicals, but distance
    via witness refinement on Hamming weight of bits 1..n (like min_distance_quantum_stabilizer_card_refine).

    CryptoSAT is not in ``CARD_SUPPORTED_SOLVERS`` (no native ``add_atmost``) but supports
    native XOR. We skip ITotalizer for it and use the CardEnc rebuild loop so the first
    witness solve matches ``_css_sector_solve_atmost_k`` with ``k >= n`` (base only, like
    CSS-split minmax).
    """
    if CardEnc is None or EncType is None:
        raise ImportError("pysat.card (CardEnc) is required")
    if not logical_subset:
        return None
    m = len(H_parity)
    if max_distance is None:
        max_distance = n

    a_start = n + 1
    k_log = len(logical_subset)
    top_id = a_start + k_log - 1
    bit_lits = list(range(1, n + 1))

    round_idx = 0

    def _record_sector_refine_round(
        sat: bool,
        solve_sec: float,
        nv: Optional[int],
        nc: Optional[int],
        *,
        refine_ctx: str = "",
        bounds_str: str = "",
    ) -> None:
        nonlocal round_idx
        round_idx += 1
        row: Dict[str, Any] = {
            "sector": sector,
            "k": round_idx,
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
        }
        if refine_ctx:
            row["refine_ctx"] = refine_ctx
        if bounds_str:
            row["bounds_str"] = bounds_str
        _append_per_k_row(per_k_records, row)
        if on_refine_row is not None:
            on_refine_row(row)

    def _xor_clause_count(lits: List[int], value: bool) -> int:
        if solver_type in XOR_SUPPORTED_SOLVERS:
            return 1
        return tseitin_xor_clause_count(lits, value)

    def add_sector_base(solver: Any) -> None:
        for j in range(m):
            lits = [i + 1 for i in range(n) if int(H_parity[j][i]) % 2 == 1]
            if not lits:
                continue
            if len(lits) == 1:
                solver.add_clause([-lits[0]])
                continue
            solver.add_xor_clause(lits, value=False)
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

    def weight_from_model(model: Optional[List[int]]) -> int:
        if not model:
            return 0
        ms = set(model)
        return sum(1 for i in range(n) if (i + 1) in ms)

    def try_bounded_native(
        bound: int, *, exact_if_unsat: Optional[int] = None
    ) -> tuple[bool, int]:
        s = get_solver(solver_type=solver_type)
        add_sector_base(s)
        s.add_atmost(bit_lits, bound)
        t0 = time.perf_counter()
        ok = bool(s.solve())
        solve_sec = time.perf_counter() - t0
        nv, nc = _solver_formula_stats(s)
        wgt = weight_from_model(s.get_model()) if ok else 0
        s.delete()
        bs = _bounds_str_refine_card(
            ok, wgt, bound, exact_if_unsat=exact_if_unsat
        )
        _record_sector_refine_round(
            ok, solve_sec, nv, nc, refine_ctx=f"|v|≤{bound}", bounds_str=bs
        )
        return ok, wgt

    def try_bounded_cardenc(
        bound: int, *, exact_if_unsat: Optional[int] = None
    ) -> tuple[bool, int]:
        s = get_solver(solver_type=solver_type)
        add_sector_base(s)
        card = CardEnc.atmost(
            lits=bit_lits, bound=bound, top_id=top_id, encoding=encoding
        )
        s.add_clauses(card.clauses)
        t0 = time.perf_counter()
        ok = bool(s.solve())
        solve_sec = time.perf_counter() - t0
        nv, nc = _solver_formula_stats(s)
        wgt = weight_from_model(s.get_model()) if ok else 0
        s.delete()
        bs = _bounds_str_refine_card(
            ok, wgt, bound, exact_if_unsat=exact_if_unsat
        )
        _record_sector_refine_round(
            ok, solve_sec, nv, nc, refine_ctx=f"|v|≤{bound}", bounds_str=bs
        )
        return ok, wgt

    if solver_type in CARD_SUPPORTED_SOLVERS:
        s0 = get_solver(solver_type=solver_type)
        add_sector_base(s0)
        t0 = time.perf_counter()
        ok0 = bool(s0.solve())
        solve_sec = time.perf_counter() - t0
        nv0, nc0 = _solver_formula_stats(s0)
        w0 = weight_from_model(s0.get_model()) if ok0 else 0
        _record_sector_refine_round(
            ok0,
            solve_sec,
            nv0,
            nc0,
            refine_ctx=(
                f"no_card witness|v|={w0}" if ok0 else "no_card UNSAT"
            ),
            bounds_str=_bounds_str_scan_lb_ub(1, w0 if ok0 else None),
        )
        if not ok0:
            s0.delete()
            return None
        U = weight_from_model(s0.get_model())
        s0.delete()
        if U > max_distance:
            ok, U = try_bounded_native(max_distance)
            if not ok:
                return None
        iterations = 0
        while U >= 1:
            ok, wgt = try_bounded_native(U - 1, exact_if_unsat=U)
            iterations += 1
            if debug:
                print(
                    f"[DEBUG] css sector {sector} refine: try |v|≤{U - 1} -> "
                    f"{'SAT' if ok else 'UNSAT'}",
                    flush=True,
                )
            if not ok:
                if stats is not None:
                    stats["css_sector_card_refine_iterations"] = iterations
                return U
            U = wgt
            if U > max_distance:
                ok2, U = try_bounded_native(max_distance)
                if not ok2:
                    if stats is not None:
                        stats["css_sector_card_refine_iterations"] = iterations
                    return None
        if stats is not None:
            stats["css_sector_card_refine_iterations"] = iterations
        return U if U >= 1 else None

    # ITotalizer on the first solve adds many vars/clauses; for CryptoSAT that diverges
    # from minmax's first sector step (no cardinality when k == n). Use CardEnc below.
    if ITotalizer is not None and solver_type != SolverType.CRYPTOSAT:
        solver = get_solver(solver_type=solver_type)
        add_sector_base(solver)
        tot = ITotalizer(lits=bit_lits, ubound=n, top_id=top_id)
        for cl in tot.cnf.clauses:
            solver.add_clause(cl)
        t_s = time.perf_counter()
        ok_first = bool(solver.solve())
        solve_sec = time.perf_counter() - t_s
        nv, nc = _solver_formula_stats(solver)
        Uw = weight_from_model(solver.get_model()) if ok_first else 0
        _record_sector_refine_round(
            ok_first,
            solve_sec,
            nv,
            nc,
            refine_ctx=(
                f"no_assum witness|v|={Uw}" if ok_first else "no_assum UNSAT"
            ),
            bounds_str=_bounds_str_scan_lb_ub(1, Uw if ok_first else None),
        )
        if not ok_first:
            tot.delete()
            solver.delete()
            return None
        U = weight_from_model(solver.get_model())
        if U > max_distance:
            t_s = time.perf_counter()
            if max_distance < n:
                ok = bool(solver.solve(assumptions=[-tot.rhs[max_distance]]))
            else:
                ok = bool(solver.solve())
            solve_sec = time.perf_counter() - t_s
            nv, nc = _solver_formula_stats(solver)
            if ok:
                Un = weight_from_model(solver.get_model())
                bs_cap = _bounds_str_scan_lb_ub(1, Un)
            else:
                bs_cap = f"[{max_distance + 1},∞]"
            _record_sector_refine_round(
                ok,
                solve_sec,
                nv,
                nc,
                refine_ctx=f"|v|≤{max_distance} (cap)",
                bounds_str=bs_cap,
            )
            if not ok:
                tot.delete()
                solver.delete()
                return None
            U = weight_from_model(solver.get_model())
        iterations = 0
        while U >= 1:
            t_s = time.perf_counter()
            if U - 1 < n:
                ok = bool(solver.solve(assumptions=[-tot.rhs[U - 1]]))
            else:
                ok = bool(solver.solve())
            solve_sec = time.perf_counter() - t_s
            nv, nc = _solver_formula_stats(solver)
            if ok:
                new_u = weight_from_model(solver.get_model())
                bs_loop = _bounds_str_scan_lb_ub(1, new_u)
            else:
                bs_loop = _bounds_str_scan_lb_ub(U, U)
            _record_sector_refine_round(
                ok,
                solve_sec,
                nv,
                nc,
                refine_ctx=f"|v|≤{U - 1}",
                bounds_str=bs_loop,
            )
            iterations += 1
            if debug:
                print(
                    f"[DEBUG] css sector {sector} refine: try |v|≤{U - 1} -> "
                    f"{'SAT' if ok else 'UNSAT'}",
                    flush=True,
                )
            if not ok:
                if stats is not None:
                    stats["css_sector_card_refine_iterations"] = iterations
                tot.delete()
                solver.delete()
                return U
            U = weight_from_model(solver.get_model())
            if U > max_distance:
                t_s = time.perf_counter()
                if max_distance < n:
                    ok2 = bool(solver.solve(assumptions=[-tot.rhs[max_distance]]))
                else:
                    ok2 = bool(solver.solve())
                solve_sec = time.perf_counter() - t_s
                nv2, nc2 = _solver_formula_stats(solver)
                if ok2:
                    Un2 = weight_from_model(solver.get_model())
                    bs2 = _bounds_str_scan_lb_ub(1, Un2)
                else:
                    bs2 = f"[{max_distance + 1},∞]"
                _record_sector_refine_round(
                    ok2,
                    solve_sec,
                    nv2,
                    nc2,
                    refine_ctx=f"|v|≤{max_distance} (cap)",
                    bounds_str=bs2,
                )
                if not ok2:
                    if stats is not None:
                        stats["css_sector_card_refine_iterations"] = iterations
                    tot.delete()
                    solver.delete()
                    return None
                U = weight_from_model(solver.get_model())
        if stats is not None:
            stats["css_sector_card_refine_iterations"] = iterations
        tot.delete()
        solver.delete()
        return U if U >= 1 else None

    s0 = get_solver(solver_type=solver_type)
    add_sector_base(s0)
    t0 = time.perf_counter()
    ok0 = bool(s0.solve())
    solve_sec = time.perf_counter() - t0
    nv0, nc0 = _solver_formula_stats(s0)
    w0 = weight_from_model(s0.get_model()) if ok0 else 0
    _record_sector_refine_round(
        ok0,
        solve_sec,
        nv0,
        nc0,
        refine_ctx=(
            f"no_card witness|v|={w0}" if ok0 else "no_card UNSAT"
        ),
        bounds_str=_bounds_str_scan_lb_ub(1, w0 if ok0 else None),
    )
    if not ok0:
        s0.delete()
        return None
    U = weight_from_model(s0.get_model())
    s0.delete()
    if U > max_distance:
        ok, U = try_bounded_cardenc(max_distance)
        if not ok:
            return None
    iterations = 0
    while U >= 1:
        ok, wgt = try_bounded_cardenc(U - 1, exact_if_unsat=U)
        iterations += 1
        if debug:
            print(
                f"[DEBUG] css sector {sector} refine: try |v|≤{U - 1} -> "
                f"{'SAT' if ok else 'UNSAT'}",
                flush=True,
            )
        if not ok:
            if stats is not None:
                stats["css_sector_card_refine_iterations"] = iterations
            return U
        U = wgt
        if U > max_distance:
            ok2, U = try_bounded_cardenc(max_distance)
            if not ok2:
                if stats is not None:
                    stats["css_sector_card_refine_iterations"] = iterations
                return None
    if stats is not None:
        stats["css_sector_card_refine_iterations"] = iterations
    return U if U >= 1 else None

def min_distance_quantum_stabilizer_card_refine(
    S: List[List[Union[int, float]]],
    solver_type: SolverType = SolverType.GLUCOSE3,
    max_distance: Optional[int] = None,
    *,
    debug: bool = False,
    stats: Optional[Dict[str, int]] = None,
    encoding: Any = None,
    per_k_records: Optional[List[Dict[str, Any]]] = None,
    setup_timing_out: Optional[Dict[str, float]] = None,
    logical_basis_override: Optional[List[List[int]]] = None,
    on_refine_row: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Optional[int]:
    """
    Minimum distance (OR-logicals) via witness refinement from above:

    1. Solve with no cardinality on w (same feasible set as blocking's first call).
    2. Let U be the Pauli weight (number of w_i true) in that model.
    3. Ask whether Σ w_i ≤ U−1 is satisfiable (strict improvement). If UNSAT, U is the
       minimum distance d: Σw ≤ d is SAT (witness) and Σw ≤ d−1 is UNSAT.
    4. If SAT, replace U by the weight of the new model and repeat.

    Respects max_distance: if the unconstrained witness has weight > max_distance, first
    checks Σ w_i ≤ max_distance; UNSAT there means no codeword in the search range (None).

    Uses ITotalizer + assumptions when available (same rhs semantics as stepwise_card), except
    for CryptoSAT: native XOR but no ``add_atmost``, so skip ITotalizer and use the same
    witness + CardEnc rebuild loop as the no-ITotalizer path (first solve = no cardinality on w).

    Native add_atmost solvers use a fresh solver for each Σw ≤ U−1 test. If ITotalizer is
    missing, uses CardEnc.atmost for each bound test.

    If ``per_k_records`` is set, appends one row per SAT ``solve()`` (column ``k`` = round
    index). Clause-bucket fields are left unset (printed as ``None``) except timing.

    If ``on_refine_row`` is set, it is called with each appended row dict immediately after
    each ``solve()`` (for live progress in CLI tools).
    """
    if CardEnc is None or EncType is None:
        raise ImportError("pysat.card (CardEnc) is required")

    if encoding is None:
        encoding = EncType.seqcounter

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
    top_id = a_start + len(logical_basis) - 1
    w_lits = list(range(w_start, w_start + n))

    round_idx = 0

    def _record_refine_round(
        sat: bool,
        solve_sec: float,
        nv: Optional[int],
        nc: Optional[int],
        *,
        refine_ctx: str = "",
        bounds_str: str = "",
    ) -> None:
        nonlocal round_idx
        round_idx += 1
        row: Dict[str, Any] = {
            "k": round_idx,
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
        }
        if refine_ctx:
            row["refine_ctx"] = refine_ctx
        if bounds_str:
            row["bounds_str"] = bounds_str
        _append_per_k_row(per_k_records, row)
        if on_refine_row is not None:
            on_refine_row(row)

    def add_or_logicals_base(solver: Any) -> None:
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

    def weight_from_model(model: Optional[List[int]]) -> int:
        if not model:
            return 0
        ms = set(model)
        return sum(1 for i in range(n) if (w_start + i) in ms)

    def try_bounded_native(
        bound: int, *, exact_if_unsat: Optional[int] = None
    ) -> tuple[bool, int]:
        """Return (sat, weight) for base ∧ Σw ≤ bound; weight meaningful only if sat."""
        s = get_solver(solver_type=solver_type)
        add_or_logicals_base(s)
        s.add_atmost(w_lits, bound)
        t0 = time.perf_counter()
        ok = bool(s.solve())
        solve_sec = time.perf_counter() - t0
        nv, nc = _solver_formula_stats(s)
        wgt = weight_from_model(s.get_model()) if ok else 0
        s.delete()
        bs = _bounds_str_refine_card(
            ok, wgt, bound, exact_if_unsat=exact_if_unsat
        )
        _record_refine_round(
            ok, solve_sec, nv, nc, refine_ctx=f"Σw≤{bound}", bounds_str=bs
        )
        return ok, wgt

    def try_bounded_cardenc(
        bound: int, *, exact_if_unsat: Optional[int] = None
    ) -> tuple[bool, int]:
        s = get_solver(solver_type=solver_type)
        add_or_logicals_base(s)
        card = CardEnc.atmost(lits=w_lits, bound=bound, top_id=top_id, encoding=encoding)
        s.add_clauses(card.clauses)
        t0 = time.perf_counter()
        ok = bool(s.solve())
        solve_sec = time.perf_counter() - t0
        nv, nc = _solver_formula_stats(s)
        wgt = weight_from_model(s.get_model()) if ok else 0
        s.delete()
        bs = _bounds_str_refine_card(
            ok, wgt, bound, exact_if_unsat=exact_if_unsat
        )
        _record_refine_round(
            ok, solve_sec, nv, nc, refine_ctx=f"Σw≤{bound}", bounds_str=bs
        )
        return ok, wgt

    # --- Native cardinality: no ITotalizer; fresh solver per bound test ---
    if solver_type in CARD_SUPPORTED_SOLVERS:
        s0 = get_solver(solver_type=solver_type)
        add_or_logicals_base(s0)
        t0 = time.perf_counter()
        ok0 = bool(s0.solve())
        solve_sec = time.perf_counter() - t0
        nv0, nc0 = _solver_formula_stats(s0)
        w0 = weight_from_model(s0.get_model()) if ok0 else 0
        _record_refine_round(
            ok0,
            solve_sec,
            nv0,
            nc0,
            refine_ctx=(
                f"no_card witness_wt={w0}" if ok0 else "no_card UNSAT"
            ),
            bounds_str=_bounds_str_scan_lb_ub(1, w0 if ok0 else None),
        )
        if not ok0:
            s0.delete()
            return None
        U = weight_from_model(s0.get_model())
        s0.delete()
        if U > max_distance:
            ok, U = try_bounded_native(max_distance)
            if not ok:
                return None
        iterations = 0
        while U >= 1:
            ok, wgt = try_bounded_native(U - 1, exact_if_unsat=U)
            iterations += 1
            if not ok:
                if stats is not None:
                    stats["card_refine_iterations"] = iterations
                return U
            U = wgt
            if U > max_distance:
                ok2, U = try_bounded_native(max_distance)
                if not ok2:
                    if stats is not None:
                        stats["card_refine_iterations"] = iterations
                    return None
        if stats is not None:
            stats["card_refine_iterations"] = iterations
        return U if U >= 1 else None

    # --- PySAT + ITotalizer (preferred); skip for CryptoSAT (match no_card first solve) ---
    if ITotalizer is not None and solver_type != SolverType.CRYPTOSAT:
        solver = get_solver(solver_type=solver_type)
        add_or_logicals_base(solver)
        tot = ITotalizer(lits=w_lits, ubound=n, top_id=top_id)
        for cl in tot.cnf.clauses:
            solver.add_clause(cl)
        if stats is not None:
            stats["totalizer_clauses"] = len(tot.cnf.clauses)

        t_s = time.perf_counter()
        ok_first = bool(solver.solve())
        solve_sec = time.perf_counter() - t_s
        nv, nc = _solver_formula_stats(solver)
        w0 = weight_from_model(solver.get_model()) if ok_first else 0
        _record_refine_round(
            ok_first,
            solve_sec,
            nv,
            nc,
            refine_ctx=(
                f"no_assum witness_wt={w0}" if ok_first else "no_assum UNSAT"
            ),
            bounds_str=_bounds_str_scan_lb_ub(1, w0 if ok_first else None),
        )
        if not ok_first:
            tot.delete()
            solver.delete()
            return None
        U = weight_from_model(solver.get_model())

        if U > max_distance:
            t_s = time.perf_counter()
            if max_distance < n:
                ok = bool(solver.solve(assumptions=[-tot.rhs[max_distance]]))
            else:
                ok = bool(solver.solve())
            solve_sec = time.perf_counter() - t_s
            nv, nc = _solver_formula_stats(solver)
            if ok:
                w_cap = weight_from_model(solver.get_model())
                bs_cap = _bounds_str_scan_lb_ub(1, w_cap)
            else:
                bs_cap = f"[{max_distance + 1},∞]"
            _record_refine_round(
                ok,
                solve_sec,
                nv,
                nc,
                refine_ctx=f"Σw≤{max_distance} (cap)",
                bounds_str=bs_cap,
            )
            if not ok:
                tot.delete()
                solver.delete()
                return None
            U = weight_from_model(solver.get_model())

        iterations = 0
        while U >= 1:
            t_s = time.perf_counter()
            if U - 1 < n:
                ok = bool(solver.solve(assumptions=[-tot.rhs[U - 1]]))
            else:
                ok = bool(solver.solve())
            solve_sec = time.perf_counter() - t_s
            nv, nc = _solver_formula_stats(solver)
            if ok:
                new_w = weight_from_model(solver.get_model())
                bs_loop = _bounds_str_scan_lb_ub(1, new_w)
            else:
                bs_loop = _bounds_str_scan_lb_ub(U, U)
            _record_refine_round(
                ok,
                solve_sec,
                nv,
                nc,
                refine_ctx=f"Σw≤{U - 1}",
                bounds_str=bs_loop,
            )
            iterations += 1
            if debug:
                print(f"[DEBUG] card_refine: try Σw≤{U-1} -> {'SAT' if ok else 'UNSAT'}", flush=True)
            if not ok:
                if stats is not None:
                    stats["card_refine_iterations"] = iterations
                tot.delete()
                solver.delete()
                return U
            U = weight_from_model(solver.get_model())
            if U > max_distance:
                t_s = time.perf_counter()
                if max_distance < n:
                    ok2 = bool(solver.solve(assumptions=[-tot.rhs[max_distance]]))
                else:
                    ok2 = bool(solver.solve())
                solve_sec = time.perf_counter() - t_s
                nv2, nc2 = _solver_formula_stats(solver)
                if ok2:
                    w2 = weight_from_model(solver.get_model())
                    bs2 = _bounds_str_scan_lb_ub(1, w2)
                else:
                    bs2 = f"[{max_distance + 1},∞]"
                _record_refine_round(
                    ok2,
                    solve_sec,
                    nv2,
                    nc2,
                    refine_ctx=f"Σw≤{max_distance} (cap)",
                    bounds_str=bs2,
                )
                if not ok2:
                    if stats is not None:
                        stats["card_refine_iterations"] = iterations
                    tot.delete()
                    solver.delete()
                    return None
                U = weight_from_model(solver.get_model())

        if stats is not None:
            stats["card_refine_iterations"] = iterations
        tot.delete()
        solver.delete()
        return U if U >= 1 else None

    # --- No ITotalizer: CardEnc per bound test (still witness refinement) ---
    s0 = get_solver(solver_type=solver_type)
    add_or_logicals_base(s0)
    t0 = time.perf_counter()
    ok0 = bool(s0.solve())
    solve_sec = time.perf_counter() - t0
    nv0, nc0 = _solver_formula_stats(s0)
    w0 = weight_from_model(s0.get_model()) if ok0 else 0
    _record_refine_round(
        ok0,
        solve_sec,
        nv0,
        nc0,
        refine_ctx=(
            f"no_card witness_wt={w0}" if ok0 else "no_card UNSAT"
        ),
        bounds_str=_bounds_str_scan_lb_ub(1, w0 if ok0 else None),
    )
    if not ok0:
        s0.delete()
        return None
    U = weight_from_model(s0.get_model())
    s0.delete()
    if U > max_distance:
        ok, U = try_bounded_cardenc(max_distance)
        if not ok:
            return None
    iterations = 0
    while U >= 1:
        ok, wgt = try_bounded_cardenc(U - 1, exact_if_unsat=U)
        iterations += 1
        if debug:
            print(f"[DEBUG] card_refine: try Σw≤{U-1} -> {'SAT' if ok else 'UNSAT'}", flush=True)
        if not ok:
            if stats is not None:
                stats["card_refine_iterations"] = iterations
            return U
        U = wgt
        if U > max_distance:
            ok2, U = try_bounded_cardenc(max_distance)
            if not ok2:
                if stats is not None:
                    stats["card_refine_iterations"] = iterations
                return None
    if stats is not None:
        stats["card_refine_iterations"] = iterations
    return U if U >= 1 else None

