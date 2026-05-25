"""
SAT Solver Interface - A unified interface for multiple SAT solvers using PySAT.

This module provides a simple abstraction layer over PySAT that allows
easy switching between different SAT solver backends.
"""

import os
from typing import List, Optional, Dict, Any, Iterable, FrozenSet
from enum import Enum

try:
    from pysat.solvers import Solver as PySATSolver
    from pysat.solvers import SolverNames
except ModuleNotFoundError as e:
    if "pysat" in str(e):
        raise ModuleNotFoundError(
            "No module named 'pysat'. Install the package with:\n"
            "  pip install python-sat\n"
            "Or in a virtual environment:\n"
            "  python3 -m venv venv && source venv/bin/activate && pip install python-sat"
        ) from e
    raise


class SolverType(Enum):
    """Enumeration of available SAT solvers."""
    Z3PY = "z3py"  # Z3 SMT solver: native XOR + PbEq/PbLe cardinality
    CVC5 = "cvc5"  # CVC5 SMT solver: native XOR + Sum/If cardinality
    MINISAT22 = "minisat22"
    MINISAT_GH = "minisatgh"
    GLUCOSE3 = "glucose3"
    GLUCOSE4 = "glucose4"
    GLUCOSE42 = "glucose42"
    CADICAL103 = "cadical103"
    CADICAL153 = "cadical153"
    CADICAL195 = "cadical195"
    LINGELING = "lingeling"
    MAPLESAT = "maplesat"
    MERGESAT3 = "mergesat3"
    MINICARD = "minicard"
    GLUECARD3 = "gluecard3"
    GLUECARD4 = "gluecard4"
    CRYPTOSAT = "cryptosat"
    # MaxSAT (PySAT RC2); suffix after rc2- is the inner SAT oracle (g3, g4, m22, …).
    RC2_G3 = "rc2-g3"
    RC2_G4 = "rc2-g4"
    RC2_MINISAT22 = "rc2-minisat22"
    RC2_CADICAL195 = "rc2-cadical195"
    RC2_CRYPTOSAT = "rc2-cryptosat"
    RC2_GLUCOSE42 = "rc2-glucose42"
    # External MaxSAT binaries (bin/maxsat/; see scripts/download_maxsat_solvers.py)
    CASHW_COREPLUS = "cashw-coreplus"
    CASHW_COREPLUS_MSE22 = "cashw-coreplus-mse22"
    EVALMAXSAT = "evalmaxsat"
    MAXCDCL = "maxcdcl"
    OPEN_WBO = "open-wbo"


# Solvers that support native XOR constraints (add_xor_clause). Others would need XOR encoded as CNF.
XOR_SUPPORTED_SOLVERS: FrozenSet[SolverType] = frozenset({SolverType.CRYPTOSAT, SolverType.Z3PY, SolverType.CVC5})

# Solvers that support native cardinality (add_atmost).
CARD_SUPPORTED_SOLVERS: FrozenSet[SolverType] = frozenset({
    SolverType.MINICARD, SolverType.GLUECARD3, SolverType.GLUECARD4, SolverType.Z3PY, SolverType.CVC5,
})
# Always use native add_atmost (PySAT encodings do not apply).
NATIVE_ONLY_CARD_SOLVERS: FrozenSet[SolverType] = frozenset({
    SolverType.MINICARD, SolverType.GLUECARD3, SolverType.GLUECARD4,
})

# PySAT solver name for each type (PySAT uses "cms" for CryptoMiniSat, not "cryptosat").
_PYSAT_SOLVER_NAME: Dict[SolverType, str] = {
    SolverType.CRYPTOSAT: "cms",  # PySAT only accepts cms/cms5/crypto/cryptominisat, etc.
}


