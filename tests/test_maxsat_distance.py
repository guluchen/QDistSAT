"""MaxSAT (RC2) distance on TN_36_8_4 (matrices from data/matrices/)."""

import pytest

from qecc_sat.io import build_s_from_hx_hz, load_matrix, resolve_precomputed_logical_basis
from qecc_sat.qecc_distance import min_distance_quantum_stabilizer_or_logicals
from qecc_sat.sat_solver import SolverType

from tests.matrix_stem import BENCHMARK_D, BENCHMARK_STEM, MATRIX_DIR

STEM = BENCHMARK_STEM
MAX_DISTANCE = 6
EXPECTED_D = BENCHMARK_D


@pytest.fixture(scope="module")
def stabilizer_and_logicals():
    hx = load_matrix(str(MATRIX_DIR / f"{STEM}_Hx.txt"))
    hz = load_matrix(str(MATRIX_DIR / f"{STEM}_Hz.txt"))
    s = build_s_from_hx_hz(hx, hz)
    logical, _, err = resolve_precomputed_logical_basis(
        str(MATRIX_DIR / f"{STEM}_Hx.txt"), len(hx[0])
    )
    assert err != "incomplete"
    return s, logical


@pytest.mark.parametrize(
    "solver_type",
    [
        SolverType.RC2_G3,
        SolverType.RC2_MINISAT22,
        SolverType.RC2_GLUCOSE42,
    ],
)
def test_maxsat_matches_sat_scan(stabilizer_and_logicals, solver_type):
    s, logical = stabilizer_and_logicals
    d_sat = min_distance_quantum_stabilizer_or_logicals(
        s,
        solver_type=SolverType.MINISAT22,
        max_distance=MAX_DISTANCE,
        logical_basis_override=logical,
    )
    d_ms = min_distance_quantum_stabilizer_or_logicals(
        s,
        solver_type=solver_type,
        max_distance=MAX_DISTANCE,
        logical_basis_override=logical,
    )
    assert d_sat == EXPECTED_D
    assert d_ms == d_sat
