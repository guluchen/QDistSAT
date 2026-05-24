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
from ..maxsat_solver import is_maxsat_solver
from .compute_distance_from_top import _min_distance_or_logicals_maxsat
from .prune_with_tanner_graph import (
    dynamic_deficit_blocking,
    inject_stopping_set_closure,
    tanner_neighbors,
)

def min_distance_quantum_stabilizer(
    S: List[List[Union[int, float]]],
    solver_type: SolverType = SolverType.GLUCOSE3,
    max_distance: Optional[int] = None,
    *,
    debug: bool = False,
    exclude_stabilizer: bool = True,
    show_formula: bool = False,
    stats: Optional[Dict[str, int]] = None,
    encoding: Any = None,
) -> Optional[int]:
    """
    Compute the minimum distance of a quantum stabilizer code from its
    binary symplectic stabilizer matrix S.

    S is m x 2n (m generators, n qubits). Each row is (X part | Z part).
    The true code distance is the minimum Pauli weight of a nonzero vector
    in the symplectic dual excluding the stabilizer group:
    d = min{wt(P) : P in S^\\perp \\ S}.

    Parameters
    ----------
    S : list of lists, shape (m, 2*n)
        Stabilizer matrix over GF(2). Columns 0..n-1 = X part, n..2n-1 = Z part.
    solver_type : SolverType
        SAT solver to use.
    max_distance : int, optional
        Stop after this weight.
    debug : bool, optional
        If True, print each step and result. Default False.
    show_formula : bool, optional
        If True, print each SAT clause as it is added. Default False.
    stats : dict, optional
        If provided, will be populated when a result is found with: "nof_vars", "nof_clauses",
        "clauses_commutation", "clauses_p_nonzero", "clauses_logical" (if exclude_stabilizer),
        "clauses_weight_def", "clauses_cardinality".
    encoding : pysat.card.EncType, optional
        Cardinality encoding for Σw_i ≤ k. Ignored for MiniCard/GlueCard (native add_atmost).
        Z3/CVC5 use CardEnc with this encoding. Default seqcounter.
    exclude_stabilizer : bool, optional
        If True (default), exclude stabilizer group to compute true distance
        d = min{wt(P): P in S^\\perp \\ S}. If False, compute min in S^\\perp \\ {0}
        (includes stabilizers; surface codes then return 1 or 2).

    Returns
    -------
    int or None
        Minimum Pauli weight. With exclude_stabilizer=True, returns the
        true code distance. With exclude_stabilizer=False, returns the
        minimum weight in the full dual (lower bound, often 1 or 2 for
        surface codes).
    """
    if CardEnc is None or EncType is None:
        raise ImportError("pysat.card (CardEnc) is required")

    m, cols = _matrix_shape(S)
    if m == 0 or cols % 2 != 0:
        if debug:
            print("[DEBUG] min_distance_quantum_stabilizer: invalid S (m=0 or odd cols) -> None")
        return None
    n = cols // 2  # number of qubits

    if max_distance is None:
        max_distance = n

    if encoding is None:
        encoding = EncType.seqcounter

    if debug:
        print(f"[DEBUG] min_distance_quantum_stabilizer: m={m} generators, n={n} qubits, max_distance={max_distance}, exclude_stabilizer={exclude_stabilizer}")
        print(f"[DEBUG]   Variables: 1..{n}=X, {n+1}..{2*n}=Z, {2*n+1}..{2*n+n}=w (Pauli weight per qubit)")

    # Variables: 1..n = x_1..x_n (X), n+1..2n = z_1..z_n (Z). Aux: 2n+1..2n+n = w_1..w_n (Pauli weight per qubit)
    n_vars_xz = 2 * n
    w_start = n_vars_xz + 1
    top_id = n_vars_xz + n  # for CardEnc

    # For exclude_stabilizer: get full logical basis {X̄ᵢ, Z̄ᵢ}, run SAT for each
    logical_basis: List[List[int]] = []
    if exclude_stabilizer:
        logical_basis = logical_basis_symplectic(S, n)
        if debug:
            print(f"[DEBUG]   Logical basis: {len(logical_basis)} operators (X̄ᵢ, Z̄ᵢ for i=1..k)")
        if not logical_basis:
            if debug:
                print("[DEBUG]   No logical operators -> None")
            return None

    def _xor_clause_count(lits: List[int], value: bool) -> int:
        """Number of CNF clauses for one XOR constraint (1 if native XOR, else 2^(n-1))."""
        if solver_type in XOR_SUPPORTED_SOLVERS:
            return 1
        return tseitin_xor_clause_count(lits, value)

    def _min_weight_for_logical(logical_L: List[int], logical_idx: int = 0) -> Optional[int]:
        """Find min Pauli weight of P in S⊥ with ⟨P,L⟩_symp=1."""
        for k in range(1, max_distance + 1):
            if debug:
                print(f"[DEBUG] --- Logical L{logical_idx}, trying weight k={k} ---")
            solver = get_solver(solver_type=solver_type)
            if show_formula:
                print(f"\n  --- Logical L{logical_idx}, weight k={k} ---")
            c_comm, c_p0, c_log, c_wdef, c_card = 0, 0, 0, 0, 0
            next_id_ref = [top_id]
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
                    if show_formula:
                        print(f"    P⊥S{j+1}:  {_lit_to_name(-lits[0], n, w_start)} = 0")
                    continue
                _add_xor_clause(solver, lits, value=False, next_var_ref=next_id_ref)
                c_comm += _xor_clause_count(lits, False)
                if show_formula:
                    names = [_lit_to_name(ℓ, n, w_start) for ℓ in lits]
                    print(f"    P⊥S{j+1}:  XOR({', '.join(names)}) = 0")
            solver.add_clause(list(range(1, n_vars_xz + 1)))
            c_p0 = 1
            if show_formula:
                print(f"    P≠0:  (x1∨x2∨...∨xn∨z1∨...∨zn)")
            # ⟨P,L⟩_symp = 1
            lits_L = [i + 1 for i in range(n) if logical_L[n + i] % 2 == 1]
            lits_L += [n + 1 + i for i in range(n) if logical_L[i] % 2 == 1]
            if lits_L:
                _add_xor_clause(solver, lits_L, value=True, next_var_ref=next_id_ref)
                c_log = _xor_clause_count(lits_L, True)
                if show_formula:
                    names = [_lit_to_name(ℓ, n, w_start) for ℓ in lits_L]
                    print(f"    ⟨P,L⟩=1:  XOR({', '.join(names)}) = 1")
            for i in range(n):
                xi, zi, wi = 1 + i, n + 1 + i, w_start + i
                solver.add_clause([-wi, xi, zi])
                solver.add_clause([-xi, wi])
                solver.add_clause([-zi, wi])
                if show_formula and i < 3:  # show first 3 qubits to avoid spam
                    print(f"    w{i+1}=x{i+1}∨z{i+1}:  (¬w{i+1}∨x{i+1}∨z{i+1}) ∧ (¬x{i+1}∨w{i+1}) ∧ (¬z{i+1}∨w{i+1})")
            c_wdef = 3 * n
            if show_formula and n > 3:
                print(f"    ... (w4..w{n} same pattern)")
            w_lits = list(range(w_start, w_start + n))
            if solver_type in NATIVE_ONLY_CARD_SOLVERS:
                solver.add_atmost(w_lits, k)
                c_card = 0
                if show_formula:
                    print(f"    Σw_i ≤ k:  native add_atmost (MiniCard/GlueCard)")
            else:
                card = CardEnc.atmost(
                    lits=w_lits,
                    bound=k,
                    top_id=next_id_ref[0],
                    encoding=encoding,
                )
                solver.add_clauses(card.clauses)
                c_card = len(card.clauses)
                if card.clauses:
                    hi = max(abs(lit) for cl in card.clauses for lit in cl)
                    next_id_ref[0] = max(next_id_ref[0], hi)
                if show_formula:
                    print(f"    Σw_i ≤ k:  CardEnc.atmost(w1..w{n}, bound={k})  # {len(card.clauses)} clauses")
            result = solver.solve()
            if result and stats is not None:
                try:
                    stats["nof_vars"] = solver.nof_vars()
                    stats["nof_clauses"] = solver.nof_clauses()
                except Exception:
                    pass
                stats["clauses_commutation"] = c_comm
                stats["clauses_p_nonzero"] = c_p0
                stats["clauses_logical"] = c_log
                stats["clauses_weight_def"] = c_wdef
                stats["clauses_cardinality"] = c_card
            solver.delete()
            if result:
                return k
        return None

    if exclude_stabilizer:
        best: Optional[int] = None
        for idx, L in enumerate(logical_basis):
            d_L = _min_weight_for_logical(L, logical_idx=idx)
            if debug:
                print(f"[DEBUG] Logical L[{idx}]: min weight = {d_L}")
            if d_L is not None and (best is None or d_L < best):
                best = d_L
        return best

    # exclude_stabilizer=False: min in S⊥ \ {0}
    for k in range(1, max_distance + 1):
        if debug:
            print(f"[DEBUG] --- Trying weight k={k} ---")
        solver = get_solver(solver_type=solver_type)
        if show_formula:
            print(f"\n  --- SAT formula for weight k={k} ---")
        c_comm, c_p0, c_wdef, c_card = 0, 0, 0, 0
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
                if show_formula:
                    print(f"    P⊥S{j+1}:  {_lit_to_name(-lits[0], n, w_start)} = 0")
                continue
            solver.add_xor_clause(lits, value=False)
            c_comm += _xor_clause_count(lits, False)
            if show_formula:
                names = [_lit_to_name(ℓ, n, w_start) for ℓ in lits]
                print(f"    P⊥S{j+1}:  XOR({', '.join(names)}) = 0")
        solver.add_clause(list(range(1, n_vars_xz + 1)))
        c_p0 = 1
        if show_formula:
            print(f"    P≠0:  (x1∨x2∨...∨xn∨z1∨...∨zn)")
        for i in range(n):
            xi, zi, wi = 1 + i, n + 1 + i, w_start + i
            solver.add_clause([-wi, xi, zi])
            solver.add_clause([-xi, wi])
            solver.add_clause([-zi, wi])
            if show_formula and i < 3:
                print(f"    w{i+1}=x{i+1}∨z{i+1}:  (¬w{i+1}∨x{i+1}∨z{i+1}) ∧ (¬x{i+1}∨w{i+1}) ∧ (¬z{i+1}∨w{i+1})")
        c_wdef = 3 * n
        if show_formula and n > 3:
            print(f"    ... (w4..w{n} same pattern)")
        w_lits = list(range(w_start, w_start + n))
        if solver_type in NATIVE_ONLY_CARD_SOLVERS:
            solver.add_atmost(w_lits, k)
            c_card = 0
            if show_formula:
                print(f"    Σw_i ≤ k:  native add_atmost (MiniCard/GlueCard)")
        else:
            card = CardEnc.atmost(
                lits=w_lits,
                bound=k,
                top_id=top_id,
                encoding=encoding,
            )
            solver.add_clauses(card.clauses)
            c_card = len(card.clauses)
            if show_formula:
                print(f"    Σw_i ≤ k:  CardEnc.atmost(w1..w{n}, bound={k})  # {len(card.clauses)} clauses")
        result = solver.solve()
        if result and stats is not None:
            try:
                stats["nof_vars"] = solver.nof_vars()
                stats["nof_clauses"] = solver.nof_clauses()
            except Exception:
                pass
            stats["clauses_commutation"] = c_comm
            stats["clauses_p_nonzero"] = c_p0
            stats["clauses_logical"] = 0
            stats["clauses_weight_def"] = c_wdef
            stats["clauses_cardinality"] = c_card
        solver.delete()
        if result:
            return k
    return None

