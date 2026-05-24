"""Tseitin XOR CNF encoding: equisatisfiable to exponential encoding on small cases."""

from __future__ import annotations

from pysat.solvers import Solver as PySATSolver

from qecc_sat.sat_solver import (
    SATSolver,
    SolverType,
    _tseitin_xor_to_cnf,
    _xor_to_cnf_exponential,
    tseitin_xor_clause_count,
)


def _solve_cnf(clauses: list[list[int]]) -> bool | None:
    with PySATSolver(name="glucose3") as s:
        for cl in clauses:
            s.add_clause(cl)
        return s.solve()


def test_tseitin_matches_exponential_small() -> None:
    for lits in ([1, 2], [1, 2, 3], [-1, 2, 3], [1, -2, 3, 4]):
        for value in (False, True):
            next_id = [max(abs(l) for l in lits)]
            tse = _tseitin_xor_to_cnf(lits, value, next_id)
            exp = _xor_to_cnf_exponential(lits, value)
            assert _solve_cnf(tse) == _solve_cnf(exp)


def test_tseitin_clause_count_linear() -> None:
    lits = list(range(1, 21))
    assert tseitin_xor_clause_count(lits, False) == 4 * 19 + 1
    assert tseitin_xor_clause_count(lits, False) < len(_xor_to_cnf_exponential(lits, False))


def test_satsolver_minisat_uses_tseitin_not_huge_cnf() -> None:
    s = SATSolver(solver_type=SolverType.MINISAT22)
    wide = list(range(1, 25))
    s.add_xor_clause(wide, value=False)
    # 23 aux vars from Tseitin chain + 24 inputs; must stay << 2^23 clauses
    assert s.nof_clauses() < 10_000
