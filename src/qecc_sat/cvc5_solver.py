"""
CVC5 SAT Solver Interface - Uses CVC5 SMT solver with native XOR and cardinality.

CVC5 handles XOR natively; cardinality is encoded via Sum(If(b,1,0)) since
the Pythonic API does not support pseudo-boolean constraints.

This provides the same API as sat_solver.SATSolver for drop-in replacement.
"""

from typing import List, Optional, Dict, Any, Iterable

try:
    from cvc5.pythonic import (
        Solver,
        Bool,
        Or,
        Not,
        Xor,
        Sum,
        If,
        IntVal,
    )
except ImportError as e:
    raise ImportError(
        "CVC5 required. Install: pip install cvc5"
    ) from e


class CVC5SATSolver:
    """
    SAT solver interface using CVC5 with native XOR and Sum/If cardinality.

    Uses 1-based literals (same as PySAT): positive = variable true, negative = negated.
    """

    def __init__(self, bootstrap_with: Optional[Iterable[Iterable[int]]] = None, **kwargs):
        """
        Initialize CVC5 solver.

        Args:
            bootstrap_with: Optional list of clauses to add initially
            **kwargs: Ignored (for API compatibility with SATSolver)
        """
        self.solver = Solver()
        self._vars: Dict[int, Any] = {}  # var_id -> cvc5 Bool
        self._nof_vars = 0
        self._nof_clauses = 0
        self._last_result: Optional[bool] = None

        if bootstrap_with:
            for clause in bootstrap_with:
                self.add_clause(list(clause))

    def _get_var(self, var_id: int):
        """Get or create CVC5 Bool for variable (1-based)."""
        if var_id not in self._vars:
            self._vars[var_id] = Bool(f"x{var_id}")
            self._nof_vars = max(self._nof_vars, var_id)
        return self._vars[var_id]

    def _lit_to_expr(self, lit: int):
        """Convert literal (1-based) to CVC5 expression."""
        var = self._get_var(abs(lit))
        return var if lit > 0 else Not(var)

    def add_clause(self, clause: List[int], no_return: bool = True) -> Optional[bool]:
        """Add clause: (l1 or l2 or ... or ln)."""
        if not clause:
            self.solver.add(False)  # empty clause = UNSAT
            self._nof_clauses += 1
            return False
        expr = Or(*[self._lit_to_expr(lit) for lit in clause])
        self.solver.add(expr)
        self._nof_clauses += 1
        return None

    def add_clauses(self, clauses: Iterable[List[int]], no_return: bool = True) -> Optional[bool]:
        """Add multiple clauses."""
        for clause in clauses:
            self.add_clause(clause, no_return)
        return None

    def supports_xor(self) -> bool:
        """CVC5 supports native XOR."""
        return True

    def supports_card(self) -> bool:
        """CVC5 supports cardinality via Sum/If encoding."""
        return True

    def add_atmost(self, lits: List[int], k: int, no_return: bool = True) -> Optional[bool]:
        """
        Add AtMostK: at most k of the literals can be true.
        Uses Sum(If(b,1,0)) <= k since CVC5 Pythonic has no PbLe.
        """
        if not lits:
            return None
        negated = all(x < 0 for x in lits)
        cvc5_vars = [self._get_var(abs(x)) for x in lits]
        one = IntVal(1)
        zero = IntVal(0)
        if negated:
            # at most k of (not v_i) true  <=>  at least n-k of v_i true
            s = Sum([If(v, one, zero) for v in cvc5_vars])
            self.solver.add(s >= len(lits) - k)
        else:
            s = Sum([If(v, one, zero) for v in cvc5_vars])
            self.solver.add(s <= k)
        self._nof_clauses += 1
        return None

    def _xor_tree(self, exprs: List[Any]) -> Any:
        """Build balanced XOR tree (CVC5 Xor takes only 2 args)."""
        if len(exprs) == 1:
            return exprs[0]
        if len(exprs) == 2:
            return Xor(exprs[0], exprs[1])
        mid = len(exprs) // 2
        return Xor(self._xor_tree(exprs[:mid]), self._xor_tree(exprs[mid:]))

    def add_xor_clause(self, lits: List[int], value: bool = True) -> None:
        """Add XOR constraint: (l1 XOR l2 XOR ... XOR ln) == value."""
        if not lits:
            if value:
                self.solver.add(False)
                self._nof_clauses += 1
            return
        if len(lits) == 1:
            expr = self._lit_to_expr(lits[0])
            self.solver.add(expr == value)
            self._nof_clauses += 1
            return
        exprs = [self._lit_to_expr(lit) for lit in lits]
        self.solver.add(self._xor_tree(exprs) == value)
        self._nof_clauses += 1

    def add_equals_card(self, lits: List[int], k: int) -> None:
        """Add cardinality equals: exactly k of lits are true. Uses Sum/If."""
        if not lits:
            if k != 0:
                self.solver.add(False)
            return
        cvc5_vars = [self._get_var(abs(x)) for x in lits]
        one = IntVal(1)
        zero = IntVal(0)
        s = Sum([If(v, one, zero) for v in cvc5_vars])
        self.solver.add(s == k)
        self._nof_clauses += 1

    def solve(self, assumptions: Optional[List[int]] = None) -> Optional[bool]:
        """Solve. Returns True if SAT, False if UNSAT, None if interrupted."""
        if assumptions:
            self.solver.push()
            for lit in assumptions:
                self.solver.add(self._lit_to_expr(lit))
        try:
            result = self.solver.check()
            s = str(result).lower()
            if "sat" in s and "unsat" not in s:
                self._last_result = True
            elif "unsat" in s:
                self._last_result = False
            else:
                self._last_result = None  # unknown
        except Exception:
            self._last_result = None
        finally:
            if assumptions:
                self.solver.pop()
        return self._last_result

    def get_model(self) -> Optional[List[int]]:
        """Return model as list of literals (1-based)."""
        try:
            m = self.solver.model()
        except Exception:
            return None
        if m is None:
            return None
        result = []
        for var_id, cvc5_var in self._vars.items():
            try:
                val = m.evaluate(cvc5_var)
                if val is None:
                    continue
                s = str(val).lower()
                if "true" in s or s == "true":
                    result.append(var_id)
                else:
                    result.append(-var_id)
            except Exception:
                pass
        return result

    def get_core(self) -> Optional[List[int]]:
        """Unsat core - not fully supported for our literal format."""
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
            self.solver.add(Or(*[self._lit_to_expr(-lit) for lit in model]))

    def get_stats(self) -> Dict[str, Any]:
        """CVC5 doesn't expose same stats as PySAT."""
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
        return f"CVC5SATSolver(vars={self.nof_vars()}, clauses={self.nof_clauses()})"