def min_distance_quantum_stabilizer_or_logicals(
    S: List[List[Union[int, float]]],
    solver_type: SolverType = SolverType.GLUCOSE3,
    max_distance: Optional[int] = None,
    *,
    debug: bool = False,
    show_formula: bool = False,
    stats: Optional[Dict[str, int]] = None,
    encoding: Any = None,
    per_k_records: Optional[List[Dict[str, Any]]] = None,
    setup_timing_out: Optional[Dict[str, float]] = None,
    logical_basis_override: Optional[List[List[int]]] = None,
    cardinality_encoding: str = "standard",
    progress_q: Optional[Any] = None,
    timeout_sec: Optional[float] = None,
) -> Optional[int]:
    """
    Same as min_distance_quantum_stabilizer with exclude_stabilizer=True, but encode
    all logical operators in one SAT instance: P ∉ S ⟺ (⟨P,L₁⟩=1) ∨ (⟨P,L₂⟩=1) ∨ ... ∨ (⟨P,Lₖ⟩=1).

    ``cardinality_encoding``: ``\"standard\"`` uses native/CardEnc atmost on w_i;
    ``\"log\"`` uses logarithmic selector slots (see ``log_encoding``).
    Uses auxiliary variables a_j with XOR(lits_Lj, a_j)=0 (so a_j ⟺ ⟨P,Lj⟩=1) and clause (a₁∨a₂∨...∨aₖ).

    If ``per_k_records`` is a list, append one dict per weight trial ``k`` with keys
    ``k``, ``sat``, ``time_sec``, ``nof_vars``, ``nof_clauses``, and clause-count fields.

    If ``setup_timing_out`` is a dict, it receives ``logical_basis_symplectic_sec`` (time for
    the symplectic logical basis, once per run, before the ``k`` loop).

    If ``logical_basis_override`` is set (rows of length ``2n``, symplectic coordinates), skip
    ``logical_basis_symplectic`` and use these operators (e.g. loaded from a precomputed file).
    """
    if CardEnc is None or EncType is None:
        raise ImportError("pysat.card (CardEnc) is required")

    m, cols = _matrix_shape(S)
    if m == 0 or cols % 2 != 0:
        if debug:
            print("[DEBUG] min_distance_quantum_stabilizer_or_logicals: invalid S -> None")
        return None
    n = cols // 2

    if max_distance is None:
        max_distance = n

    if encoding is None:
        encoding = EncType.seqcounter

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
        if debug:
            print("[DEBUG] No logical operators -> None")
        return None

    if is_maxsat_solver(solver_type):
        if cardinality_encoding == "log":
            raise ValueError(
                "MaxSAT distance search minimizes sum(w_i) directly; "
                "cardinality_encoding='log' does not apply to rc2-* solvers."
            )
        if per_k_records is not None:
            raise ValueError("per_k_records is not supported for MaxSAT (rc2-*) solvers.")
        return _min_distance_or_logicals_maxsat(
            S,
            solver_type,
            max_distance,
            logical_basis,
            n,
            m,
            debug=debug,
            show_formula=show_formula,
            stats=stats,
            timeout_sec=timeout_sec,
        )

    n_vars_xz = 2 * n
    w_start = n_vars_xz + 1
    a_start = w_start + n  # a_1, a_2, ..., a_k for k logicals
    top_id = a_start + len(logical_basis) - 1

    def _xor_clause_count(lits: List[int], value: bool) -> int:
        if solver_type in XOR_SUPPORTED_SOLVERS:
            return 1
        return tseitin_xor_clause_count(lits, value)

    run_lb = 1
    for k in range(1, max_distance + 1):
        t_k_start = time.perf_counter()
        if debug:
            print(f"[DEBUG] --- OR-logicals, trying weight k={k} ---")
        solver = get_solver(solver_type=solver_type)
        if show_formula:
            print(f"\n  --- OR-logicals, weight k={k} ---")
        c_comm, c_p0, c_log, c_wdef, c_card = 0, 0, 0, 0, 0
        next_id_ref = [top_id]

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
                if show_formula:
                    print(f"    P⊥S{j+1}:  {_lit_to_name(-lits[0], n, w_start)} = 0")
                continue
            _add_xor_clause(solver, lits, value=False, next_var_ref=next_id_ref)
            c_comm += _xor_clause_count(lits, False)
            if show_formula:
                names = [_lit_to_name(ℓ, n, w_start) for ℓ in lits]
                print(f"    P⊥S{j+1}:  XOR({', '.join(names)}) = 0")

        solver.add_clause(list(range(1, n_vars_xz + 1)))
        c_p0 = 1
        if show_formula:
            print(f"    P≠0:  (x1∨...∨xn∨z1∨...∨zn)")

        # ⟨P,Lj⟩=1 for at least one j: a_j ⟺ ⟨P,Lj⟩, then a_1 ∨ a_2 ∨ ... ∨ a_k
        for idx, L in enumerate(logical_basis):
            lits_L = [i + 1 for i in range(n) if L[n + i] % 2 == 1]
            lits_L += [n + 1 + i for i in range(n) if L[i] % 2 == 1]
            a_j = a_start + idx
            if lits_L:
                # XOR(lits_L, a_j) = 0  ⟺  ⟨P,L⟩ = a_j
                _add_xor_clause(
                    solver, lits_L + [a_j], value=False, next_var_ref=next_id_ref
                )
                c_log += _xor_clause_count(lits_L + [a_j], False)
                if show_formula:
                    names = [_lit_to_name(ℓ, n, w_start) for ℓ in lits_L]
                    print(f"    a{idx+1}⟺⟨P,L{idx}⟩:  XOR({', '.join(names)}, a{idx+1}) = 0")
            else:
                # L is zero vector (shouldn't happen for valid logical): ⟨P,L⟩=0 always
                solver.add_clause([-a_j])
                c_log += 1

        solver.add_clause(list(range(a_start, a_start + len(logical_basis))))
        c_log += 1
        if show_formula:
            print(f"    (a1∨a2∨...∨a{len(logical_basis)}): at least one ⟨P,Lj⟩=1")

        for i in range(n):
            xi, zi, wi = 1 + i, n + 1 + i, w_start + i
            solver.add_clause([-wi, xi, zi])
            solver.add_clause([-xi, wi])
            solver.add_clause([-zi, wi])
            if show_formula and i < 3:
                print(f"    w{i+1}=x{i+1}∨z{i+1}:  (¬w{i+1}∨x{i+1}∨z{i+1}) ∧ ...")
        c_wdef = 3 * n
        if show_formula and n > 3:
            print(f"    ... (w4..w{n} same pattern)")

        w_lits = list(range(w_start, w_start + n))
        t_pre_card = time.perf_counter()
        time_base_sec = t_pre_card - t_k_start
        c_card = _add_weight_atmost_k(
            solver,
            w_lits,
            k,
            solver_type,
            encoding,
            top_id,
            next_id_ref,
            cardinality_encoding=cardinality_encoding,
        )
        if show_formula:
            if cardinality_encoding == "log":
                print(f"    Σw_i ≤ k:  log selector encoding  # {c_card} clauses")
            elif c_card == 0:
                print(f"    Σw_i ≤ k:  native add_atmost")
            else:
                print(f"    Σw_i ≤ k:  CardEnc.atmost  # {c_card} clauses")

        t_after_card = time.perf_counter()
        time_cardenc_sec = t_after_card - t_pre_card
        build_time_sec = time_base_sec + time_cardenc_sec

        nv, nc = _solver_formula_stats(solver)
        t_solve = time.perf_counter()
        result = solver.solve()
        solve_sec = time.perf_counter() - t_solve
        if per_k_records is not None:
            bs = (
                _bounds_str_scan_lb_ub(k, k)
                if result
                else _bounds_str_scan_lb_ub(run_lb, None)
            )
            per_k_records.append(
                {
                    "k": k,
                    "sat": bool(result),
                    "time_base_sec": time_base_sec,
                    "time_cardenc_sec": time_cardenc_sec,
                    "build_time_sec": build_time_sec,
                    "time_sec": solve_sec,
                    "nof_vars": nv,
                    "nof_clauses": nc,
                    "clauses_commutation": c_comm,
                    "clauses_p_nonzero": c_p0,
                    "clauses_logical": c_log,
                    "clauses_weight_def": c_wdef,
                    "clauses_cardinality": c_card,
                    "bounds_str": bs,
                }
            )
        if not result:
            run_lb = k + 1
        _emit_scan_progress(
            progress_q,
            completed_k=k,
            sat=bool(result),
            run_lb=run_lb,
            nof_vars=nv,
            nof_clauses=nc,
        )
        if result and stats is not None:
            if nv is not None:
                stats["nof_vars"] = nv
            if nc is not None:
                stats["nof_clauses"] = nc
            stats["clauses_commutation"] = c_comm
            stats["clauses_p_nonzero"] = c_p0
            stats["clauses_logical"] = c_log
            stats["clauses_weight_def"] = c_wdef
            stats["clauses_cardinality"] = c_card
        solver.delete()
        if result:
            return k
    return None

