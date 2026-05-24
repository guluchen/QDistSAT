from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
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
from .build_distance_constraints import *
from .compute_logical_basis import *
from .compute_css_split_distance import split_css_stabilizers, _logicals_pure_z_only, _logicals_pure_x_only

def min_distance_quantum_minmax_or_logicals(
    S: List[List[Union[int, float]]],
    solver_type: SolverType = SolverType.GLUCOSE3,
    max_distance: Optional[int] = None,
    *,
    timeout_sec: Optional[float] = None,
    encoding: Any = None,
    stats: Optional[Dict[str, Any]] = None,
    setup_timing_out: Optional[Dict[str, float]] = None,
    logical_basis_override: Optional[List[List[int]]] = None,
    debug: bool = False,
    on_minmax_row: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Optional[int]:
    """
    Alternate **card**-style trials (Σw≤k) to raise a lower bound and **refine**-style
    trials (Σw≤U−1) to shrink an upper bound until ``lb == ub`` (exact d) or ``timeout_sec``.

    On timeout without proving ``lb == ub``, sets ``stats`` keys ``minmax_lb``, ``minmax_ub``,
    ``minmax_exact`` (bool), and returns ``None``. When exact, returns ``d`` and sets
    ``minmax_lb == minmax_ub == d``.

    If ``on_minmax_row`` is set (or ``stats`` is set), each SAT call appends a snapshot to
    ``stats["minmax_rows_chrono"]`` with keys ``chrono_idx`` (1-based wall order), ``sector``
    (``\"full\"``), plus the usual detail-row fields.

    ``max_distance`` caps how high the **card** rounds probe (try ``Σw≤k`` for ``k`` up to
    ``min(n, max_distance)``). ``None`` means ``n``. The first witness solve uses the same cap
    (``Σw≤scan_cap``), so if no logical has weight ≤ ``scan_cap`` the search stops with no distance.
    """
    if CardEnc is None or EncType is None:
        raise ImportError("pysat.card (CardEnc) is required")
    if encoding is None:
        encoding = EncType.seqcounter
    m, cols = _matrix_shape(S)
    if m == 0 or cols % 2 != 0:
        return None
    n = cols // 2
    scan_cap = _minmax_scan_cap(n, max_distance)
    BIG = n + 1
    deadline = None if timeout_sec is None else time.monotonic() + float(timeout_sec)

    if logical_basis_override is not None:
        logical_basis = [[int(x) % 2 for x in row] for row in logical_basis_override]
        for row in logical_basis:
            if len(row) != 2 * n:
                raise ValueError(
                    f"logical_basis_override rows must have length 2n={2 * n}, got {len(row)}"
                )
        if setup_timing_out is not None:
            setup_timing_out["logical_basis_symplectic_sec"] = 0.0
    else:
        if setup_timing_out is not None:
            _t_lb = time.perf_counter()
        logical_basis = logical_basis_symplectic(S, n)
        if setup_timing_out is not None:
            setup_timing_out["logical_basis_symplectic_sec"] = time.perf_counter() - _t_lb
    if not logical_basis:
        return None

    n_vars_xz = 2 * n
    w_start = n_vars_xz + 1
    a_start = w_start + n
    top_id = a_start + len(logical_basis) - 1

    rows_full: List[Dict[str, Any]] = []
    kr = 0
    rows_chrono: List[Dict[str, Any]] = []
    chrono_box = [0]
    track_chrono = stats is not None or on_minmax_row is not None
    sat_cache_full: Dict[int, Tuple[bool, int]] = {}

    def _ub_label(u: int) -> str:
        return "∞" if u >= BIG else str(u)

    def _emit_chrono_full() -> None:
        if not track_chrono or not rows_full:
            return
        chrono_box[0] += 1
        d = dict(rows_full[-1])
        d["chrono_idx"] = chrono_box[0]
        d["sector"] = "full"
        d["bounds_str"] = f"[{lb},{_ub_label(ub)}]"
        rows_chrono.append(d)
        if stats is not None:
            stats["minmax_rows_chrono"] = rows_chrono
        if on_minmax_row is not None:
            on_minmax_row(d)

    lb = 1
    ub = BIG
    k_cursor = 1
    phase_card = True

    def _finish_exact(d: int) -> int:
        if stats is not None:
            stats["minmax_lb"] = d
            stats["minmax_ub"] = d
            stats["minmax_exact"] = True
            stats["minmax_rows_full"] = rows_full
            if track_chrono:
                stats["minmax_rows_chrono"] = rows_chrono
        return d

    def _finish_partial() -> None:
        if stats is not None:
            stats["minmax_lb"] = lb
            stats["minmax_ub"] = ub if ub < BIG else None
            stats["minmax_exact"] = False
            stats["minmax_rows_full"] = rows_full
            if track_chrono:
                stats["minmax_rows_chrono"] = rows_chrono

    # Initial upper bound: Σw ≤ n (vacuous on n qubits) — same feasible set as unconstrained refine start
    if not _minmax_before_deadline(deadline):
        _finish_partial()
        return None
    kr += 1
    sat0, w0 = _stabilizer_or_logicals_solve_atmost_k(
        S,
        logical_basis,
        n,
        m,
        scan_cap,
        solver_type,
        encoding,
        w_start=w_start,
        a_start=a_start,
        top_id=top_id,
        rows_out=rows_full,
        row_k=kr,
        refine_ctx="",
    )
    if rows_full:
        rows_full[-1]["refine_ctx"] = (
            f"no_card witness Σw={w0}" if sat0 else "no_card UNSAT"
        )
    if not sat0:
        _emit_chrono_full()
        if stats is not None:
            stats["minmax_lb"] = 1
            stats["minmax_ub"] = None
            stats["minmax_exact"] = False
            stats["minmax_rows_full"] = rows_full
        return None
    ub = min(ub, w0)
    _emit_chrono_full()
    if lb >= ub:
        return _finish_exact(ub)

    while _minmax_before_deadline(deadline):
        if lb >= ub:
            return _finish_exact(ub)
        if phase_card:
            if k_cursor > scan_cap:
                phase_card = False
                continue
            if not _minmax_before_deadline(deadline):
                break
            kr += 1
            k_card = k_cursor
            if k_card in sat_cache_full:
                sat, w = sat_cache_full[k_card]
                _minmax_append_row(
                    rows_full,
                    kr,
                    sat,
                    0.0,
                    f"card Σw≤{k_card} (cache)",
                    None,
                    None,
                )
            else:
                sat, w = _stabilizer_or_logicals_solve_atmost_k(
                    S,
                    logical_basis,
                    n,
                    m,
                    k_card,
                    solver_type,
                    encoding,
                    w_start=w_start,
                    a_start=a_start,
                    top_id=top_id,
                    rows_out=rows_full,
                    row_k=kr,
                    refine_ctx=f"card Σw≤{k_card}",
                )
                sat_cache_full[k_card] = (sat, w)
            if not sat:
                lb = max(lb, k_card + 1)
            else:
                ub = min(ub, w)
            _emit_chrono_full()
            if lb >= ub:
                return _finish_exact(ub)
            k_cursor += 1
            phase_card = False
        else:
            if ub <= lb:
                return _finish_exact(ub)
            if not _minmax_before_deadline(deadline):
                break
            kr += 1
            kb = ub - 1
            if kb in sat_cache_full:
                sat_r, w_r = sat_cache_full[kb]
                _minmax_append_row(
                    rows_full,
                    kr,
                    sat_r,
                    0.0,
                    f"Σw≤{kb} (cache)",
                    None,
                    None,
                )
            else:
                sat_r, w_r = _stabilizer_or_logicals_solve_atmost_k(
                    S,
                    logical_basis,
                    n,
                    m,
                    kb,
                    solver_type,
                    encoding,
                    w_start=w_start,
                    a_start=a_start,
                    top_id=top_id,
                    rows_out=rows_full,
                    row_k=kr,
                    refine_ctx=f"Σw≤{kb}",
                )
                sat_cache_full[kb] = (sat_r, w_r)
            if not sat_r:
                _emit_chrono_full()
                return _finish_exact(ub)
            ub = w_r
            _emit_chrono_full()
            if lb >= ub:
                return _finish_exact(ub)
            phase_card = True
            if debug:
                print(f"[DEBUG] minmax full: refine -> ub={ub}", flush=True)

    if lb >= ub:
        return _finish_exact(ub)
    _finish_partial()
    return None


def min_distance_quantum_css_split_minmax(
    Hx: List[List[Union[int, float]]],
    Hz: List[List[Union[int, float]]],
    solver_type: SolverType = SolverType.GLUCOSE3,
    max_distance: Optional[int] = None,
    *,
    timeout_sec: Optional[float] = None,
    encoding: Any = None,
    stats: Optional[Dict[str, Any]] = None,
    setup_timing_out: Optional[Dict[str, float]] = None,
    logical_basis_override: Optional[List[List[int]]] = None,
    debug: bool = False,
    on_minmax_row: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Optional[int]:
    """
    ``minmax`` on CSS split: for each round, Z and X sectors use the **same** card index ``k_cursor``;
    per-sector ``lb_*`` / ``ub_*`` are merged as ``lb = min(lb_z, lb_x)``, ``ub = min(ub_z, ub_x)``
    (valid for ``d = min(d_Z, d_X)``). Alternates a **card** round with a **refine** round on both
    sectors (same semantics as full-body minmax per sector).

    With ``on_minmax_row`` or ``stats``, each SAT completion appends to ``stats["minmax_rows_chrono"]``
    a row copy with ``chrono_idx`` (wall-clock order) and ``sector`` ``\"z\"`` / ``\"x\"``.

    ``max_distance`` caps sector card rounds and the first witness solve at
    ``min(n, max_distance)`` (``None`` → ``n``), matching other distance strategies.
    """
    if CardEnc is None or EncType is None:
        raise ImportError("pysat.card (CardEnc) is required")
    if encoding is None:
        encoding = EncType.seqcounter
    if not Hx and not Hz:
        return None
    n = len(Hx[0]) if Hx else len(Hz[0]) if Hz else 0
    if n == 0:
        return None
    scan_cap = _minmax_scan_cap(n, max_distance)
    BIG = n + 1
    deadline = None if timeout_sec is None else time.monotonic() + float(timeout_sec)

    if logical_basis_override is not None:
        logical_basis = [[int(x) % 2 for x in row] for row in logical_basis_override]
        for row in logical_basis:
            if len(row) != 2 * n:
                raise ValueError(
                    f"logical_basis_override rows must have length 2n={2 * n}, got {len(row)}"
                )
        if setup_timing_out is not None:
            setup_timing_out["logical_basis_symplectic_sec"] = 0.0
    else:
        S0 = [list(row) + [0] * n for row in Hx] + [[0] * n + list(row) for row in Hz]
        if setup_timing_out is not None:
            _t_lb = time.perf_counter()
        logical_basis = logical_basis_symplectic(S0, n)
        if setup_timing_out is not None:
            setup_timing_out["logical_basis_symplectic_sec"] = time.perf_counter() - _t_lb
    if not logical_basis:
        return None

    lz = _logicals_pure_z_only(logical_basis, n)
    lx = _logicals_pure_x_only(logical_basis, n)
    if not lz or not lx:
        return None

    lb_z = lb_x = 1
    ub_z = ub_x = BIG
    k_log_z = len(lz)
    k_log_x = len(lx)
    a_start = n + 1
    top_id_z = a_start + k_log_z - 1
    top_id_x = a_start + k_log_x - 1
    k_cursor = 1
    phase_card = True

    rows_z: List[Dict[str, Any]] = []
    rows_x: List[Dict[str, Any]] = []
    kz = 0
    kx = 0
    rows_chrono: List[Dict[str, Any]] = []
    chrono_box = [0]
    track_chrono = stats is not None or on_minmax_row is not None
    sat_cache: Dict[Tuple[str, int], Tuple[bool, int]] = {}

    def _ub_lab(u: int) -> str:
        return "∞" if u >= BIG else str(u)

    def _emit_chrono(src: List[Dict[str, Any]], sector: str) -> None:
        if not track_chrono or not src:
            return
        chrono_box[0] += 1
        d = dict(src[-1])
        d["chrono_idx"] = chrono_box[0]
        d["sector"] = sector
        glb, gub = _merge_lb_ub()
        d["bounds_str"] = (
            f"Z[{lb_z},{_ub_lab(ub_z)}] X[{lb_x},{_ub_lab(ub_x)}] "
            f"⇒[{glb},{_ub_lab(gub)}]"
        )
        rows_chrono.append(d)
        if stats is not None:
            stats["minmax_rows_chrono"] = rows_chrono
        if on_minmax_row is not None:
            on_minmax_row(d)

    def _merge_lb_ub() -> Tuple[int, int]:
        return min(lb_z, lb_x), min(ub_z, ub_x)

    def _merged_tight() -> Optional[int]:
        """If merged lb >= merged ub, return exact d; else None."""
        glb, gub = _merge_lb_ub()
        if glb >= gub:
            return gub
        return None

    def _finish_exact(d: int) -> int:
        if stats is not None:
            stats["minmax_lb"] = d
            stats["minmax_ub"] = d
            stats["minmax_exact"] = True
            stats["css_minmax_lb_Z"] = lb_z
            stats["css_minmax_lb_X"] = lb_x
            stats["css_minmax_ub_Z"] = None if ub_z >= BIG else ub_z
            stats["css_minmax_ub_X"] = None if ub_x >= BIG else ub_x
            stats["minmax_rows_z"] = rows_z
            stats["minmax_rows_x"] = rows_x
            if track_chrono:
                stats["minmax_rows_chrono"] = rows_chrono
        return d

    def _finish_partial() -> None:
        glb, gub = _merge_lb_ub()
        if stats is not None:
            stats["minmax_lb"] = glb
            stats["minmax_ub"] = None if gub >= BIG else gub
            stats["minmax_exact"] = False
            stats["css_minmax_lb_Z"] = lb_z
            stats["css_minmax_lb_X"] = lb_x
            stats["css_minmax_ub_Z"] = None if ub_z >= BIG else ub_z
            stats["css_minmax_ub_X"] = None if ub_x >= BIG else ub_x
            stats["minmax_rows_z"] = rows_z
            stats["minmax_rows_x"] = rows_x
            if track_chrono:
                stats["minmax_rows_chrono"] = rows_chrono

    if not _minmax_before_deadline(deadline):
        _finish_partial()
        return None
    kz += 1
    satz0, wz0 = _css_sector_solve_atmost_k(
        Hx,
        lz,
        n,
        "z",
        scan_cap,
        solver_type,
        encoding,
        a_start=a_start,
        top_id=top_id_z,
        rows_out=rows_z,
        row_k=kz,
        refine_ctx="",
    )
    if rows_z:
        rows_z[-1]["refine_ctx"] = (
            f"no_card witness|v|={wz0}" if satz0 else "no_card UNSAT"
        )
    if satz0:
        ub_z = int(wz0)
    _emit_chrono(rows_z, "z")
    kx += 1
    satx0, wx0 = _css_sector_solve_atmost_k(
        Hz,
        lx,
        n,
        "x",
        scan_cap,
        solver_type,
        encoding,
        a_start=a_start,
        top_id=top_id_x,
        rows_out=rows_x,
        row_k=kx,
        refine_ctx="",
    )
    if rows_x:
        rows_x[-1]["refine_ctx"] = (
            f"no_card witness|v|={wx0}" if satx0 else "no_card UNSAT"
        )
    if satx0:
        ub_x = int(wx0)
    _emit_chrono(rows_x, "x")
    if not satz0 or not satx0:
        _finish_partial()
        return None
    lb, ub = _merge_lb_ub()
    if lb >= ub:
        return _finish_exact(ub)

    # Interleave X/Z: first card round is |v|≤k X then |v|≤k Z; later rounds run the
    # sector that solved faster last time first (card pair compares card times; refine
    # pair compares refine times when both ran).
    order_x_before_z = True

    while _minmax_before_deadline(deadline):
        lb, ub = _merge_lb_ub()
        if lb >= ub:
            return _finish_exact(ub)
        if phase_card:
            k_sync = max(k_cursor, lb_z, lb_x)
            if k_sync > scan_cap:
                phase_card = False
                continue
            if not _minmax_before_deadline(deadline):
                break

            def _card_solve_z() -> Tuple[bool, int]:
                nonlocal kz, lb_z, ub_z
                kz += 1
                key = ("z", k_sync)
                if key in sat_cache:
                    satz, wz = sat_cache[key]
                    _minmax_append_row(
                        rows_z,
                        kz,
                        satz,
                        0.0,
                        f"|v|≤{k_sync} (cache)",
                        None,
                        None,
                    )
                else:
                    satz, wz = _css_sector_solve_atmost_k(
                        Hx,
                        lz,
                        n,
                        "z",
                        k_sync,
                        solver_type,
                        encoding,
                        a_start=a_start,
                        top_id=top_id_z,
                        rows_out=rows_z,
                        row_k=kz,
                        refine_ctx=f"|v|≤{k_sync}",
                    )
                    sat_cache[key] = (satz, wz)
                if not satz:
                    lb_z = max(lb_z, k_sync + 1)
                else:
                    ub_z = min(ub_z, wz)
                _emit_chrono(rows_z, "z")
                return satz, wz

            def _card_solve_x() -> Tuple[bool, int]:
                nonlocal kx, lb_x, ub_x
                kx += 1
                key = ("x", k_sync)
                if key in sat_cache:
                    satx, wx = sat_cache[key]
                    _minmax_append_row(
                        rows_x,
                        kx,
                        satx,
                        0.0,
                        f"|v|≤{k_sync} (cache)",
                        None,
                        None,
                    )
                else:
                    satx, wx = _css_sector_solve_atmost_k(
                        Hz,
                        lx,
                        n,
                        "x",
                        k_sync,
                        solver_type,
                        encoding,
                        a_start=a_start,
                        top_id=top_id_x,
                        rows_out=rows_x,
                        row_k=kx,
                        refine_ctx=f"|v|≤{k_sync}",
                    )
                    sat_cache[key] = (satx, wx)
                if not satx:
                    lb_x = max(lb_x, k_sync + 1)
                else:
                    ub_x = min(ub_x, wx)
                _emit_chrono(rows_x, "x")
                return satx, wx

            if order_x_before_z:
                _card_solve_x()
                mt = _merged_tight()
                if mt is not None:
                    return _finish_exact(mt)
                _card_solve_z()
            else:
                _card_solve_z()
                mt = _merged_tight()
                if mt is not None:
                    return _finish_exact(mt)
                _card_solve_x()
            mt = _merged_tight()
            if mt is not None:
                return _finish_exact(mt)
            tz_c = float(rows_z[-1]["time_sec"])
            tx_c = float(rows_x[-1]["time_sec"])
            order_x_before_z = tx_c <= tz_c

            k_cursor = k_sync + 1
            phase_card = False
            if debug:
                print(
                    f"[DEBUG] minmax css card k={k_sync} -> lb_z={lb_z} lb_x={lb_x} "
                    f"ub_z={ub_z} ub_x={ub_x}",
                    flush=True,
                )
        else:
            lb, ub = _merge_lb_ub()
            if ub <= lb:
                return _finish_exact(ub)

            need_z = (
                ub_z < BIG
                and ub_z > lb_z
                and _minmax_before_deadline(deadline)
            )
            need_x = (
                ub_x < BIG
                and ub_x > lb_x
                and _minmax_before_deadline(deadline)
            )

            def _refine_solve_z() -> None:
                nonlocal kz, lb_z, ub_z
                kz += 1
                kb = ub_z - 1
                key = ("z", kb)
                if key in sat_cache:
                    satz, wz = sat_cache[key]
                    _minmax_append_row(
                        rows_z,
                        kz,
                        satz,
                        0.0,
                        f"|v|≤{kb} (cache)",
                        None,
                        None,
                    )
                else:
                    satz, wz = _css_sector_solve_atmost_k(
                        Hx,
                        lz,
                        n,
                        "z",
                        kb,
                        solver_type,
                        encoding,
                        a_start=a_start,
                        top_id=top_id_z,
                        rows_out=rows_z,
                        row_k=kz,
                        refine_ctx=f"|v|≤{kb}",
                    )
                    sat_cache[key] = (satz, wz)
                if not satz:
                    lb_z = max(lb_z, ub_z)
                else:
                    ub_z = wz
                _emit_chrono(rows_z, "z")

            def _refine_solve_x() -> None:
                nonlocal kx, lb_x, ub_x
                kx += 1
                kb = ub_x - 1
                key = ("x", kb)
                if key in sat_cache:
                    satx, wx = sat_cache[key]
                    _minmax_append_row(
                        rows_x,
                        kx,
                        satx,
                        0.0,
                        f"|v|≤{kb} (cache)",
                        None,
                        None,
                    )
                else:
                    satx, wx = _css_sector_solve_atmost_k(
                        Hz,
                        lx,
                        n,
                        "x",
                        kb,
                        solver_type,
                        encoding,
                        a_start=a_start,
                        top_id=top_id_x,
                        rows_out=rows_x,
                        row_k=kx,
                        refine_ctx=f"|v|≤{kb}",
                    )
                    sat_cache[key] = (satx, wx)
                if not satx:
                    lb_x = max(lb_x, ub_x)
                else:
                    ub_x = wx
                _emit_chrono(rows_x, "x")

            ran_z = ran_x = False
            if order_x_before_z:
                if need_x:
                    _refine_solve_x()
                    ran_x = True
                    mt = _merged_tight()
                    if mt is not None:
                        return _finish_exact(mt)
                if need_z:
                    _refine_solve_z()
                    ran_z = True
                    mt = _merged_tight()
                    if mt is not None:
                        return _finish_exact(mt)
            else:
                if need_z:
                    _refine_solve_z()
                    ran_z = True
                    mt = _merged_tight()
                    if mt is not None:
                        return _finish_exact(mt)
                if need_x:
                    _refine_solve_x()
                    ran_x = True
                    mt = _merged_tight()
                    if mt is not None:
                        return _finish_exact(mt)

            if ran_z and ran_x:
                tz_r = float(rows_z[-1]["time_sec"])
                tx_r = float(rows_x[-1]["time_sec"])
                order_x_before_z = tx_r <= tz_r

            phase_card = True

    lb, ub = _merge_lb_ub()
    if lb >= ub:
        return _finish_exact(ub)
    _finish_partial()
    return None


def min_distance_quantum_minmax_auto(
    S: List[List[Union[int, float]]],
    solver_type: SolverType = SolverType.GLUCOSE3,
    max_distance: Optional[int] = None,
    *,
    timeout_sec: Optional[float] = None,
    encoding: Any = None,
    stats: Optional[Dict[str, Any]] = None,
    setup_timing_out: Optional[Dict[str, float]] = None,
    logical_basis_override: Optional[List[List[int]]] = None,
    debug: bool = False,
    on_minmax_row: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Optional[int]:
    """Use CSS-split minmax when ``S`` is CSS-shaped; else full stabilizer minmax.

    ``max_distance`` is passed through to the chosen minmax implementation (scan cap
    ``min(n, max_distance)``, or full ``n`` when ``None``).
    """
    m, cols = _matrix_shape(S)
    if m == 0 or cols % 2 != 0:
        return None
    nloc = cols // 2
    sp = split_css_stabilizers(S, nloc)
    if sp is not None:
        hx, hz = sp
        if stats is not None:
            stats["minmax_mode"] = "css_split"
        return min_distance_quantum_css_split_minmax(
            hx,
            hz,
            solver_type=solver_type,
            max_distance=max_distance,
            timeout_sec=timeout_sec,
            encoding=encoding,
            stats=stats,
            setup_timing_out=setup_timing_out,
            logical_basis_override=logical_basis_override,
            debug=debug,
            on_minmax_row=on_minmax_row,
        )
    if stats is not None:
        stats["minmax_mode"] = "full"
    return min_distance_quantum_minmax_or_logicals(
        S,
        solver_type=solver_type,
        max_distance=max_distance,
        timeout_sec=timeout_sec,
        encoding=encoding,
        stats=stats,
        setup_timing_out=setup_timing_out,
        logical_basis_override=logical_basis_override,
        debug=debug,
        on_minmax_row=on_minmax_row,
    )
