from qecc_sat.distance.compute_distance_from_bottom import (
    min_distance_quantum_stabilizer_or_logicals,
    min_distance_quantum_stabilizer_stepwise_card,
)
from qecc_sat.io import build_s_from_hx_hz, load_matrix, resolve_precomputed_logical_basis
from qecc_sat.sat_solver import SolverType

from tests.matrix_stem import BENCHMARK_D, BENCHMARK_STEM, MATRIX_DIR


class ProgressSink:
    def __init__(self):
        self.rows = []

    def put(self, row):
        self.rows.append(row)


def test_from_bottom_tn_36_8_4_distance_and_progress():
    hx = load_matrix(str(MATRIX_DIR / f"{BENCHMARK_STEM}_Hx.txt"))
    hz = load_matrix(str(MATRIX_DIR / f"{BENCHMARK_STEM}_Hz.txt"))
    s = build_s_from_hx_hz(hx, hz)
    logical, _, err = resolve_precomputed_logical_basis(
        str(MATRIX_DIR / f"{BENCHMARK_STEM}_Hx.txt"), len(hx[0])
    )
    assert err != "incomplete"

    progress = ProgressSink()
    d = min_distance_quantum_stabilizer_or_logicals(
        s,
        solver_type=SolverType.MINISAT22,
        max_distance=BENCHMARK_D,
        logical_basis_override=logical,
        progress_q=progress,
    )

    assert d == BENCHMARK_D
    assert progress.rows[-1]["witness_d"] == BENCHMARK_D


def test_from_bottom_stepwise_tn_36_8_4_distance():
    hx = load_matrix(str(MATRIX_DIR / f"{BENCHMARK_STEM}_Hx.txt"))
    hz = load_matrix(str(MATRIX_DIR / f"{BENCHMARK_STEM}_Hz.txt"))
    s = build_s_from_hx_hz(hx, hz)
    logical, _, err = resolve_precomputed_logical_basis(
        str(MATRIX_DIR / f"{BENCHMARK_STEM}_Hx.txt"), len(hx[0])
    )
    assert err != "incomplete"

    d = min_distance_quantum_stabilizer_stepwise_card(
        s,
        solver_type=SolverType.MINISAT22,
        max_distance=BENCHMARK_D,
        logical_basis_override=logical,
    )

    assert d == BENCHMARK_D