def _min_distance_css_sector_or_logicals(
    H_parity: List[List[Union[int, float]]],
    logical_subset: List[List[int]],
    n: int,
    sector: str,
    solver_type: SolverType,
    max_distance: Optional[int],
    encoding: Any,
    *,
    debug: bool = False,
    show_formula: bool = False,
    stats: Optional[Dict[str, int]] = None,
    per_k_records: Optional[List[Dict[str, Any]]] = None,
    enable_stopping_closure: bool = False,
    enable_dynamic_deficit: bool = False,
    dynamic_block_limit: int = 5000,
) -> Optional[int]:
    """
    One CSS sector: n Boolean variables (Z-type bits if sector=='z' else X-type bits),
    commutation H_parity @ v = 0, OR-of-logicals on symplectic representatives in logical_subset,
    CardEnc.atmost on those n bits (no auxiliary w_i).
    """
    if CardEnc is None or EncType is None:
        raise ImportError("pysat.card (CardEnc) is required")
    if not logical_subset:
        return None
    m = len(H_parity)
    if m == 0 and n == 0:
        return None
    if max_distance is None:
        max_distance = n

    a_start = n + 1
    k_log = len(logical_subset)
    top_id = a_start + k_log - 1
    check_to_bits, bit_to_checks = tanner_neighbors(H_parity)

    def _xor_clause_count(lits: List[int], value: bool) -> int:
        if solver_type in XOR_SUPPORTED_SOLVERS:
            return 1
        return tseitin_xor_clause_count(lits, value)

    run_lb = 1
    for k in range(1, max_distance + 1):
        t_k_start = time.perf_counter()
        if debug:
            print(f"[DEBUG] css sector {sector}: try weight k={k}", flush=True)
        solver = get_solver(solver_type=solver_type)
        c_comm, c_p0, c_log, c_card = 0, 0, 0, 0
        next_id_ref = [top_id]

        for j in range(m):
            lits = [i + 1 for i in range(n) if int(H_parity[j][i]) % 2 == 1]
            if not lits:
                continue
            if len(lits) == 1:
                solver.add_clause([-lits[0]])
                c_comm += 1
                continue
            _add_xor_clause(solver, lits, value=False, next_var_ref=next_id_ref)
            c_comm += _xor_clause_count(lits, False)

        if enable_stopping_closure:
            # Stopping-set closure is globally implied by H_parity @ v = 0.
            # Adding it explicitly gives CDCL/unit propagation a shorter local
            # proof when a low-weight candidate leaves a singleton check.
            inject_stopping_set_closure(solver, check_to_bits, lambda i: i + 1)

        solver.add_clause(list(range(1, n + 1)))
        c_p0 = 1

        for idx, L in enumerate(logical_subset):
            if sector == "z":
                lits_L = [i + 1 for i in range(n) if L[i] % 2 == 1]
            else:
                lits_L = [i + 1 for i in range(n) if L[n + i] % 2 == 1]
            a_j = a_start + idx
            if lits_L:
                _add_xor_clause(
                    solver, lits_L + [a_j], value=False, next_var_ref=next_id_ref
                )
                c_log += _xor_clause_count(lits_L + [a_j], False)
            else:
                solver.add_clause([-a_j])
                c_log += 1

        solver.add_clause(list(range(a_start, a_start + k_log)))
        c_log += 1

        w_lits = list(range(1, n + 1))
        t_pre_card = time.perf_counter()
        time_base_sec = t_pre_card - t_k_start
        if solver_type in NATIVE_ONLY_CARD_SOLVERS:
            solver.add_atmost(w_lits, k)
        else:
            card = CardEnc.atmost(
                lits=w_lits, bound=k, top_id=next_id_ref[0], encoding=encoding
            )
            solver.add_clauses(card.clauses)
            c_card = len(card.clauses)
            if card.clauses:
                hi = max(abs(lit) for cl in card.clauses for lit in cl)
                next_id_ref[0] = max(next_id_ref[0], hi)

        if enable_dynamic_deficit:
            # This solver is rebuilt for each k, so direct blocking clauses are
            # safe: they only rule out supports that cannot close under |v| <= k.
            dynamic_deficit_blocking(
                solver,
                k + 1,
                check_to_bits,
                bit_to_checks,
                lambda i: i + 1,
                limit=dynamic_block_limit,
            )

        t_after_card = time.perf_counter()
        time_cardenc_sec = t_after_card - t_pre_card
        build_time_sec = time_base_sec + time_cardenc_sec

        nv, nc = _solver_formula_stats(solver)
        t_solve = time.perf_counter()
        result = solver.solve()
        solve_sec = time.perf_counter() - t_solve
        if per_k_records is not None:
            bs = (
                _bounds_str_scan_lb_ub(k, k)
                if result
                else _bounds_str_scan_lb_ub(run_lb, None)
            )
            per_k_records.append(
                {
                    "sector": sector,
                    "k": k,
                    "sat": bool(result),
                    "time_base_sec": time_base_sec,
                    "time_cardenc_sec": time_cardenc_sec,
                    "build_time_sec": build_time_sec,
                    "time_sec": solve_sec,
                    "nof_vars": nv,
                    "nof_clauses": nc,
                    "clauses_commutation": c_comm,
                    "clauses_p_nonzero": c_p0,
                    "clauses_logical": c_log,
                    "clauses_weight_def": 0,
                    "clauses_cardinality": c_card,
                    "bounds_str": bs,
                }
            )
        if not result:
            run_lb = k + 1
        if result and stats is not None:
            if nv is not None:
                stats["nof_vars"] = nv
            if nc is not None:
                stats["nof_clauses"] = nc
            stats["clauses_commutation"] = c_comm
            stats["clauses_p_nonzero"] = c_p0
            stats["clauses_logical"] = c_log
            stats["clauses_weight_def"] = 0
            stats["clauses_cardinality"] = c_card
        solver.delete()
        if result:
            return k
    return None


