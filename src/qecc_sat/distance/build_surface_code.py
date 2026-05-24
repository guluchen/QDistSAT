from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple, Union

# ---------------------------------------------------------------------------
# [[5,1,2]] Rotated surface code (one rung of a ladder)
# Generators: ZZZII, IIZZZ, XIXXI, IXXIX (Error Correction Zoo)
# Symplectic (X|Z): 4 x 10
# ---------------------------------------------------------------------------
STABILIZER_SURFACE_5_1_2 = [
    [0, 0, 0, 0, 0, 1, 1, 1, 0, 0],  # ZZZII
    [0, 0, 0, 0, 0, 0, 0, 1, 1, 1],  # IIZZZ
    [1, 1, 1, 0, 0, 0, 0, 0, 0, 0],  # XIXXI
    [0, 1, 1, 1, 0, 0, 0, 0, 0, 0],  # IXXIX
]

def rotated_surface_code_stabilizers(L: int, *, debug: bool = False) -> List[List[int]]:
    """
    Build the stabilizer matrix (symplectic X|Z) for the [[L^2, 1, L]] rotated
    surface code patch on an L x L grid with open boundaries.

    Parameters
    ----------
    L : int
        Grid size (L x L qubits).
        debug : bool, optional
        If True, print Z and X boundary positions. Default False.

    Qubits are indexed row-major: (r,c) -> index r*L+c; row 0 is top, col 0 is left.
    Boundaries (weight-2) are on the four sides; bulk plaquettes are weight-4.
    - Top boundary: X weight-2 pairs on row 0. For odd L: (0,0)-(0,1),...; for even L: (0,0)-(0,1), (0,2)-(0,3), ...
    - Bottom boundary: X weight-2 pairs on row L-1. For odd L: (L-1,1)-(L-1,2),...; for even L: (L-1,0)-(L-1,1), (L-1,2)-(L-1,3), ...
    - Left boundary: Z weight-2 pairs on col 0, excluding row 0. (1,0)-(2,0), (3,0)-(4,0), ...
    - Right boundary: Z weight-2 pairs on col L-1. For odd L: (0,L-1)-(1,L-1),...; for even L: (0,L-1)-(1,L-1), (2,L-1)-(3,L-1), ...
    Bulk Z at squares with top-left (r,c) where 0<=r,c<=L-2 and (r+c) even.
    Bulk X at squares with top-left (r,c) where 0<=r,c<=L-2 and (r+c) odd.
    Every X check overlaps every Z check on an even number of qubits (valid CSS).

    Returns
    -------
    S : list of rows, each row length 2*L^2 (X part | Z part)
    """
    n = L * L
    S = []

    def q(r: int, c: int) -> int:
        return r * L + c

    def add_z(positions: List[tuple]) -> None:
        row = [0] * (2 * n)
        for (rr, cc) in positions:
            row[n + q(rr, cc)] = 1
        S.append(row)

    def add_x(positions: List[tuple]) -> None:
        row = [0] * (2 * n)
        for (rr, cc) in positions:
            row[q(rr, cc)] = 1
        S.append(row)

    # Z type: bulk (r+c even), then right boundary, then left boundary, then remaining bulk
    z_bulk = []
    for r in range(L - 1):
        for c in range(L - 1):
            if (r + c) % 2 != 0:
                continue
            row = [0] * (2 * n)
            for (rr, cc) in [(r, c), (r + 1, c), (r, c + 1), (r + 1, c + 1)]:
                row[n + q(rr, cc)] = 1
            z_bulk.append(row)
    if L >= 2:
        S.append(z_bulk[0])
        # Z boundaries: weight-2 stabilizers (pairs of adjacent qubits) on left and right edges
        # Right: pairs (2i, L-1)-(2i+1, L-1) for i = 0, 1, ...
        for i in range(0, L - 1, 2):
            right_pair = [(i, L - 1), (i + 1, L - 1)]
            if debug:
                print(f"[DEBUG] Z right boundary: positions {right_pair}")
            add_z(right_pair)
        # Left: exclude row 0. Pairs (2i+1,0)-(2i+2,0) for i = 0, 1, ...
        left_start = 1
        for i in range(left_start, L - 1, 2):
            left_pair = [(i, 0), (i + 1, 0)]
            if debug:
                print(f"[DEBUG] Z left boundary:  positions {left_pair}")
            add_z(left_pair)
        for row in z_bulk[1:]:
            S.append(row)
    else:
        S.extend(z_bulk)

    # X type: top boundary, bulk (r+c odd), bottom boundary
    if L >= 2:
        # X boundaries: weight-2 stabilizers (pairs of adjacent qubits) on top and bottom edges
        # Top: pairs (0,2j)-(0,2j+1). For odd L exclude col L-1; for even L include all.
        top_col_end = L if L % 2 == 0 else L - 1
        for j in range(0, top_col_end - 1, 2):
            top_pair = [(0, j), (0, j + 1)]
            if debug:
                print(f"[DEBUG] X top boundary:    positions {top_pair}")
            add_x(top_pair)
        # Bottom: pairs (L-1,2j)-(L-1,2j+1). For odd L exclude col 0; for even L include all.
        bottom_col_start = 0 if L % 2 == 0 else 1
        for j in range(bottom_col_start, L - 1, 2):
            bottom_pair = [(L - 1, j), (L - 1, j + 1)]
            if debug:
                print(f"[DEBUG] X bottom boundary: positions {bottom_pair}")
            add_x(bottom_pair)
    for r in range(L - 1):
        for c in range(L - 1):
            if (r + c) % 2 != 1:
                continue
            add_x([(r, c), (r + 1, c), (r, c + 1), (r + 1, c + 1)])
    return S