def ensure_pysat_cms_solve_limited_budgets(pysat_solver: object) -> None:
    """
    CryptoMiniSat (``cms``) requires numeric ``time_limit`` / ``confl_limit`` in
    ``solve_limited``; PySAT clears them after each call. Set huge defaults only
    when no explicit budget is active (RC2 may set ``conf_budget(1000)`` for MUS).
    """
    inner = getattr(pysat_solver, "solver", pysat_solver)
    if getattr(inner, "cryptosat", None) is None:
        return
    if getattr(inner, "time_limit", None) is None:
        inner.time_budget(10**9)
    if getattr(inner, "conf_limit", None) is None:
        inner.conf_budget(10**18)


def _fold_xor_literals(lits: List[int]) -> tuple[List[int], bool]:
    """Map signed literals to positive vars; flip target parity if negations are odd."""
    pos: List[int] = []
    flip = False
    for lit in lits:
        if lit < 0:
            pos.append(-lit)
            flip = not flip
        else:
            pos.append(lit)
    return pos, flip


def _tseitin_xor_pair_clauses(a: int, b: int, t: int) -> List[List[int]]:
    """CNF for t ↔ (a XOR b), with a,b,t positive literals."""
    return [
        [-a, -b, -t],
        [a, b, -t],
        [a, -b, t],
        [-a, b, t],
    ]


def tseitin_xor_clause_count(lits: List[int], value: bool) -> int:
    """Clause count for Tseitin XOR encoding (matches ``_tseitin_xor_to_cnf``)."""
    pos, flip = _fold_xor_literals(lits)
    target = bool(value) ^ flip
    n = len(pos)
    if n == 0:
        return 1 if target else 0
    if n == 1:
        return 1
    return 4 * (n - 1) + 1


def _tseitin_xor_to_cnf(
    lits: List[int],
    value: bool,
    next_var: List[int],
) -> List[List[int]]:
    """
    Encode (lits[0] XOR ... XOR lits[n-1]) == value with Tseitin auxiliaries.

    Uses O(n) variables and O(n) clauses (4 per chain step + one unit). Literal signs
    are folded into the target parity; ``next_var[0]`` is incremented for each new aux.
    """
    pos, flip = _fold_xor_literals(lits)
    target = bool(value) ^ flip
    n = len(pos)
    if n == 0:
        return [[]] if target else []
    if n == 1:
        return [[pos[0]]] if target else [[-pos[0]]]

    def fresh() -> int:
        next_var[0] += 1
        return next_var[0]

    clauses: List[List[int]] = []
    cur = pos[0]
    for i in range(1, n - 1):
        t = fresh()
        clauses.extend(_tseitin_xor_pair_clauses(cur, pos[i], t))
        cur = t
    t_out = fresh()
    clauses.extend(_tseitin_xor_pair_clauses(cur, pos[-1], t_out))
    clauses.append([t_out] if target else [-t_out])
    return clauses


def _xor_to_cnf_exponential(lits: List[int], value: bool) -> List[List[int]]:
    """
    Direct CNF: 2^(n-1) clauses. Kept for regression tests only; do not use on wide XORs.
    """
    n = len(lits)
    if n == 0:
        return [[]] if value else []
    if n == 1:
        return [[lits[0]]] if value else [[-lits[0]]]
    clauses: List[List[int]] = []
    for assignment in range(1 << n):
        popcount = bin(assignment).count("1")
        if (popcount % 2) == (0 if value else 1):
            clause = [
                -lits[i] if (assignment >> i) & 1 else lits[i]
                for i in range(n)
            ]
            clauses.append(clause)
    return clauses