def _min_distance_css_sector_stepwise(
    H_parity: List[List[Union[int, float]]],
    logical_subset: List[List[int]],
    n: int,
    sector: str,
    solver_type: SolverType,
    max_distance: Optional[int],
    *,
    debug: bool = False,
    stats: Optional[Dict[str, int]] = None,
    per_k_records: Optional[List[Dict[str, Any]]] = None,
    enable_stopping_closure: bool = False,
    enable_dynamic_deficit: bool = False,
    dynamic_block_limit: int = 5000,
) -> Optional[int]:
    """
    Same semantics as _min_distance_css_sector_or_logicals but one solver + ITotalizer on
    the n sector bits; scan k with assumptions [-rhs[k]] (k < n) like stepwise_card.
    """
    if ITotalizer is None:
        return None
    if not logical_subset:
        return None
    m = len(H_parity)
    if max_distance is None:
        max_distance = n

    a_start = n + 1
    k_log = len(logical_subset)
    top_id = a_start + k_log - 1
    bit_lits = list(range(1, n + 1))
    check_to_bits, bit_to_checks = tanner_neighbors(H_parity)

    def _xor_clause_count(lits: List[int], value: bool) -> int:
        if solver_type in XOR_SUPPORTED_SOLVERS:
            return 1
        return tseitin_xor_clause_count(lits, value)

    t_build_start = time.perf_counter()
    solver = get_solver(solver_type=solver_type)
    c_comm, c_p0, c_log = 0, 0, 0
    next_id_ref = [top_id]

    for j in range(m):
        lits = [i + 1 for i in range(n) if int(H_parity[j][i]) % 2 == 1]
        if not lits:
            continue
        if len(lits) == 1:
            solver.add_clause([-lits[0]])
            c_comm += 1
            continue
        _add_xor_clause(solver, lits, value=False, next_var_ref=next_id_ref)
        c_comm += _xor_clause_count(lits, False)

    if enable_stopping_closure:
        inject_stopping_set_closure(solver, check_to_bits, lambda i: i + 1)

    solver.add_clause(list(range(1, n + 1)))
    c_p0 = 1

    for idx, L in enumerate(logical_subset):
        if sector == "z":
            lits_L = [i + 1 for i in range(n) if L[i] % 2 == 1]
        else:
            lits_L = [i + 1 for i in range(n) if L[n + i] % 2 == 1]
        a_j = a_start + idx
        if lits_L:
            _add_xor_clause(
                solver,
                lits_L + [a_j],
                value=False,
                next_var_ref=next_id_ref,
            )
            c_log += _xor_clause_count(lits_L + [a_j], False)
        else:
            solver.add_clause([-a_j])
            c_log += 1

    solver.add_clause(list(range(a_start, a_start + k_log)))
    c_log += 1

    tot = ITotalizer(lits=bit_lits, ubound=n, top_id=next_id_ref[0])
    for cl in tot.cnf.clauses:
        solver.add_clause(cl)

    if stats is not None:
        stats["css_sector_totalizer_clauses"] = len(tot.cnf.clauses)

    build_time_sec = time.perf_counter() - t_build_start
    c_card = len(tot.cnf.clauses)
    c_dynamic = 0
    gate_hi = max(
        [next_id_ref[0], *[abs(lit) for cl in tot.cnf.clauses for lit in cl]],
        default=next_id_ref[0],
    )

    run_lb = 1
    for k in range(1, max_distance + 1):
        if debug:
            print(f"[DEBUG] css sector {sector} stepwise: k={k}", flush=True)
        assumptions: List[int] = []
        if enable_dynamic_deficit:
            # Dynamic deficit clauses are valid only for this bound. Guard them
            # with a fresh activation literal so later, larger bounds are not
            # accidentally constrained by an old round's blockers.
            gate_hi += 1
            round_gate = gate_hi
            added_dynamic = dynamic_deficit_blocking(
                solver,
                k + 1,
                check_to_bits,
                bit_to_checks,
                lambda i: i + 1,
                activation_lit=round_gate,
                limit=dynamic_block_limit,
            )
            c_dynamic += added_dynamic
            if added_dynamic:
                assumptions.append(round_gate)
        nv, nc = _solver_formula_stats(solver)
        t_solve = time.perf_counter()
        if k < n:
            result = solver.solve(assumptions=assumptions + [-tot.rhs[k]])
        else:
            result = solver.solve(assumptions=assumptions)
        solve_sec = time.perf_counter() - t_solve
        if result:
            nv, nc = _solver_formula_stats(solver)
        if k == 1:
            tb, te, bld = build_time_sec, 0.0, build_time_sec
        else:
            tb, te, bld = 0.0, 0.0, 0.0
        bs = (
            _bounds_str_scan_lb_ub(k, k)
            if result
            else _bounds_str_scan_lb_ub(run_lb, None)
        )
        _append_per_k_row(
            per_k_records,
            {
                "sector": sector,
                "k": k,
                "sat": bool(result),
                "time_base_sec": tb,
                "time_cardenc_sec": te,
                "build_time_sec": bld,
                "time_sec": solve_sec,
                "nof_vars": nv,
                "nof_clauses": nc,
                "clauses_commutation": c_comm,
                "clauses_p_nonzero": c_p0,
                "clauses_logical": c_log,
                "clauses_weight_def": 0,
                "clauses_cardinality": c_card,
                "clauses_dynamic_deficit": c_dynamic,
                "bounds_str": bs,
            },
        )
        if not result:
            run_lb = k + 1
        if result:
            if stats is not None:
                if nv is not None:
                    stats["nof_vars"] = nv
                if nc is not None:
                    stats["nof_clauses"] = nc
                stats["clauses_commutation"] = c_comm
                stats["clauses_p_nonzero"] = c_p0
                stats["clauses_logical"] = c_log
                stats["clauses_weight_def"] = 0
                stats["clauses_cardinality"] = c_card
                stats["clauses_dynamic_deficit"] = c_dynamic
            tot.delete()
            solver.delete()
            return k

    tot.delete()
    solver.delete()
    return None

