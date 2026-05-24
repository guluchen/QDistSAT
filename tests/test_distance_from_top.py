from qecc_sat.distance.compute_distance_from_top import (
    _min_distance_or_logicals_maxsat,
    min_distance_quantum_stabilizer_card_refine,
)
from qecc_sat.io import build_s_from_hx_hz, load_matrix, resolve_precomputed_logical_basis
from qecc_sat.sat_solver import SolverType

from tests.matrix_stem import BENCHMARK_D, BENCHMARK_STEM, MATRIX_DIR


def _tn_36_8_4():
    hx = load_matrix(str(MATRIX_DIR / f"{BENCHMARK_STEM}_Hx.txt"))
    hz = load_matrix(str(MATRIX_DIR / f"{BENCHMARK_STEM}_Hz.txt"))
    s = build_s_from_hx_hz(hx, hz)
    logical, _, err = resolve_precomputed_logical_basis(
        str(MATRIX_DIR / f"{BENCHMARK_STEM}_Hx.txt"), len(hx[0])
    )
    assert err != "incomplete"
    return s, logical, len(hx[0])


def test_from_top_maxsat_tn_36_8_4():
    s, logical, n = _tn_36_8_4()
    d = _min_distance_or_logicals_maxsat(
        s,
        SolverType.RC2_G3,
        BENCHMARK_D,
        logical,
        n,
        len(s),
    )
    assert d == BENCHMARK_D


def test_from_top_refine_smoke_tn_36_8_4():
    s, logical, _n = _tn_36_8_4()
    d = min_distance_quantum_stabilizer_card_refine(
        s,
        solver_type=SolverType.MINISAT22,
        max_distance=BENCHMARK_D,
        logical_basis_override=logical,
    )
    assert d is None or isinstance(d, int)
