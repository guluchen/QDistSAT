"""
Z3Py SAT Solver Interface - Uses Z3 SMT solver with native XOR and cardinality.

Z3 handles XOR and cardinality constraints differently from PySAT:
- XOR: Native z3.Xor() - no CNF blow-up
- Cardinality: Native z3.PbEq / PbLe / PbGe (pseudo-boolean) - no CardEnc encoding

This provides the same API as sat_solver.SATSolver for drop-in replacement.
"""

from typing import List, Optional, Dict, Any, Iterable

try:
    from z3 import Solver, Bool, Xor, Or, Not, Sum, If, PbEq, PbLe, PbGe, sat, unsat
except ImportError as e:
    err = str(e)
    if "pkg_resources" in err:
        raise ImportError(
            "Z3 needs pkg_resources. Install: pip install pkg-resources-backport"
        ) from e
    if "z3" not in err.lower():
        raise  # re-raise if it's some other import error
    raise ImportError(
        "Z3 required. Install: pip install z3-solver"
    ) from e


class Z3SATSolver:
    """
    SAT solver interface using Z3 with native XOR and cardinality constraints.

    Uses 1-based literals (same as PySAT): positive = variable true, negative = negated.
    Z3 handles XOR natively (no 2^n CNF expansion) and cardinality via PbEq/PbLe.
    """

    def __init__(self, bootstrap_with: Optional[Iterable[Iterable[int]]] = None, **kwargs):
        """
        Initialize Z3 solver.

        Args:
            bootstrap_with: Optional list of clauses to add initially
            **kwargs: Ignored (for API compatibility with SATSolver)
        """
        self.solver = Solver()
        self._vars: Dict[int, Any] = {}  # var_id -> z3.Bool
        self._nof_vars = 0
        self._nof_clauses = 0
        self._last_result: Optional[bool] = None

        if bootstrap_with:
            for clause in bootstrap_with:
                self.add_clause(list(clause))

    def _get_var(self, var_id: int):
        """Get or create Z3 Bool for variable (1-based)."""
        if var_id not in self._vars:
            self._vars[var_id] = Bool(f"x{var_id}")
            self._nof_vars = max(self._nof_vars, var_id)
        return self._vars[var_id]

    def _lit_to_z3(self, lit: int):
        """Convert literal (1-based) to Z3 expression."""
        var = self._get_var(abs(lit))
        return var if lit > 0 else Not(var)

    def add_clause(self, clause: List[int], no_return: bool = True) -> Optional[bool]:
        """Add clause: (l1 or l2 or ... or ln)."""
        if not clause:
            self.solver.add(False)  # empty clause = UNSAT
            self._nof_clauses += 1
            return False
        z3_expr = Or(*[self._lit_to_z3(lit) for lit in clause])
        self.solver.add(z3_expr)
        self._nof_clauses += 1
        return None

    def add_clauses(self, clauses: Iterable[List[int]], no_return: bool = True) -> Optional[bool]:
        """Add multiple clauses."""
        for clause in clauses:
            self.add_clause(clause, no_return)
        return None

    def supports_xor(self) -> bool:
        """Z3 supports native XOR."""
        return True

    def supports_card(self) -> bool:
        """Z3 supports native cardinality via PbEq/PbLe."""
        return True

    def add_atmost(self, lits: List[int], k: int, no_return: bool = True) -> Optional[bool]:
        """
        Add AtMostK: at most k of the literals can be true.
        For lits=[1,2,3], k=2: at most 2 of x1,x2,x3 true.
        For lits=[-1,-2,-3], k=1: at most 1 of (not x1, not x2, not x3) true = at least 2 of x1,x2,x3 true.
        """
        if not lits:
            return None
        negated = all(x < 0 for x in lits)
        z3_vars = [self._get_var(abs(x)) for x in lits]
        if negated:
            # at most k of (not v_i) true  <=>  at least n-k of v_i true  <=>  PbGe
            self.solver.add(PbGe([(v, 1) for v in z3_vars], len(lits) - k))
        else:
            self.solver.add(PbLe([(v, 1) for v in z3_vars], k))
        self._nof_clauses += 1
        return None

    def _xor_tree(self, exprs: List[Any]) -> Any:
        """Build balanced XOR tree (Z3 Xor takes only 2 args)."""
        if len(exprs) == 1:
            return exprs[0]
        if len(exprs) == 2:
            return Xor(exprs[0], exprs[1])
        mid = len(exprs) // 2
        return Xor(self._xor_tree(exprs[:mid]), self._xor_tree(exprs[mid:]))

    def add_xor_clause(self, lits: List[int], value: bool = True) -> None:
        """Add XOR constraint: (l1 XOR l2 XOR ... XOR ln) == value. Uses native z3.Xor."""
        if not lits:
            if value:
                self.solver.add(False)
                self._nof_clauses += 1
            return
        if len(lits) == 1:
            z3_expr = self._lit_to_z3(lits[0])
            self.solver.add(z3_expr == value)
            self._nof_clauses += 1
            return
        z3_lits = [self._lit_to_z3(lit) for lit in lits]
        self.solver.add(self._xor_tree(z3_lits) == value)
        self._nof_clauses += 1

    def add_equals_card(self, lits: List[int], k: int) -> None:
        """
        Add cardinality equals: exactly k of lits are true.
        Uses PbEq. For compatibility with CardEnc.equals usage.
        """
        if not lits:
            if k != 0:
                self.solver.add(False)
            return
        z3_vars = [self._get_var(abs(x)) for x in lits]
        self.solver.add(PbEq([(v, 1) for v in z3_vars], k))
        self._nof_clauses += 1

    def solve(self, assumptions: Optional[List[int]] = None) -> Optional[bool]:
        """Solve. Returns True if SAT, False if UNSAT, None if interrupted."""
        if assumptions:
            self.solver.push()
            for lit in assumptions:
                self.solver.add(self._lit_to_z3(lit))
        try:
            result = self.solver.check()
            if result == sat:
                self._last_result = True
            elif result == unsat:
                self._last_result = False
            else:
                self._last_result = None  # unknown
        except Exception:
            self._last_result = None
        finally:
            if assumptions:
                self.solver.pop()
        return self._last_result

    def _solve_result(self):
        """Get check() result - sat/unsat/unknown."""
        return self.solver.check()

    def get_model(self) -> Optional[List[int]]:
        """Return model as list of literals (1-based)."""
        m = self.solver.model()
        if m is None:
            return None
        result = []
        for var_id, z3_var in self._vars.items():
            try:
                val = m.eval(z3_var)
                if str(val) == "True":
                    result.append(var_id)
                else:
                    result.append(-var_id)
            except Exception:
                pass
        return result

    def get_core(self) -> Optional[List[int]]:
        """Unsat core - Z3 supports this via unsat_core()."""
        if self._solve_result() != unsat:
            return None
        try:
            core = self.solver.unsat_core()
            # Convert back to literals if we tracked assumption mapping
            return None  # Z3 unsat_core returns proof terms, not our literals
        except Exception:
            return None

    def is_satisfiable(self) -> Optional[bool]:
        return self._last_result

    def enumerate_models(self, assumptions: Optional[List[int]] = None) -> Iterable[List[int]]:
        """Enumerate models (blocking clause approach)."""
        while True:
            if self.solve(assumptions) != True:
                break
            model = self.get_model()
            if model is None:
                break
            yield model
            # Block this model: add clause (not model)
            self.solver.add(Or(*[self._lit_to_z3(-lit) for lit in model]))

    def get_stats(self) -> Dict[str, Any]:
        """Z3 doesn't expose same stats as PySAT; return placeholder."""
        return {}

    def nof_vars(self) -> int:
        return len(self._vars)

    def nof_clauses(self) -> int:
        return self._nof_clauses

    def delete(self) -> None:
        """Clean up."""
        self.solver = None
        self._vars.clear()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.delete()

    def __str__(self) -> str:
        return f"Z3SATSolver(vars={self.nof_vars()}, clauses={self.nof_clauses()})"
