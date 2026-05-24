from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple, Union

try:
    from pysat.card import CardEnc, EncType, ITotalizer
except ImportError:
    CardEnc = None
    EncType = None
    ITotalizer = None

from ..sat_solver import (
    get_solver,
    SolverType,
    CARD_SUPPORTED_SOLVERS,
    NATIVE_ONLY_CARD_SOLVERS,
    XOR_SUPPORTED_SOLVERS,
    tseitin_xor_clause_count,
)
from .build_distance_constraints import _add_xor_clause, _matrix_shape

def min_distance_parity_check(
    H: List[List[Union[int, float]]],
    solver_type: SolverType = SolverType.GLUCOSE3,
    max_distance: Optional[int] = None,
    encoding: Any = None,
) -> Optional[int]:
    """
    Compute the minimum distance of a code with parity check matrix H over GF(2).

    The minimum distance is the minimum Hamming weight of a nonzero vector x
    such that H @ x = 0 (mod 2). Implementation: for k = 1, 2, ..., solve
    (H*x = 0) and (x != 0) and (weight(x) = k); the first k that is satisfiable
    is the minimum distance.

    Parameters
    ----------
    H : list of lists (or 2D array)
        Parity check matrix, m x n. Entries should be 0 or 1 (mod 2).
        Rows are constraints; columns correspond to codeword bits.
    solver_type : SolverType, optional
        SAT solver to use. Default Glucose3. CryptoMiniSat can be faster
        when many XOR constraints are present.
    max_distance : int, optional
        Stop searching after this weight. If None, search up to n (code length).
    encoding : pysat.card.EncType, optional
        Cardinality encoding for Σx_i ≤ k. Default seqcounter.

    Returns
    -------
    int or None
        The minimum distance d, or None if no nonzero codeword exists
        (trivial code) or CardEnc is unavailable.

    Examples
    --------
    >>> # Hamming [7,4] code: one parity check per syndrome bit
    >>> H = [
    ...     [1, 0, 1, 0, 1, 0, 1],
    ...     [0, 1, 1, 0, 0, 1, 1],
    ...     [0, 0, 0, 1, 1, 1, 1],
    ... ]
    >>> min_distance_parity_check(H)
    3
    """
    if CardEnc is None or EncType is None:
        raise ImportError("pysat.card (CardEnc) is required for min_distance_parity_check")

    if encoding is None:
        encoding = EncType.seqcounter

    m, n = _matrix_shape(H)
    if m == 0 or n == 0:
        return None

    if max_distance is None:
        max_distance = n

    # Variables: 1..n for x_1, ..., x_n (1-based)
    for k in range(1, max_distance + 1):
        solver = get_solver(solver_type=solver_type)

        # H @ x = 0 (mod 2): each row gives XOR of x_i for H[row][i]==1
        for row in range(m):
            lits = [i + 1 for i in range(n) if H[row][i] % 2 == 1]
            if not lits:
                continue
            if len(lits) == 1:
                # 0 = x_i  =>  x_i = 0
                solver.add_clause([-lits[0]])
                continue
            solver.add_xor_clause(lits, value=False)

        # x != 0: at least one x_i = 1
        solver.add_clause(list(range(1, n + 1)))

        # weight(x) ≤ k
        card = CardEnc.atmost(
            lits=list(range(1, n + 1)),
            bound=k,
            top_id=n,
            encoding=encoding,
        )
        solver.add_clauses(card.clauses)

        result = solver.solve()
        solver.delete()

        if result:
            return k

    return None


def min_distance_with_witness(
    H: List[List[Union[int, float]]],
    solver_type: SolverType = SolverType.GLUCOSE3,
    max_distance: Optional[int] = None,
) -> tuple:
    """
    Compute the minimum distance and return a witness (minimum-weight nonzero codeword).

    Returns
    -------
    (d, model) : (int or None, list or None)
        d is the minimum distance; model is a list of literals for one
        minimum-weight codeword (e.g. [1, -2, 3] means x1=1, x2=0, x3=1).
    """
    if CardEnc is None or EncType is None:
        raise ImportError("pysat.card (CardEnc) is required")

    m, n = _matrix_shape(H)
    if m == 0 or n == 0:
        return None, None

    if max_distance is None:
        max_distance = n

    for k in range(1, max_distance + 1):
        solver = get_solver(solver_type=solver_type)

        for row in range(m):
            lits = [i + 1 for i in range(n) if H[row][i] % 2 == 1]
            if not lits:
                continue
            if len(lits) == 1:
                solver.add_clause([-lits[0]])
                continue
            solver.add_xor_clause(lits, value=False)

        solver.add_clause(list(range(1, n + 1)))

        card = CardEnc.atmost(
            lits=list(range(1, n + 1)),
            bound=k,
            top_id=n,
            encoding=EncType.seqcounter,
        )
        solver.add_clauses(card.clauses)

        result = solver.solve()
        if result:
            model = solver.get_model()
            solver.delete()
            # Return only the n codeword bits (variables 1..n), sorted by variable index
            witness = [0] * n
            if model:
                for lit in model:
                    var = abs(lit)
                    if 1 <= var <= n:
                        witness[var - 1] = 1 if lit > 0 else 0
            return k, witness

        solver.delete()

    return None, None


