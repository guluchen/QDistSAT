from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from .build_distance_constraints import _matrix_shape

def _kernel_gf2(M: List[List[Union[int, float]]]) -> List[List[int]]:
    """
    Compute a basis for the right kernel of M over GF(2).
    Returns list of basis vectors; each vector has length cols.
    v in kernel iff M @ v = 0 (mod 2).
    """
    m, cols = _matrix_shape(M)
    if m == 0:
        return [[1 if j == i else 0 for j in range(cols)] for i in range(cols)]
    mat = [[int(M[i][j]) % 2 for j in range(cols)] for i in range(m)]
    pivot_row_for_col = [-1] * cols
    pivot_cols = []
    row = 0
    for col in range(cols):
        if row >= m:
            break
        for r in range(row, m):
            if mat[r][col] == 1:
                mat[row], mat[r] = mat[r], mat[row]
                pivot_cols.append(col)
                pivot_row_for_col[col] = row
                for r2 in range(m):
                    if r2 != row and mat[r2][col] == 1:
                        for c in range(cols):
                            mat[r2][c] = (mat[r2][c] + mat[row][c]) % 2
                row += 1
                break
    free_cols = [c for c in range(cols) if pivot_row_for_col[c] < 0]
    if not free_cols:
        return []
    basis = []
    for c in free_cols:
        w = [0] * cols
        w[c] = 1
        for col in reversed(pivot_cols):
            r = pivot_row_for_col[col]
            w[col] = sum(mat[r][j] * w[j] for j in range(col + 1, cols)) % 2
        basis.append(w)
    return basis


def _kernel_gf2_with_n(
    M: List[List[Union[int, float]]], n: int
) -> List[List[int]]:
    """Right kernel of ``M``; if ``M`` has no rows, kernel is all of ``F_2^n``."""
    if not M:
        return [[1 if j == i else 0 for j in range(n)] for i in range(n)]
    return _kernel_gf2(M)


def _vector_in_rref_span(
    rref: List[List[int]],
    pivot_cols: List[int],
    v: List[int],
    n: int,
) -> bool:
    work = [int(v[j]) % 2 for j in range(n)]
    for row_idx, pcol in enumerate(pivot_cols):
        if work[pcol]:
            pr = rref[row_idx]
            work = [(work[c] + pr[c]) % 2 for c in range(n)]
    return all(x == 0 for x in work)


def _rref_add_to_span(
    rref: List[List[int]],
    pivot_cols: List[int],
    v: List[int],
    n: int,
) -> bool:
    """
    Extend ``rref`` / ``pivot_cols`` with ``v`` if not already in their span.

    Returns True when ``v`` was already in the span.
    """
    work = [int(v[j]) % 2 for j in range(n)]
    for row_idx, pcol in enumerate(pivot_cols):
        if work[pcol]:
            pr = rref[row_idx]
            work = [(work[c] + pr[c]) % 2 for c in range(n)]
    pivot = next((c for c in range(n) if work[c]), None)
    if pivot is None:
        return True
    new_row = work
    rref.append(new_row)
    pivot_cols.append(pivot)
    idx = len(rref) - 1
    for r in range(idx):
        if rref[r][pivot]:
            rref[r] = [(rref[r][c] + new_row[c]) % 2 for c in range(n)]
    return False


def _quotient_basis_ker_mod_rowspan(
    parity: List[List[Union[int, float]]],
    mod_rows: List[List[Union[int, float]]],
    n: int,
) -> List[List[int]]:
    """
    Basis of ``ker(parity) / span(mod_rows)`` over GF(2), as ``n``-bit column vectors.

    ``parity`` and ``mod_rows`` are row matrices (each row in ``F_2^n``).
    """
    ker = _kernel_gf2_with_n(parity, n)
    rref: List[List[int]] = []
    pivot_cols: List[int] = []
    for row in mod_rows:
        _rref_add_to_span(rref, pivot_cols, [int(x) % 2 for x in row], n)
    out: List[List[int]] = []
    for v in ker:
        vv = [int(x) % 2 for x in v]
        if _vector_in_rref_span(rref, pivot_cols, vv, n):
            continue
        out.append(vv)
        _rref_add_to_span(rref, pivot_cols, vv, n)
    return out


def css_logical_nbit_rows(
    Hx: List[List[Union[int, float]]],
    Hz: List[List[Union[int, float]]],
) -> Tuple[List[List[int]], List[List[int]]]:
    """
    CSS logical representatives as ``n``-bit ``F_2^n`` rows (not symplectic).

    - **Z-type** (Pauli Z on qubits): ``ker(Hx) / row(Hz)``.
    - **X-type** (Pauli X on qubits): ``ker(Hz) / row(Hx)``, symplectic ``[x|0]`` later.

    Assumes ``Hx @ Hz^T = 0`` when both are nonempty.
    """
    n = len(Hx[0]) if Hx else len(Hz[0]) if Hz else 0
    if n == 0:
        return [], []
    hx_rows = Hx if Hx else []
    hz_rows = Hz if Hz else []
    bz = _quotient_basis_ker_mod_rowspan(hx_rows, hz_rows, n)
    bx = _quotient_basis_ker_mod_rowspan(hz_rows, hx_rows, n)
    return bz, bx


def symplectic_from_css_nbit_rows(
    z_rows: List[List[int]],
    x_rows: List[List[int]],
    n: int,
) -> List[List[int]]:
    """
    Build symplectic logical rows from CSS ``n``-bit representatives: ``[0|z]`` then ``[x|0]``.
    """
    for i, z in enumerate(z_rows):
        if len(z) != n:
            raise ValueError(f"z_rows[{i}] length {len(z)} != n={n}")
    for i, x in enumerate(x_rows):
        if len(x) != n:
            raise ValueError(f"x_rows[{i}] length {len(x)} != n={n}")
    logicals: List[List[int]] = []
    for z in z_rows:
        logicals.append([0] * n + [int(v) % 2 for v in z])
    for x in x_rows:
        logicals.append([int(v) % 2 for v in x] + [0] * n)
    return logicals


