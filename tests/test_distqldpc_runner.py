"""DistQLDPC stdout parsing."""

from qecc_sat.distqldpc_runner import (
    DISTQLDPC_BENCH_CONFIGS,
    DistQLDPCResult,
    format_distance_bounds,
    parse_distqldpc_output,
)


def test_parse_lb_ub_and_o():
    text = """
c trying d: 4
c d_lb: 2
c d_ub: 6
c trying d: 5
c d_lb: 3
c d_ub: 5
o 5
"""
    r = parse_distqldpc_output(text)
    assert r.d_lb == 3
    assert r.d_ub == 5
    assert r.o == 5
    assert r.format_result() == "5"


def test_format_bounds_on_timeout():
    r = DistQLDPCResult(
        d_lb=2,
        d_ub=8,
        d=None,
        o=-1,
        stdout="",
        stderr="",
        returncode=0,
        elapsed_sec=1.0,
        timed_out=True,
    )
    assert r.proved is False
    assert r.format_result() == "[2,8]"
    assert format_distance_bounds(lb=6) == "≥6"
    assert format_distance_bounds(ub=8) == "≤8"


def test_format_exact_no_lb_ub_suffix():
    r = DistQLDPCResult(
        d_lb=6,
        d_ub=6,
        d=6,
        o=6,
        stdout="",
        stderr="",
        returncode=0,
        elapsed_sec=0.1,
    )
    assert r.proved
    assert r.format_result() == "6"


def test_bench_configs():
    ids = [c for c, _ in DISTQLDPC_BENCH_CONFIGS]
    assert ids == ["no-card", "card-mto"]
    assert DISTQLDPC_BENCH_CONFIGS[0][1] == ("-no-card",)
    assert DISTQLDPC_BENCH_CONFIGS[1][1] == ("-card-mto",)


def test_format_exact_d_line():
    text = "c d_lb: 1\nc d_ub: 4\nc d  : 4\no 4\n"
    r = parse_distqldpc_output(text)
    assert r.d == 4
    assert r.format_result() == "4"
    assert r.proved


def test_parse_size_stats_from_verbose_stdout():
    text = """
c Reduced to 232 vars, 984 cls (c/v ratio==4.2, grow=0)
c MaxSAT: OPTIMAL, Pauli weight 2 (reported cost 2), vars 791 (base 142 + aux 290)
"""
    r = parse_distqldpc_output(text)
    assert r.nof_vars == 791
    assert r.nof_clauses == 984
    assert r.clauses_approx is True