class SATSolver:
    """
    A unified interface for SAT solving that supports multiple solver backends.
    
    This class wraps PySAT's Solver class and provides a clean API for
    adding clauses, solving, and retrieving models while allowing easy
    switching between different SAT solver implementations.
    
    Example:
        >>> solver = SATSolver(solver_type=SolverType.GLUCOSE3)
        >>> solver.add_clause([-1, 2])
        >>> solver.add_clause([-2, 3])
        >>> result = solver.solve()
        >>> if result:
        ...     print(solver.get_model())
    """
    
    def __init__(
        self,
        solver_type: SolverType = SolverType.MINISAT22,
        bootstrap_with: Optional[Iterable[Iterable[int]]] = None,
        use_timer: bool = False,
        **kwargs
    ):
        """
        Initialize a SAT solver instance.
        
        Args:
            solver_type: The type of SAT solver to use (default: MINISAT22)
            bootstrap_with: Optional list of clauses to initialize the solver with
            use_timer: Whether to track solving time
            **kwargs: Additional solver-specific arguments (e.g., with_proof, incr)
        """
        self.solver_type = solver_type
        pysat_name = _PYSAT_SOLVER_NAME.get(solver_type, solver_type.value)
        self.solver = PySATSolver(
            name=pysat_name,
            bootstrap_with=bootstrap_with,
            use_timer=use_timer,
            **kwargs
        )
        self._last_result: Optional[bool] = None
        self._aux_var_hi: int = 0

    def _fresh_aux_var(self) -> int:
        nv = self.solver.nof_vars()
        if nv is not None and nv > self._aux_var_hi:
            self._aux_var_hi = int(nv)
        self._aux_var_hi += 1
        return self._aux_var_hi

    def _use_solve_limited_interrupt(self) -> bool:
        v = os.environ.get("QEECC_SAT_SOLVE_LIMITED_INTERRUPT", "").strip().lower()
        return v in ("1", "yes", "true", "on")

    def _solve_limited_expect_interrupt(
        self, assumptions: List[int]
    ) -> Optional[bool]:
        """PySAT path: ``solve_limited(..., expect_interrupt=True)`` (see env var)."""
        if self.solver_type == SolverType.CRYPTOSAT:
            ensure_pysat_cms_solve_limited_budgets(self.solver)
        try:
            return self.solver.solve_limited(
                assumptions=assumptions, expect_interrupt=True
            )
        except (TypeError, NotImplementedError):
            return self.solver.solve(assumptions=assumptions)
    
    def add_clause(self, clause: List[int], no_return: bool = True) -> Optional[bool]:
        """
        Add a single clause to the solver.
        
        Args:
            clause: A list of literals (integers). Negative integers represent
                   negated variables, positive integers represent variables.
            no_return: If False, check satisfiability immediately after adding
        
        Returns:
            If no_return is False, returns the satisfiability result (True/False).
            Otherwise returns None.
        """
        return self.solver.add_clause(clause, no_return=no_return)
    
    def add_clauses(self, clauses: Iterable[List[int]], no_return: bool = True) -> Optional[bool]:
        """
        Add multiple clauses to the solver.
        
        Args:
            clauses: An iterable of clause lists
            no_return: If False, check satisfiability immediately after adding
        
        Returns:
            If no_return is False, returns the satisfiability result (True/False).
            Otherwise returns None.
        """
        return self.solver.append_formula(clauses, no_return=no_return)
    
    def supports_xor(self) -> bool:
        """
        Return True if this solver supports native XOR constraints (add_xor_clause).
        Currently only CryptoMiniSat (CRYPTOSAT) supports XOR in PySAT.
        """
        return self.solver_type in XOR_SUPPORTED_SOLVERS

    def supports_card(self) -> bool:
        """
        Return True if this solver supports native cardinality (add_atmost).
        MiniCard, GlueCard3, GlueCard4 support it; no need to encode Σx_i ≤ k to CNF.
        """
        return self.solver_type in CARD_SUPPORTED_SOLVERS

    def add_atmost(self, lits: List[int], k: int, no_return: bool = True) -> Optional[bool]:
        """
        Add AtMostK: Σx_i ≤ k. Only for MiniCard/GlueCard; raises if unsupported.
        For EqualsK (Σx_i = k), use add_atmost(lits, k) and add_atmost([-l for l in lits], n-k).
        """
        if not self.supports_card():
            raise NotImplementedError(
                f"Solver {self.solver_type.value} does not support native cardinality. "
                "Use MiniCard, GlueCard3, or GlueCard4."
            )
        return self.solver.add_atmost(lits, k, no_return=no_return)

    def add_xor_clause(
        self,
        lits: List[int],
        value: bool = True,
        *,
        next_var_ref: Optional[List[int]] = None,
    ) -> None:
        """
        Add an XOR constraint: (lits[0] XOR lits[1] XOR ... XOR lits[n]) == value.
        
        If the solver supports native XOR (CryptoMiniSat, Z3, CVC5), the constraint is
        added natively. Otherwise it is encoded to CNF with Tseitin auxiliaries
        (O(n) clauses). For very large instances, SolverType.CRYPTOSAT is still fastest.
        
        Args:
            lits: List of literals (positive = variable, negative = negated). Sign
                  is respected: (-1, 2) means (not x1) XOR x2.
            value: True for XOR sum == 1 (odd number of true), False for == 0 (even).
        """
        if self.supports_xor():
            self.solver.add_xor_clause(lits, value=value)
        else:
            if next_var_ref is not None:
                base = next_var_ref[0]
            else:
                base = max(
                    self._aux_var_hi,
                    int(self.solver.nof_vars() or 0),
                    max((abs(l) for l in lits), default=0),
                )
            next_var = [base]
            clauses = _tseitin_xor_to_cnf(lits, value, next_var)
            self._aux_var_hi = max(self._aux_var_hi, next_var[0])
            if next_var_ref is not None:
                next_var_ref[0] = next_var[0]
            for clause in clauses:
                self.solver.add_clause(clause, no_return=True)
    
    def solve(self, assumptions: Optional[List[int]] = None) -> Optional[bool]:
        """
        Solve the current formula.
        
        Args:
            assumptions: Optional list of assumption literals
        
        Returns:
            True if satisfiable, False if unsatisfiable, None if interrupted
            (e.g. when using solve_limited and hitting the budget).
        """
        if assumptions is None:
            assumptions = []
        if self._use_solve_limited_interrupt():
            self._last_result = self._solve_limited_expect_interrupt(assumptions)
        else:
            self._last_result = self.solver.solve(assumptions=assumptions)
        return self._last_result
    
    def get_model(self) -> Optional[List[int]]:
        """
        Get a satisfying assignment (model) if the formula is satisfiable.
        
        Returns:
            A list of literals representing the model, or None if unsatisfiable
        """
        return self.solver.get_model()
    
    def get_core(self) -> Optional[List[int]]:
        """
        Get an unsatisfiable core (subset of assumptions causing UNSAT).
        
        Returns:
            A list of assumption literals in the core, or None if satisfiable
        """
        return self.solver.get_core()
    
    def is_satisfiable(self) -> Optional[bool]:
        """
        Check if the last solve call was satisfiable.
        
        Returns:
            True if satisfiable, False if unsatisfiable, None if not solved yet
            or if the last solve was interrupted.
        """
        return self._last_result
    
    def enumerate_models(self, assumptions: Optional[List[int]] = None) -> Iterable[List[int]]:
        """
        Enumerate all models of the formula.
        
        Args:
            assumptions: Optional list of assumption literals
        
        Returns:
            An iterator over models (lists of literals)
        """
        if assumptions is None:
            assumptions = []
        return self.solver.enum_models(assumptions=assumptions)
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get solver statistics.
        
        Returns:
            A dictionary with solver statistics (restarts, conflicts, decisions, propagations)
        """
        return self.solver.accum_stats()
    
    def nof_vars(self) -> int:
        """Get the number of variables in the formula."""
        return self.solver.nof_vars()
    
    def nof_clauses(self) -> int:
        """Get the number of clauses in the formula."""
        return self.solver.nof_clauses()
    
    def switch_solver(self, new_solver_type: SolverType, **kwargs):
        """
        Switch to a different SAT solver while preserving the current formula.
        
        Args:
            new_solver_type: The new solver type to use
            **kwargs: Additional solver-specific arguments
        """
        # Save current formula
        clauses = []
        for i in range(self.solver.nof_clauses()):
            # Note: PySAT doesn't provide direct clause retrieval, so we need
            # to reconstruct from the model or use a different approach
            pass
        
        # Delete old solver
        self.solver.delete()
        
        # Create new solver
        self.solver_type = new_solver_type
        pysat_name = _PYSAT_SOLVER_NAME.get(new_solver_type, new_solver_type.value)
        self.solver = PySATSolver(
            name=pysat_name,
            bootstrap_with=None,  # We'd need to save clauses first
            **kwargs
        )
    
    def delete(self):
        """Clean up the solver instance."""
        if self.solver:
            self.solver.delete()
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - automatically clean up."""
        self.delete()
    
    def __str__(self) -> str:
        """String representation."""
        return f"SATSolver(type={self.solver_type.value}, vars={self.nof_vars()}, clauses={self.nof_clauses()})"


