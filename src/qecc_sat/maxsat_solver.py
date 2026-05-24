"""
MaxSAT backends for minimum-weight Pauli distance (OR-logicals encoding).

Uses PySAT's RC2 [1]_ on a partial weighted CNF: commutation / logical / P≠0 / w_i
definitions are hard; each ``w_i`` is a unit soft clause of weight 1 so the optimum
cost equals Hamming weight.

.. [1] PySAT ``pysat.examples.rc2.RC2``.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from pysat.formula import WCNF

from .maxsat_registry import manifest_by_solver_type
from .sat_solver import (
    SolverType,
    _tseitin_xor_to_cnf,
    ensure_pysat_cms_solve_limited_budgets,
    tseitin_xor_clause_count,
)

try:
    from pysat.examples.rc2 import RC2
except ImportError as e:
    RC2 = None  # type: ignore[misc, assignment]
    _RC2_IMPORT_ERROR = e
else:
    _RC2_IMPORT_ERROR = None


class _RC2CMS(RC2):
    """RC2 with CMS oracle: set solve_limited budgets before each SAT call."""

    def _call_oracle(self, assumptions=[], expect_interrupt=False):
        ensure_pysat_cms_solve_limited_budgets(self.oracle)
        return super()._call_oracle(
            assumptions=assumptions, expect_interrupt=expect_interrupt
        )


# Suffix after rc2- -> PySAT oracle name for RC2.
_PYSAT_RC2_ORACLE: dict[str, str] = {
    "g3": "g3",
    "g4": "g4",
    "glucose3": "g3",
    "glucose4": "g4",
    "glucose42": "g42",
    "minisat22": "m22",
    "cadical195": "cd195",
    "cryptosat": "cms",
}


def is_external_maxsat_solver(solver_type: SolverType) -> bool:
    """True for ``cashw-coreplus``, ``open-wbo``, etc. (see ``bin/maxsat/manifest.json``)."""
    return solver_type.value in manifest_by_solver_type()


def is_rc2_maxsat_solver(solver_type: SolverType) -> bool:
    return solver_type.value.startswith("rc2-")


def is_maxsat_solver(solver_type: SolverType) -> bool:
    return is_rc2_maxsat_solver(solver_type) or is_external_maxsat_solver(solver_type)


def rc2_oracle_name(solver_type: SolverType) -> str:
    """Map ``SolverType.RC2_G3`` (``rc2-g3``) to RC2's ``solver='g3'`` argument."""
    if not is_rc2_maxsat_solver(solver_type):
        raise ValueError(f"Not an RC2 MaxSAT solver type: {solver_type}")
    suffix = solver_type.value[len("rc2-") :]
    try:
        return _PYSAT_RC2_ORACLE[suffix]
    except KeyError:
        known = ", ".join(sorted(_PYSAT_RC2_ORACLE))
        raise ValueError(
            f"Unknown RC2 backend {suffix!r}; known oracle suffixes: {known}"
        ) from None


class WCNFBuilder:
    """Accumulate a WCNF: hard CNF clauses + optional soft weighted units."""

    def __init__(self) -> None:
        self.wcnf = WCNF()
        self._aux_hi = 0
        self.nhard = 0
        self.nsoft = 0

    def add_clause(self, clause: List[int]) -> None:
        self.wcnf.append(list(clause))
        self.nhard += 1

    def add_xor_clause(
        self,
        lits: List[int],
        *,
        value: bool = False,
        next_var_ref: Optional[List[int]] = None,
    ) -> None:
        if next_var_ref is not None:
            base = next_var_ref[0]
        else:
            base = max(
                self._aux_hi,
                self.wcnf.nv,
                max((abs(l) for l in lits), default=0),
            )
        next_var = [base]
        for clause in _tseitin_xor_to_cnf(lits, value, next_var):
            self.add_clause(clause)
        self._aux_hi = max(self._aux_hi, next_var[0])
        if next_var_ref is not None:
            next_var_ref[0] = next_var[0]

    def add_soft_lit(self, lit: int, weight: int = 1) -> None:
        """Soft unit clause: pays ``weight`` when ``lit`` is false (RC2 cost model)."""
        self.wcnf.append([lit], weight=weight)
        self.nsoft += 1

    def nof_vars(self) -> int:
        return int(self.wcnf.nv)

    def nof_hard_clauses(self) -> int:
        return self.nhard

    def xor_clause_count(self, lits: List[int], value: bool) -> int:
        return tseitin_xor_clause_count(lits, value)


def solve_rc2(
    builder: WCNFBuilder,
    oracle: str,
    *,
    verbose: int = 0,
) -> Tuple[Optional[List[int]], Optional[int]]:
    """
    Run RC2 on ``builder.wcnf``.

    Returns ``(model, cost)``; ``(None, None)`` if hard part is unsatisfiable.
    """
    if RC2 is None:
        raise ImportError(
            "PySAT RC2 MaxSAT not available. Install python-sat."
        ) from _RC2_IMPORT_ERROR
    rc2_cls = _RC2CMS if oracle == "cms" else RC2
    with rc2_cls(builder.wcnf, solver=oracle, verbose=verbose) as engine:
        model = engine.compute()
        if model is None:
            return None, None
        return model, int(engine.cost)


def minimize_soft_weight(
    builder: WCNFBuilder,
    solver_type: SolverType,
    *,
    max_weight: Optional[int] = None,
    verbose: int = 0,
    timeout_sec: Optional[float] = None,
) -> Tuple[Optional[int], Optional[List[int]], WCNFBuilder]:
    """
    Solve and return ``(optimal_weight, model, builder)``.

    If ``max_weight`` is set and optimum exceeds it, returns ``(None, None, builder)``.
    """
    if is_external_maxsat_solver(solver_type):
        from .maxsat_external import run_external_maxsat

        cost, model, _stdout = run_external_maxsat(
            builder,
            solver_type.value,
            timeout_sec=timeout_sec,
        )
    else:
        oracle = rc2_oracle_name(solver_type)
        model, cost = solve_rc2(builder, oracle, verbose=verbose)
    if cost is None:
        return None, None, builder
    # Some external binaries (e.g. glucose_release) report optimal cost only.
    if model is None and not is_external_maxsat_solver(solver_type):
        return None, None, builder
    if max_weight is not None and cost > max_weight:
        return None, None, builder
    return cost, model, builder
