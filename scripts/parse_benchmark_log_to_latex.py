#!/usr/bin/env python3
"""
Parse benchmark_solver_performance.py log output and emit an aggregate LaTeX table.

Includes every (solver, strategy) configuration present in the log.

Usage:
  python scripts/parse_benchmark_log_to_latex.py logs/BB_bench_0521.log
  python scripts/parse_benchmark_log_to_latex.py logs/BB_bench_0521.log -o table.tex
  python scripts/parse_benchmark_log_to_latex.py logs/BB_bench_0521.log --sort solved
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

BENCHMARK_RE = re.compile(
    r"^Benchmark:\s+(\S+)\s+\(n=(\d+),",
)
RESULT_LINE_RE = re.compile(
    r"^(\S+)\s+(\S+)\s+(\S+)\s+"
    r"([\d.]+|-)\s+"
    r"(\S+)\s+(\S+)\s+"
    r"(\S+)\s+"
    r"(OK|timeout)\s*$"
)
STRATEGY_RESULT_LINE_RE = re.compile(
    r"^(\S+)\s+(\S+)\s+"
    r"([\d.]+|-)\s+"
    r"(\S+)\s+(\S+)\s+"
    r"(\S+)\s+"
    r"(OK|timeout)\s*$"
)

# Pretty names for LaTeX (unknown ids fall back to escaped raw tokens).
SOLVER_DISPLAY: dict[str, str] = {
    "z3py": "Z3",
    "cvc5": "CVC5",
    "minisat22": "MiniSat22",
    "minisatgh": "MiniSat-GH",
    "glucose3": "Glucose3",
    "glucose4": "Glucose4",
    "glucose42": "Glucose42",
    "cadical103": "CaDiCaL103",
    "cadical153": "CaDiCaL153",
    "cadical195": "CaDiCaL195",
    "lingeling": "Lingeling",
    "maplesat": "MapleSAT",
    "mergesat3": "MergeSAT3",
    "minicard": "MiniCard",
    "gluecard3": "Gluecard3",
    "gluecard4": "Gluecard4",
    "cryptosat": "CryptoMiniSat",
    "rc2-g3": "RC2-Glucose3",
    "rc2-g4": "RC2-Glucose4",
    "rc2-minisat22": "RC2-MiniSat22",
    "rc2-cadical195": "RC2-CaDiCaL195",
    "rc2-cryptosat": "RC2-CryptoMiniSat",
    "rc2-glucose42": "RC2-Glucose42",
    "cashw-coreplus": "CASHW-CorePlus",
    "cashw-coreplus-mse22": "CASHW-CorePlus-MSE22",
    "evalmaxsat": "EvalMaxSAT",
    "maxcdcl": "MaxCDCL",
    "open-wbo": "Open-WBO",
}

CARD_DISPLAY: dict[str, str] = {
    "standard": "Standard",
    "maxsat": "MaxSAT",
}

ENCODING_DISPLAY: dict[str, str] = {
    "seqcounter": "Sequential Counter",
    "kmtotalizer": "Totalizer",
    "mtotalizer": "Totalizer",
    "totalizer": "Totalizer",
    "native": "Native Cardinality",
    "maxsat": "MaxSAT",
    "log": "Log",
}


@dataclass(frozen=True)
class RunRecord:
    stem: str
    solver: str
    card: str
    encoding: str
    time_sec: float
    result: str
    status: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.solver, self.card, self.encoding)

    @property
    def exact_distance(self) -> Optional[int]:
        if self.status != "OK":
            return None
        try:
            return int(self.result)
        except ValueError:
            return None


def parse_log(text: str) -> tuple[list[str], list[RunRecord]]:
    stems: list[str] = []
    records: list[RunRecord] = []
    current_stem: Optional[str] = None
    in_table = False
    table_has_strategy_column = False

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        m_bench = BENCHMARK_RE.match(line)
        if m_bench:
            current_stem = m_bench.group(1)
            if current_stem not in stems:
                stems.append(current_stem)
            in_table = False
            continue

        if line.startswith("# Multi-stem summary"):
            in_table = False
            continue

        if line.startswith("Solver") and ("Strategy" in line or "Encoding" in line):
            in_table = True
            table_has_strategy_column = "Strategy" in line
            continue

        if not in_table or current_stem is None:
            continue

        if line.startswith("---"):
            continue

        if line.startswith("Completed:") or line.startswith("Fastest:"):
            in_table = False
            continue

        if table_has_strategy_column:
            m_row = STRATEGY_RESULT_LINE_RE.match(line)
            if not m_row:
                continue
            solver, strategy, time_s, _vars, _clauses, result, status = m_row.groups()
            card = encoding = strategy.lower()
        else:
            m_row = RESULT_LINE_RE.match(line)
            if not m_row:
                continue
            solver, card, encoding, time_s, _vars, _clauses, result, status = m_row.groups()
            card = card.lower()
            encoding = encoding.lower()
        records.append(
            RunRecord(
                stem=current_stem,
                solver=solver.lower(),
                card=card,
                encoding=encoding,
                time_sec=float(time_s) if time_s != "-" else 0.0,
                result=result,
                status=status,
            )
        )

    return stems, records


def unique_config_keys(records: Iterable[RunRecord]) -> list[tuple[str, str, str]]:
    seen: set[tuple[str, str, str]] = set()
    keys: list[tuple[str, str, str]] = []
    for rec in records:
        if rec.key not in seen:
            seen.add(rec.key)
            keys.append(rec.key)
    return keys


def _title_case_id(solver_id: str) -> str:
    """Fallback: rc2-minisat22 -> RC2-Minisat22."""
    parts = solver_id.split("-")
    return "-".join(p[:1].upper() + p[1:] if p else p for p in parts)


def solver_display_name(solver_id: str) -> str:
    return SOLVER_DISPLAY.get(solver_id, _title_case_id(solver_id))


def encoding_display_name(solver_id: str, card: str, encoding: str) -> str:
    if card == encoding:
        if card == "maxsat":
            return "MaxSAT"
        if card in ENCODING_DISPLAY:
            return ENCODING_DISPLAY[card]
        if card in CARD_DISPLAY:
            return CARD_DISPLAY[card]
    if card == "maxsat" and encoding == "maxsat":
        return "MaxSAT"
    enc = ENCODING_DISPLAY.get(encoding, encoding)
    if solver_id == "cryptosat" and card == "standard":
        return f"XOR + {enc}"
    if card == "standard":
        return enc
    card_label = CARD_DISPLAY.get(card, card)
    enc_label = ENCODING_DISPLAY.get(encoding, encoding)
    if card_label == enc_label:
        return card_label
    return f"{card_label} ({enc_label})"


@dataclass
class AggregateStats:
    solved: int
    total_stems: int
    avg_time_sec: Optional[float]
    max_exact_distance: Optional[int]


def aggregate(
    records: Iterable[RunRecord],
    key: tuple[str, str, str],
    stems: list[str],
) -> AggregateStats:
    by_stem: dict[str, list[RunRecord]] = defaultdict(list)
    for rec in records:
        if rec.key == key:
            by_stem[rec.stem].append(rec)

    ok_times: list[float] = []
    exact_distances: list[int] = []
    solved = 0

    for stem in stems:
        runs = by_stem.get(stem, [])
        ok_runs = [r for r in runs if r.status == "OK"]
        if not ok_runs:
            continue
        best = ok_runs[0]
        solved += 1
        ok_times.append(best.time_sec)
        if best.exact_distance is not None:
            exact_distances.append(best.exact_distance)

    avg_time = sum(ok_times) / len(ok_times) if ok_times else None
    max_d = max(exact_distances) if exact_distances else None
    return AggregateStats(
        solved=solved,
        total_stems=len(stems),
        avg_time_sec=avg_time,
        max_exact_distance=max_d,
    )


def _fmt_num(value: Optional[float], places: int = 3) -> str:
    if value is None:
        return "--"
    return f"{value:.{places}f}"


def _fmt_int(value: Optional[int]) -> str:
    if value is None:
        return "--"
    return str(value)


def sort_config_keys(
    keys: list[tuple[str, str, str]],
    records: list[RunRecord],
    stems: list[str],
    mode: str,
) -> list[tuple[str, str, str]]:
    if mode == "solver":
        return sorted(keys, key=lambda k: (solver_display_name(k[0]), k[1], k[2]))

    stats_by_key = {k: aggregate(records, k, stems) for k in keys}

    if mode == "solved":
        return sorted(
            keys,
            key=lambda k: (
                -stats_by_key[k].solved,
                stats_by_key[k].avg_time_sec if stats_by_key[k].avg_time_sec is not None else float("inf"),
                solver_display_name(k[0]),
                k[1],
                k[2],
            ),
        )

    if mode == "time":
        return sorted(
            keys,
            key=lambda k: (
                stats_by_key[k].avg_time_sec if stats_by_key[k].avg_time_sec is not None else float("inf"),
                solver_display_name(k[0]),
                k[1],
                k[2],
            ),
        )

    raise ValueError(f"unknown sort mode: {mode}")


def render_latex_table(
    stems: list[str],
    records: list[RunRecord],
    *,
    sort: str = "solver",
) -> str:
    keys = sort_config_keys(unique_config_keys(records), records, stems, sort)

    lines = [
        r"\begin{table*}[t]",
        r"\centering",
        r"\caption{Aggregate solver performance across QLDPC benchmark instances.}",
        r"\label{tab:overall-performance}",
        r"\begin{tabular}{l l r r r}",
        r"\hline",
        r"Solver & Strategy & Solved & Avg.\ Time (s) & Max Exact Distance \\",
        r"\hline",
    ]

    for solver_id, card, encoding in keys:
        stats = aggregate(records, (solver_id, card, encoding), stems)
        solved_cell = f"{stats.solved}/{stats.total_stems}"
        if stats.solved == 0:
            avg_cell = "--"
            max_cell = "--"
        else:
            avg_cell = _fmt_num(stats.avg_time_sec)
            max_cell = _fmt_int(stats.max_exact_distance)

        solver_name = solver_display_name(solver_id)
        enc_name = encoding_display_name(solver_id, card, encoding)
        lines.append(
            f"{solver_name} & {enc_name} & {solved_cell} & {avg_cell} & {max_cell} \\\\"
        )

    lines.extend([r"\hline", r"\end{tabular}", r"\end{table*}"])
    return "\n".join(lines) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Parse benchmark_solver_performance log and emit aggregate LaTeX table.",
    )
    parser.add_argument(
        "log_file",
        type=Path,
        help="Path to benchmark log (e.g. logs/BB_bench_0521.log)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Write LaTeX to this file (default: stdout)",
    )
    parser.add_argument(
        "--sort",
        choices=("solver", "solved", "time"),
        default="solver",
        help="Row order: by solver name (default), by solved count desc, or by avg time asc",
    )
    args = parser.parse_args(argv)

    if not args.log_file.is_file():
        print(f"error: not a file: {args.log_file}", file=sys.stderr)
        return 1

    text = args.log_file.read_text(encoding="utf-8", errors="replace")
    stems, records = parse_log(text)
    if not stems:
        print("error: no benchmark stems found in log", file=sys.stderr)
        return 1

    keys = unique_config_keys(records)
    if not keys:
        print("error: no solver result rows found in log", file=sys.stderr)
        return 1

    latex = render_latex_table(stems, records, sort=args.sort)
    if args.output:
        args.output.write_text(latex, encoding="utf-8")
    else:
        sys.stdout.write(latex)
    print(
        f"# {len(keys)} configuration(s), {len(stems)} stem(s)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
