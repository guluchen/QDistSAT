"""Tanner-graph pruning helpers for CSS sector distance SAT instances.

These helpers do not own SAT variable allocation. Callers provide ``bit_lit`` so
the existing ``x_i`` / sector-bit numbering remains unchanged.
"""

from __future__ import annotations

from collections import deque
from math import ceil
from typing import Any, Callable, Iterable, List, Optional, Sequence, Set, Tuple


Support = Tuple[int, ...]


def tanner_neighbors(
    h_parity: Sequence[Sequence[int]],
) -> tuple[list[tuple[int, ...]], list[set[int]]]:
    """Return ``(check_to_bits, bit_to_checks)`` for a binary parity matrix."""
    n = max((len(row) for row in h_parity), default=0)
    check_to_bits: list[tuple[int, ...]] = []
    bit_to_checks: list[set[int]] = [set() for _ in range(n)]

    for c, row in enumerate(h_parity):
        bits = tuple(i for i, val in enumerate(row) if int(val) % 2 == 1)
        check_to_bits.append(bits)
        for i in bits:
            bit_to_checks[i].add(c)
    return check_to_bits, bit_to_checks


def inject_stopping_set_closure(
    solver: Any,
    check_to_bits: Sequence[Sequence[int]],
    bit_lit: Callable[[int], int],
) -> int:
    """Inject local stopping-set closure clauses.

    For each check ``c`` and each bit ``i`` in ``N(c)``, add
    ``x_i -> OR(N(c) \\ {i})`` as ``[-x_i, x_j1, ...]``. A degree-1 check becomes
    the unit clause ``[-x_i]``. These clauses are already implied by parity, but
    they shorten UNSAT proofs by exposing local singleton contradictions to unit
    propagation.
    """
    added = 0
    for nbrs in check_to_bits:
        for i in nbrs:
            clause = [-bit_lit(i)]
            clause.extend(bit_lit(j) for j in nbrs if j != i)
            solver.add_clause(clause)
            added += 1
    return added


def _bit_graph_neighbors(
    support: Iterable[int],
    check_to_bits: Sequence[Sequence[int]],
    bit_to_checks: Sequence[Set[int]],
) -> set[int]:
    out: set[int] = set()
    for bit in support:
        for check in bit_to_checks[bit]:
            out.update(check_to_bits[check])
    return out


def enumerate_connected_supports(
    bit_to_checks: Sequence[Set[int]],
    check_to_bits: Sequence[Sequence[int]],
    max_size: int,
    *,
    limit: int = 5000,
) -> list[Support]:
    """Enumerate connected bit supports in the Tanner-induced bit graph.

    Supports are zero-based bit indices. The enumeration is deterministic and
    capped because the number of connected subgraphs can grow quickly.
    """
    if max_size <= 0 or limit <= 0:
        return []

    n = len(bit_to_checks)
    seen: set[Support] = set()
    queue: deque[Support] = deque()
    results: list[Support] = []

    for start in range(n):
        support = (start,)
        seen.add(support)
        queue.append(support)

    while queue and len(results) < limit:
        support = queue.popleft()
        results.append(support)
        if len(support) >= max_size:
            continue

        support_set = set(support)
        frontier = _bit_graph_neighbors(support, check_to_bits, bit_to_checks)
        for bit in sorted(frontier):
            if bit in support_set:
                continue
            new_support = tuple(sorted((*support, bit)))
            if new_support in seen:
                continue
            seen.add(new_support)
            queue.append(new_support)
            if len(seen) >= limit:
                break

    return results[:limit]


def safe_deficit_lower_bound(
    support: Sequence[int],
    check_to_bits: Sequence[Sequence[int]],
    bit_to_checks: Sequence[Set[int]],
) -> int:
    """Lower-bound extra bits needed to close singleton checks.

    A raw singleton-check count is not sound because one added bit may close
    several singleton checks. We divide by the largest number of singleton
    checks any one candidate bit can cover, yielding a conservative lower bound.
    """
    support_set = set(support)
    singleton_checks = [
        c
        for c, nbrs in enumerate(check_to_bits)
        if sum(1 for bit in nbrs if bit in support_set) == 1
    ]
    if not singleton_checks:
        return 0

    candidate_bits: set[int] = set()
    for check in singleton_checks:
        candidate_bits.update(check_to_bits[check])
    candidate_bits.difference_update(support_set)

    singleton_set = set(singleton_checks)
    max_cover = 0
    for bit in candidate_bits:
        max_cover = max(max_cover, len(bit_to_checks[bit] & singleton_set))

    if max_cover == 0:
        return len(singleton_checks)
    return ceil(len(singleton_checks) / max_cover)


def dynamic_deficit_blocking(
    solver: Any,
    current_lb: int,
    check_to_bits: Sequence[Sequence[int]],
    bit_to_checks: Sequence[Set[int]],
    bit_lit: Callable[[int], int],
    *,
    activation_lit: Optional[int] = None,
    max_support_size: Optional[int] = None,
    limit: int = 5000,
    supports: Optional[Sequence[Sequence[int]]] = None,
) -> int:
    """Add deficit-based blocking clauses for the current lower-bound round.

    If ``activation_lit`` is set, clauses are guarded as
    ``[-activation_lit, -x_i1, ...]`` and only apply when that literal is passed
    as a solve assumption. Use this for persistent incremental solvers.
    """
    if current_lb <= 1:
        return 0
    if max_support_size is None:
        max_support_size = current_lb - 1
    else:
        max_support_size = min(max_support_size, current_lb - 1)

    candidates = supports
    if candidates is None:
        candidates = enumerate_connected_supports(
            bit_to_checks,
            check_to_bits,
            max_size=max_support_size,
            limit=limit,
        )

    added = 0
    for support in candidates:
        if not support or len(support) >= current_lb:
            continue
        deficit = safe_deficit_lower_bound(support, check_to_bits, bit_to_checks)
        if len(support) + deficit < current_lb:
            continue
        clause = [-bit_lit(i) for i in support]
        if activation_lit is not None:
            clause = [-activation_lit] + clause
        solver.add_clause(clause)
        added += 1
        if added >= limit:
            break
    return added

