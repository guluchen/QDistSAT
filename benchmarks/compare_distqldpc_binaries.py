#!/usr/bin/env python3
"""Compare two DistQLDPC binaries on QDistSAT matrix instances.

This harness is intentionally stdlib-only so downstream repositories can clone
QDistSAT and use it without installing the full SAT/MaxSAT benchmark stack.

It checks scientific result consistency and reports timing as a noisy CI signal.
Timing differences never fail the run. Result mismatches do.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

RE_LB = re.compile(r"^c\s+d_lb:\s*(\d+)\s*$", re.MULTILINE)
RE_UB = re.compile(r"^c\s+d_ub:\s*(\d+)\s*$", re.MULTILINE)
RE_D = re.compile(r"^c\s+d\s*:\s*(\d+)\s*$", re.MULTILINE)
RE_O = re.compile(r"^o\s+(-?\d+)\s*$", re.MULTILINE)
CONFIGS = (("no-card", "-no-card"), ("card-mto", "-card-mto"))


@dataclass
class Run:
    binary: str
    stem: str
    config: str
    elapsed_sec: float
    returncode: int
    timed_out: bool
    d_lb: int | None
    d_ub: int | None
    d: int | None
    objective: int | None

    @property
    def semantic_result(self) -> tuple[int | None, int | None, int | None, int | None]:
        return (self.d, self.objective, self.d_lb, self.d_ub)


def _last_int(regex: re.Pattern[str], text: str) -> int | None:
    matches = regex.findall(text)
    return int(matches[-1]) if matches else None


def run_one(binary: Path, prefix: Path, stem: str, config: str, flag: str, timeout: float) -> Run:
    cmd = [str(binary), f"-cpu-lim={max(1, int(timeout))}", flag, str(prefix)]
    t0 = time.perf_counter()
    timed_out = False
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout + 15, check=False)
        stdout = proc.stdout or ""
        rc = int(proc.returncode)
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        rc = -1
    elapsed = time.perf_counter() - t0
    return Run(
        binary=str(binary),
        stem=stem,
        config=config,
        elapsed_sec=elapsed,
        returncode=rc,
        timed_out=timed_out,
        d_lb=_last_int(RE_LB, stdout),
        d_ub=_last_int(RE_UB, stdout),
        d=_last_int(RE_D, stdout),
        objective=_last_int(RE_O, stdout),
    )


def matrix_prefix(data_root: Path, stem: str) -> Path:
    matches = list(data_root.glob(f"*/{stem}_Hx.txt"))
    if len(matches) != 1:
        raise SystemExit(f"Expected exactly one Hx file for {stem} under {data_root}, found {len(matches)}")
    prefix = matches[0].with_name(stem)
    for suffix in ("_Hx.txt", "_Hz.txt", "_Gx.txt", "_Gz.txt"):
        path = prefix.with_name(stem + suffix)
        if not path.is_file():
            raise SystemExit(f"Missing benchmark matrix: {path}")
    return prefix


def result_label(r: Run) -> str:
    if r.d is not None:
        return f"d={r.d}"
    if r.objective is not None and r.objective >= 0:
        return f"o={r.objective}"
    if r.d_lb is not None and r.d_ub is not None:
        return f"[{r.d_lb},{r.d_ub}]"
    if r.d_lb is not None:
        return f">={r.d_lb}"
    if r.d_ub is not None:
        return f"<={r.d_ub}"
    return "no-result"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--baseline-bin", required=True, type=Path)
    p.add_argument("--candidate-bin", required=True, type=Path)
    p.add_argument("--data-root", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    p.add_argument("--stems", nargs="+", default=["LP_136_32_4"])
    p.add_argument("--timeout", type=float, default=45.0)
    p.add_argument("--json-out", type=Path)
    p.add_argument("--markdown-out", type=Path)
    args = p.parse_args()

    for binary in (args.baseline_bin, args.candidate_bin):
        if not binary.is_file():
            raise SystemExit(f"Binary not found: {binary}")

    rows: list[dict] = []
    mismatch = False
    for stem in args.stems:
        prefix = matrix_prefix(args.data_root, stem)
        for config, flag in CONFIGS:
            base = run_one(args.baseline_bin, prefix, stem, config, flag, args.timeout)
            cand = run_one(args.candidate_bin, prefix, stem, config, flag, args.timeout)
            same = base.semantic_result == cand.semantic_result and base.returncode == cand.returncode
            if not same:
                mismatch = True
            speed = None
            if base.elapsed_sec > 0:
                speed = cand.elapsed_sec / base.elapsed_sec
            rows.append({
                "stem": stem,
                "config": config,
                "same_semantics": same,
                "baseline": asdict(base),
                "candidate": asdict(cand),
                "candidate_over_baseline_time": speed,
            })

    report = {
        "scientific_semantics_match": not mismatch,
        "timing_is_ci_signal_only": True,
        "rows": rows,
    }

    md = [
        "# DistQLDPC cross-repo benchmark",
        "",
        f"Scientific results match: **{'YES' if not mismatch else 'NO'}**",
        "",
        "Timing is informational only; shared CI runners are noisy.",
        "",
        "| Stem | Config | Baseline | Candidate | Cand/Base time | Semantic match |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in rows:
        b = Run(**row["baseline"])
        c = Run(**row["candidate"])
        ratio = row["candidate_over_baseline_time"]
        ratio_s = f"{ratio:.2f}x" if ratio is not None else "n/a"
        md.append(
            f"| {row['stem']} | {row['config']} | {result_label(b)} ({b.elapsed_sec:.2f}s) | "
            f"{result_label(c)} ({c.elapsed_sec:.2f}s) | {ratio_s} | "
            f"{'YES' if row['same_semantics'] else 'NO'} |"
        )
    md_text = "\n".join(md) + "\n"

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(md_text, encoding="utf-8")
    print(md_text, end="")
    return 2 if mismatch else 0


if __name__ == "__main__":
    raise SystemExit(main())
