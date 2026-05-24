# QDistSAT — what is published

This GitHub repository (**QDistSAT**) contains only what is needed to run
`benchmarks/benchmark_solver_performance.py` on the shared `data/matrices/` corpus,
plus `precompute-logicals` to build `Gx`/`Gz` files.

Related project: [DistQLDPC](https://github.com/guluchen/DistQLDPC) (GPL-3.0-or-later,
MaxSAT reference implementation). Matrix layout and attribution match DistQLDPC; see
[NOTICE](../NOTICE).

## Tracked in git

| Path | Role |
|------|------|
| `src/qecc_sat/` | Distance library + MaxSAT/SAT backends (excluding gitignored modules) |
| `src/qecc_sat/literature_distances.py` | Default `-d` for known BB stems |
| `src/qecc_sat/cli/precompute_logical_bases.py` | `precompute-logicals` CLI |
| `benchmarks/benchmark_solver_performance.py` | Main benchmark driver |
| `scripts/download_maxsat_solvers.py` | External MaxSAT install |
| `scripts/parse_benchmark_log_to_latex.py` | Log → LaTeX |
| `scripts/run_benchmark_stems_dir.sh` | Batch benchmark |
| `data/matrices/` | Hx/Hz/Gx/Gz matrices ([data/README.md](../data/README.md)) |
| `tests/` | Pytest (excluding gitignored tests) |
| `LICENSE`, `NOTICE`, `README.md` | GPL-3.0-or-later + attributions |

## Local-only (gitignored)

Use the **`local/`** tree for experiments ([local/README.md](../local/README.md)):

| Subfolder | Contents |
|-----------|----------|
| `local/benchmarks/` | e.g. `benchmark_card_strategies.py`, `benchmark_bb_3_3_distance.py` |
| `local/scripts/` | rsync, codetable, smoke tests |
| `local/tools/` | matrix generators |
| `local/new_benchmark/`, `local/packages/` | instance builder, wheel experiment |
| `local/examples/`, `local/archive/` | demos, zips |

Some gitignored library modules may still sit under `src/qecc_sat/` (e.g. `bb_code_capacity.py`).

## Promote a file to the public repo

1. Confirm it is required by `benchmark_solver_performance.py` or its documented workflow.
2. Remove the path from `.gitignore`.
3. Update this file and README.