def logical_basis_css_from_parity_checks(
    Hx: List[List[Union[int, float]]],
    Hz: List[List[Union[int, float]]],
) -> List[List[int]]:
    """
    CSS logical Pauli operators from separate parity checks (same span as symplectic dual for CSS).

    - **Z-type logicals** (Pauli Z on qubits): ``ker(Hx) / row(Hz)``, symplectic ``[0|z]``.
    - **X-type logicals**: ``ker(Hz) / row(Hx)``, symplectic ``[x|0]``.

    Assumes the usual CSS condition ``Hx @ Hz^T = 0`` (``row(Hz) ⊆ ker(Hx)``). Rows are listed
    as for ``S = [Hx|0] ∥ [0|Hz]``. Output order: all Z-type symplectic rows, then all X-type.
    """
    n = len(Hx[0]) if Hx else len(Hz[0]) if Hz else 0
    if n == 0:
        return []
    bz, bx = css_logical_nbit_rows(Hx, Hz)
    return symplectic_from_css_nbit_rows(bz, bx, n)


def _in_rowspan(v: List[int], S: List[List[Union[int, float]]]) -> bool:
    """Check if v is in the row span of S over GF(2) (linear combination membership via Gaussian elimination)."""
    m, cols = _matrix_shape(S)
    if m == 0:
        return all(vi % 2 == 0 for vi in v)
    # Augment S with v as extra row; v in rowspan(S) iff rank([S;v]) = rank(S)
    M = [[int(S[i][j]) % 2 for j in range(cols)] for i in range(m)]
    M.append([int(v[j]) % 2 for j in range(cols)])
    # Row reduce and check if last row becomes zero
    pivot_cols = []
    for row in range(len(M)):
        for col in range(cols):
            if col in pivot_cols:
                continue
            if M[row][col] == 1:
                pivot_cols.append(col)
                for r2 in range(len(M)):
                    if r2 != row and M[r2][col] == 1:
                        for c in range(cols):
                            M[r2][c] = (M[r2][c] + M[row][c]) % 2
                break
    return all(M[-1][c] == 0 for c in range(cols))


def _symp(v: List[int], w: List[int], n: int) -> int:
    """Symplectic product ⟨(vx|vz), (wx|wz)⟩ = vx·wz + vz·wx (mod 2)."""
    return (sum(v[i] * w[n + i] for i in range(n)) + sum(v[n + i] * w[i] for i in range(n))) % 2


def logical_basis_symplectic(S: List[List[Union[int, float]]], n: int) -> List[List[int]]:
    """
    Extract logical basis {X̄ᵢ, Z̄ᵢ} from symplectic dual N = ker(M) via symplectic elimination.
    M = SΛ with Λ swapping X|Z, so M[j] = [S[j,n:2n], S[j,0:n]]. N = S^\\perp.
    Returns list of 2k logical operators [X̄₁, Z̄₁, X̄₂, Z̄₂, ..., X̄ₖ, Z̄ₖ].
    """
    m = len(S)
    M = [[int(S[j][n + i]) % 2 for i in range(n)] + [int(S[j][i]) % 2 for i in range(n)] for j in range(m)]
    basis = _kernel_gf2(M)
    if not basis:
        return []
    # Span to exclude: S (stabilizer) + pairs found so far
    excluded: List[List[int]] = [list(row) for row in S]

    def in_span(v: List[int], rows: List[List[int]]) -> bool:
        if not rows:
            return all(vi % 2 == 0 for vi in v)
        mat = [list(r) for r in rows]
        mat.append(list(v))
        cols = len(v)
        pivot_cols: List[int] = []
        for row in range(len(mat)):
            for col in range(cols):
                if col in pivot_cols:
                    continue
                if mat[row][col] % 2 == 1:
                    pivot_cols.append(col)
                    for r2 in range(len(mat)):
                        if r2 != row and mat[r2][col] % 2 == 1:
                            for c in range(cols):
                                mat[r2][c] = (mat[r2][c] + mat[row][c]) % 2
                    break
        return all(mat[-1][c] % 2 == 0 for c in range(cols))

    logicals: List[List[int]] = []
    used = [False] * len(basis)
    basis_vecs = [list(v) for v in basis]

    for _ in range(len(basis) // 2):  # at most k pairs
        found_pair = False
        for i in range(len(basis_vecs)):
            if used[i]:
                continue
            v = basis_vecs[i]
            if in_span(v, excluded):
                continue
            for j in range(len(basis_vecs)):
                if used[j] or i == j:
                    continue
                w = basis_vecs[j]
                if in_span(w, excluded):
                    continue
                if _symp(v, w, n) == 1:
                    logicals.append(v)
                    logicals.append(w)
                    excluded.append(v)
                    excluded.append(w)
                    used[i] = used[j] = True
                    # Orthogonalize remaining: u += ⟨u,v⟩w + ⟨u,w⟩v
                    for k in range(len(basis_vecs)):
                        if used[k]:
                            continue
                        u = basis_vecs[k]
                        sp_uv = _symp(u, v, n)
                        sp_uw = _symp(u, w, n)
                        if sp_uv or sp_uw:
                            basis_vecs[k] = [(u[c] + sp_uv * w[c] + sp_uw * v[c]) % 2 for c in range(2 * n)]
                    found_pair = True
                    break
            if found_pair:
                break
        if not found_pair:
            break
    return logicals