def stabilizer_to_pauli_string(row: List[Union[int, float]], n: Optional[int] = None) -> str:
    """
    Convert one symplectic row (X part | Z part) of length 2n to a Pauli string.

    For each qubit i: (x_i, z_i) -> I (0,0), X (1,0), Z (0,1), Y (1,1).
    """
    if n is None:
        n = len(row) // 2
    s = []
    for i in range(n):
        x = int(row[i]) % 2
        z = int(row[n + i]) % 2
        s.append("I" if (x, z) == (0, 0) else "X" if (x, z) == (1, 0) else "Z" if (x, z) == (0, 1) else "Y")
    return "".join(s)


def _qubit_to_coord(i: int, shape: tuple) -> tuple:
    """Map qubit index i to (x, y) with row-major order: i = x * cols + y."""
    rows, cols = shape
    return (i // cols, i % cols)


def stabilizer_to_pauli_coords(
    row: List[Union[int, float]],
    shape: Optional[tuple] = None,
    n: Optional[int] = None,
    skip_identity: bool = True,
    linear_index: bool = False,
) -> List[str]:
    """
    Convert one symplectic row to a list of "P(i)" or "P(x,y)" for non-identity Paulis.

    shape : (rows, cols) for qubit index -> (x, y). Ignored if linear_index=True.
    linear_index : if True, use P(i) format (qubit index only). For non-surface codes.
    skip_identity : if True, omit I (default True).
    Returns e.g. ["Z(0)", "Z(1)", "X(2)"] or ["Z(0,0)", "Z(1,0)", "X(0,1)"].
    """
    if n is None:
        n = len(row) // 2
    if shape is None and not linear_index:
        shape = (1, n)
    out = []
    for i in range(n):
        xi = int(row[i]) % 2
        zi = int(row[n + i]) % 2
        if (xi, zi) == (0, 0):
            if not skip_identity:
                out.append(f"I({i})" if linear_index else f"I{_qubit_to_coord(i, shape)}")
            continue
        pauli = "X" if (xi, zi) == (1, 0) else "Z" if (xi, zi) == (0, 1) else "Y"
        if linear_index:
            out.append(f"{pauli}({i})")
        else:
            (x, y) = _qubit_to_coord(i, shape)
            out.append(f"{pauli}({x},{y})")
    return out


def pretty_print_stabilizer(
    S: List[List[Union[int, float]]],
    *,
    labels: bool = True,
    one_line: bool = False,
    file: Any = None,
    shape: Optional[tuple] = None,
    coords: bool = True,
    linear_index: bool = False,
) -> None:
    """
    Pretty-print stabilizer matrix S as Pauli strings.

    When coords=True (default) and shape is set: ignore I and print only
    non-identity Paulis with coordinate pairs (x,y), e.g. "S1: Z(0,0) Z(1,0) X(0,1)".
    When shape is None: infer square grid if n is a perfect square, else (1, n).
    When coords=False: print full Pauli string (e.g. "XZZXI") for each row.

    Parameters
    ----------
    S : list of rows, each row length 2*n (X part | Z part)
    labels : if True, print "S1:", "S2:", ... before each string
    one_line : if True, print all strings on one line separated by spaces
    file : file-like to print to (default stdout)
    shape : (rows, cols) for qubit index -> (x,y). If None and coords True, use (L,L) when n=L^2 else (1,n).
    coords : if True, use P(x,y) format and skip I; if False, use full Pauli string

    Notes
    -----
    (x, y) uses row-major order: x = row, y = col, qubit index i = x*cols + y
    (so for a 3x3 grid, (0,0) is top-left and (2,2) is bottom-right).
    For the rotated surface code [[L²,1,L]], boundary stabilizers have weight 2;
    corner (0,0) is only in a Z check in the convention used by the builder.
    """
    if not S:
        return
    n = len(S[0]) // 2
    out = file if file is not None else __import__("sys").stdout

    if coords:
        if shape is None and not linear_index:
            L = int(round(n ** 0.5))
            shape = (L, L) if L * L == n else (1, n)
        strings = [
            " ".join(stabilizer_to_pauli_coords(row, shape, n, linear_index=linear_index))
            for row in S
        ]
    else:
        strings = [stabilizer_to_pauli_string(row, n) for row in S]

    if one_line:
        line = "  ".join(f"S{i+1}: {s}" if labels else s for i, s in enumerate(strings))
        print(line, file=out)
    else:
        for i, s in enumerate(strings):
            prefix = f"S{i+1}: " if labels else ""
            print(f"{prefix}{s}", file=out)


# [[9,1,3]] from builder (L=3)
STABILIZER_SURFACE_81_1_9 = rotated_surface_code_stabilizers(9)

# ---------------------------------------------------------------------------
# [[5,1,3]] 5-qubit code (stabilizer: XZZXI, IXZZX, XIXZZ, ZXIXZ)
# Symplectic (X|Z) rows: 4 x 10. Columns 0..4 = X, 5..9 = Z.
# ---------------------------------------------------------------------------
STABILIZER_5QUBIT_SYMPLECTIC = [
    [1, 0, 0, 1, 0, 0, 1, 1, 0, 0],  # S1: X Z Z X I
    [0, 1, 0, 0, 1, 0, 0, 1, 1, 0],  # S2: I X Z Z X
    [1, 0, 1, 0, 0, 0, 0, 0, 1, 1],  # S3: X I X Z Z
    [0, 1, 0, 1, 0, 1, 0, 0, 0, 1],  # S4: Z X I X Z
]