def min_distance_quantum_stabilizer_stepwise_card(
    S: List[List[Union[int, float]]],
    solver_type: SolverType = SolverType.GLUCOSE3,
    max_distance: Optional[int] = None,
    *,
    debug: bool = False,
    stats: Optional[Dict[str, int]] = None,
    per_k_records: Optional[List[Dict[str, Any]]] = None,
    setup_timing_out: Optional[Dict[str, float]] = None,
    logical_basis_override: Optional[List[List[int]]] = None,
) -> Optional[int]:
    """
    Same objective as min_distance_quantum_stabilizer_or_logicals (card): minimum k with
    a satisfying assignment under Σ w_i ≤ k.

    Instead of rebuilding the whole formula for each k, this builds the stabilizer / XOR /
    logical / w-definition clauses once, then adds an *iterative totalizer* (ITotalizer)
    on w_1..w_n once. Each bound k is tested with solve(assumptions=[-tot.rhs[k]]) — no
    full-model blocking clauses, and no CardEnc rebuild per k (see PySAT LSU / CP'14).

    Solvers with native add_atmost fall back to the standard card loop (same as or_logicals).

    If ITotalizer is unavailable (old PySAT), falls back to min_distance_quantum_stabilizer_or_logicals.

    If ``per_k_records`` is set, appends one row per trial ``k`` (same keys as ``or_logicals``;
    ``time_base_sec`` / ``build_time_sec`` are nonzero only on ``k==1`` — one-time build).
    """
    if CardEnc is None or EncType is None:
        raise ImportError("pysat.card (CardEnc) is required")

    if solver_type in CARD_SUPPORTED_SOLVERS:
        return min_distance_quantum_stabilizer_or_logicals(
            S,
            solver_type=solver_type,
            max_distance=max_distance,
            debug=debug,
            stats=stats,
            encoding=EncType.seqcounter,
            per_k_records=per_k_records,
            setup_timing_out=setup_timing_out,
            logical_basis_override=logical_basis_override,
        )

    if ITotalizer is None:
        return min_distance_quantum_stabilizer_or_logicals(
            S,
            solver_type=solver_type,
            max_distance=max_distance,
            debug=debug,
            stats=stats,
            encoding=EncType.seqcounter,
            per_k_records=per_k_records,
            setup_timing_out=setup_timing_out,
            logical_basis_override=logical_basis_override,
        )

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

    def _xor_clause_count(lits: List[int], value: bool) -> int:
        if solver_type in XOR_SUPPORTED_SOLVERS:
            return 1
        return tseitin_xor_clause_count(lits, value)

    ubound = n
    t_build_start = time.perf_counter()
    c_comm, c_p0, c_log, c_wdef = 0, 0, 0, 0
    solver = get_solver(solver_type=solver_type)
    next_id_ref = [top_id]

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
        _add_xor_clause(solver, lits, value=False, next_var_ref=next_id_ref)
        c_comm += _xor_clause_count(lits, False)

    solver.add_clause(list(range(1, n_vars_xz + 1)))
    c_p0 = 1

    for idx, L in enumerate(logical_basis):
        lits_L = [i + 1 for i in range(n) if L[n + i] % 2 == 1]
        lits_L += [n + 1 + i for i in range(n) if L[i] % 2 == 1]
        a_j = a_start + idx
        if lits_L:
            _add_xor_clause(
                solver,
                lits_L + [a_j],
                value=False,
                next_var_ref=next_id_ref,
            )
            c_log += _xor_clause_count(lits_L + [a_j], False)
        else:
            solver.add_clause([-a_j])
            c_log += 1

    solver.add_clause(list(range(a_start, a_start + len(logical_basis))))
    c_log += 1

    for i in range(n):
        xi, zi, wi = 1 + i, n + 1 + i, w_start + i
        solver.add_clause([-wi, xi, zi])
        solver.add_clause([-xi, wi])
        solver.add_clause([-zi, wi])
    c_wdef = 3 * n

    tot = ITotalizer(lits=w_lits, ubound=ubound, top_id=next_id_ref[0])
    for cl in tot.cnf.clauses:
        solver.add_clause(cl)
    c_card = len(tot.cnf.clauses)

    t_build_end = time.perf_counter()
    build_time_sec = t_build_end - t_build_start

    if stats is not None:
        stats["totalizer_clauses"] = len(tot.cnf.clauses)
        stats["stepwise_ubound"] = ubound

    # ITotalizer: -rhs[j] enforces Σ w_i ≤ j for j < n; for k == n the bound is vacuous (plain solve).
    run_lb = 1
    for k in range(1, max_distance + 1):
        if debug:
            print(f"[DEBUG] stepwise_card: try k={k}", flush=True)
        nv, nc = _solver_formula_stats(solver)
        t_solve = time.perf_counter()
        if k < n:
            result = solver.solve(assumptions=[-tot.rhs[k]])
        else:
            result = solver.solve()
        solve_sec = time.perf_counter() - t_solve
        if k == 1:
            time_base_sec = build_time_sec
            time_cardenc_sec = 0.0
            bld = build_time_sec
        else:
            time_base_sec = 0.0
            time_cardenc_sec = 0.0
            bld = 0.0
        bs = (
            _bounds_str_scan_lb_ub(k, k)
            if result
            else _bounds_str_scan_lb_ub(run_lb, None)
        )
        _append_per_k_row(
            per_k_records,
            {
                "k": k,
                "sat": bool(result),
                "time_base_sec": time_base_sec,
                "time_cardenc_sec": time_cardenc_sec,
                "build_time_sec": bld,
                "time_sec": solve_sec,
                "nof_vars": nv,
                "nof_clauses": nc,
                "clauses_commutation": c_comm,
                "clauses_p_nonzero": c_p0,
                "clauses_logical": c_log,
                "clauses_weight_def": c_wdef,
                "clauses_cardinality": c_card,
                "bounds_str": bs,
            },
        )
        if not result:
            run_lb = k + 1
        if result:
            if stats is not None:
                try:
                    stats["nof_vars"] = solver.nof_vars()
                    stats["nof_clauses"] = solver.nof_clauses()
                except Exception:
                    pass
            tot.delete()
            solver.delete()
            return k

    tot.delete()
    solver.delete()
    return None

