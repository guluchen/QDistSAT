#!/usr/bin/env python3
"""Sanity checks: log selector encoding matches brute force for small n,k."""

from __future__ import annotations

from itertools import combinations

from pysat.solvers import Solver as PySolver

from qecc_sat.log_encoding import add_log_atmost_k


def _models(n: int, k: int, use_log: bool) -> set[tuple[int, ...]]:
    w_lits = list(range(1, n + 1))
    top = n
    models: set[tuple[int, ...]] = set()
    for mask in range(1 << n):
        wt = bin(mask).count("1")
        if wt > k:
            continue
        next_id = [top]
        solver = PySolver(name="minicard")
        for i in range(n):
            lit = w_lits[i]
            if (mask >> i) & 1:
                solver.add_clause([lit])
            else:
                solver.add_clause([-lit])
        if use_log:
            add_log_atmost_k(solver, w_lits, k, next_id)
        else:
            solver.add_atmost(w_lits, k)
        if solver.solve():
            m = solver.get_model() or []
            models.add(
                tuple(1 if w_lits[i] in m else 0 for i in range(n))
            )
        solver.delete()
    return models


def test_log_matches_atmost_small():
    for n in range(1, 8):
        for k in range(0, n + 1):
            brute = {
                tuple(v)
                for v in (
                    [0] * i + [1] + [0] * (n - i - 1)
                    for i in range(n)
                )
            }
            # enumerate all assignments with wt<=k
            allowed = set()
            for mask in range(1 << n):
                if bin(mask).count("1") <= k:
                    allowed.add(tuple((mask >> i) & 1 for i in range(n)))
            std = _models(n, k, use_log=False)
            log = _models(n, k, use_log=True)
            assert std == allowed, (n, k, std, allowed)
            assert log == allowed, (n, k, log, allowed)


if __name__ == "__main__":
    test_log_matches_atmost_small()
    print("ok")
