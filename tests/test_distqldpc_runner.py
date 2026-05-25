"""DistQLDPC stdout parsing."""

from qecc_sat.distqldpc_runner import DistQLDPCResult, parse_distqldpc_output


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


def test_format_exact_d_line():
    text = "c d_lb: 1\nc d_ub: 4\nc d  : 4\no 4\n"
    r = parse_distqldpc_output(text)
    assert r.d == 4
    assert r.format_result() == "4"
    assert r.proved
