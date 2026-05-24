"""
Logarithmic (binary selector) encoding for at-most-k on Boolean variables.

For w_1..w_n and bound k, introduce k slots. Each slot has L = ceil(log2(n+1)) bits
encoding an index in {0,..,n-1} or sentinel n (unused). At most k qubits are active:

  w_i <-> OR_s (slot s selects index i)

with strict increasing indices across active slots (symmetry breaking).

This is related to Rodríguez-Carbonell's *logarithmic encoding* for AMO, extended to
a sparse set representation with k selectors.
"""

from __future__ import annotations

from typing import Any, List, Sequence, Tuple


def _ceil_log2_upto(n_inclusive: int) -> int:
    """Bits needed to encode integers 0..n_inclusive (inclusive upper bound)."""
    if n_inclusive <= 0:
        return 1
    return max(1, (n_inclusive).bit_length())


def _bits_of(value: int, width: int) -> Tuple[int, ...]:
    return tuple((value >> j) & 1 for j in range(width))


def _reify_and(solver: Any, inputs: Sequence[int], out: int) -> int:
    """out <-> AND(inputs). Returns number of clauses added."""
    ncl = 0
    if not inputs:
        solver.add_clause([out])
        return 1
    for x in inputs:
        solver.add_clause([-out, x])
        ncl += 1
    solver.add_clause([-x for x in inputs] + [out])
    ncl += 1
    return ncl


def _reify_bits_equal_pattern(
    solver: Any,
    bits: Sequence[int],
    pattern: int,
    out: int,
) -> int:
    """out <-> (bits decode to pattern). Returns clause count."""
    width = len(bits)
    if width == 0:
        solver.add_clause([out] if pattern == 0 else [-out])
        return 1
    lits = []
    for j, b in enumerate(bits):
        want = (pattern >> j) & 1
        if want:
            lits.append(b)
        else:
            lits.append(-b)
    return _reify_and(solver, lits, out)


def add_log_atmost_k(
    solver: Any,
    w_lits: List[int],
    k: int,
    next_id: List[int],
) -> Tuple[int, int]:
    """
    Encode sum(w) <= k using k logarithmic selector slots.

    ``next_id`` is a one-element list holding the current max variable id; updated in place.

    Returns (clauses_added, new_aux_vars).
    """
    n = len(w_lits)
    if k <= 0:
        for w in w_lits:
            solver.add_clause([-w])
        return n, 0
    if k >= n:
        return 0, 0

    sentinel = n  # unused slot
    L = _ceil_log2_upto(sentinel)
    n_slots = k

    def fresh() -> int:
        next_id[0] += 1
        return next_id[0]

    ncl = 0
    n_aux = 0

    bits: List[List[int]] = []
    eq: List[List[int]] = []
    eq_sentinel: List[int] = []

    for _s in range(n_slots):
        row = [fresh() for _ in range(L)]
        bits.append(row)
        n_aux += L
        erow = [fresh() for _ in range(n)]
        eq.append(erow)
        n_aux += n
        es = fresh()
        eq_sentinel.append(es)
        n_aux += 1

        ncl += _reify_bits_equal_pattern(solver, row, sentinel, es)
        for i in range(n):
            ncl += _reify_bits_equal_pattern(solver, row, i, erow[i])
            # eq[s,i] -> ~eq[s,sentinel]
            solver.add_clause([-erow[i], -es])
            ncl += 1

    # Channel w_i <-> OR_s eq[s,i]
    for i in range(n):
        wi = w_lits[i]
        for s in range(n_slots):
            solver.add_clause([-eq[s][i], wi])
            ncl += 1
        solver.add_clause([-wi] + [eq[s][i] for s in range(n_slots)])
        ncl += 1

    # Strict order on selected indices: s < t => index_s < index_t
    for s in range(n_slots):
        for t in range(s + 1, n_slots):
            for i in range(n):
                for j in range(i):
                    solver.add_clause([-eq[s][i], -eq[t][j]])
                    ncl += 1
            # sentinel suffix: if s unused, t unused
            solver.add_clause([-eq_sentinel[s], eq_sentinel[t]])
            ncl += 1

    return ncl, n_aux