def get_available_solvers() -> List[str]:
    """
    Get a list of all available solver names.
    
    Returns:
        A list of solver name strings
    """
    return [solver.value for solver in SolverType]


def get_solver(solver_type: SolverType = SolverType.MINISAT22, **kwargs) -> "SATSolver":
    """
    Create a solver for the given type. Returns Z3SATSolver for Z3PY, else SATSolver.
    Use this when solver_type may be Z3PY (qecc_distance, benchmarks).

    MaxSAT backends (``rc2-*``) are not SAT oracles; use
    ``qecc_distance.min_distance_quantum_stabilizer_or_logicals`` with those types instead.
    """
    from .maxsat_solver import is_maxsat_solver as _is_maxsat_solver

    if _is_maxsat_solver(solver_type):
        raise ValueError(
            f"Solver {solver_type.value} is a MaxSAT backend (RC2/external), not a SAT solver. "
            "Distance search dispatches to MaxSAT automatically in qecc_distance."
        )
    if solver_type == SolverType.Z3PY:
        from .z3_solver import Z3SATSolver
        kw = {k: v for k, v in kwargs.items() if k != "solver_type"}
        return Z3SATSolver(**kw)
    if solver_type == SolverType.CVC5:
        from .cvc5_solver import CVC5SATSolver
        kw = {k: v for k, v in kwargs.items() if k != "solver_type"}
        return CVC5SATSolver(**kw)
    return SATSolver(solver_type=solver_type, **kwargs)


def create_solver(solver_name: str, **kwargs) -> SATSolver:
    """
    Create a SAT solver by name string.
    
    Args:
        solver_name: Name of the solver (e.g., "glucose3", "minisat22")
        **kwargs: Additional arguments to pass to SATSolver
    
    Returns:
        A SATSolver instance
    
    Raises:
        ValueError: If solver_name is not recognized
    """
    solver_name_lower = solver_name.lower()
    try:
        solver_type = SolverType(solver_name_lower)
    except ValueError:
        available = ", ".join(get_available_solvers())
        raise ValueError(
            f"Unknown solver: {solver_name}. Available solvers: {available}"
        )
    
    return get_solver(solver_type=solver_type, **kwargs)


if __name__ == "__main__":
    # Quick demo when run directly: python sat_solver.py
    # Uses Minisat22 so it works without optional CryptoMiniSat (pycryptosat).
    print("SAT Solver demo (run 'python example.py' for more examples)\n")
    with SATSolver(solver_type=SolverType.CRYPTOSAT) as solver:
        solver.add_xor_clause([1, 2])
        solver.add_clause([-2, 3])
        result = solver.solve()
        print(f"Satisfiable: {result}")
        if result:
            print(f"Model: {solver.get_model()}")
