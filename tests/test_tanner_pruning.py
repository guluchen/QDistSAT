from pysat.solvers import Solver

from qecc_sat.distance.compute_css_split_distance import (
    min_distance_quantum_css_split_or_logicals,
)
from qecc_sat.distance.prune_with_tanner_graph import (
    dynamic_deficit_blocking,
    inject_stopping_set_closure,
    safe_deficit_lower_bound,
    tanner_neighbors,
)
from qecc_sat.io import load_matrix, resolve_precomputed_logical_basis
from qecc_sat.sat_solver import SolverType

from tests.matrix_stem import BENCHMARK_D, BENCHMARK_STEM, MATRIX_DIR


class ClauseSink:
    def __init__(self):
        self.clauses = []

    def add_clause(self, clause):
        self.clauses.append(list(clause))


def test_stopping_set_closure_injects_implications_and_degree_one_units():
    check_to_bits, _bit_to_checks = tanner_neighbors([[1, 1, 0], [0, 0, 1]])
    sink = ClauseSink()

    added = inject_stopping_set_closure(sink, check_to_bits, lambda i: i + 1)

    assert added == 3
    assert [-1, 2] in sink.clauses
    assert [-2, 1] in sink.clauses
    assert [-3] in sink.clauses


def test_deficit_lower_bound_accounts_for_shared_repair_bits():
    check_to_bits, bit_to_checks = tanner_neighbors([[1, 0, 1], [0, 1, 1]])

    assert safe_deficit_lower_bound((0, 1), check_to_bits, bit_to_checks) == 1


def test_gated_dynamic_blocking_only_applies_when_assumed():
    check_to_bits, bit_to_checks = tanner_neighbors([[1, 1]])

    with Solver(name="m22") as solver:
        solver.add_clause([1])
        added = dynamic_deficit_blocking(
            solver,
            2,
            check_to_bits,
            bit_to_checks,
            lambda i: i + 1,
            activation_lit=10,
            supports=[(0,)],
        )

        assert added == 1
        assert solver.solve()
        assert not solver.solve(assumptions=[10])


def test_css_split_with_tanner_pruning_tn_36_8_4_smoke():
    hx = load_matrix(str(MATRIX_DIR / f"{BENCHMARK_STEM}_Hx.txt"))
    hz = load_matrix(str(MATRIX_DIR / f"{BENCHMARK_STEM}_Hz.txt"))
    logical, _, err = resolve_precomputed_logical_basis(
        str(MATRIX_DIR / f"{BENCHMARK_STEM}_Hx.txt"), len(hx[0])
    )
    assert err != "incomplete"

    d = min_distance_quantum_css_split_or_logicals(
        hx,
        hz,
        solver_type=SolverType.MINISAT22,
        max_distance=BENCHMARK_D,
        logical_basis_override=logical,
        sector_cardinality="linear",
        parallel_css_sectors=False,
        enable_stopping_closure=True,
        enable_dynamic_deficit=True,
    )

    assert d == BENCHMARK_D

