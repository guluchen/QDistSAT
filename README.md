# QDistSAT

Benchmark **SAT and MaxSAT solvers** on **minimum-distance** search for **CSS / QLDPC** codes,
using parity-check matrices `Hx`, `Hz` and logical bases `Gx`, `Gz`.

Matrix file layout and attribution: see [NOTICE](NOTICE).

**License:** GPL-3.0-or-later ([LICENSE](LICENSE)).

## Quick start

```bash
git clone https://github.com/guluchen/QDistSAT.git
cd QDistSAT
python3 -m venv venv && source venv/bin/activate
pip install -e ".[dev]"

# optional: external MaxSAT (Linux x86_64)
python scripts/download_maxsat_solvers.py --list

# logical bases (if Gx/Gz missing)
precompute-logicals BB_108_8_10

# benchmark
python benchmarks/benchmark_solver_performance.py --stem BB_108_8_10 -d 10 \
  --solvers rc2-glucose42 glucose_release maxcdcl
```

On macOS, MSE `linux_elf` solvers (e.g. `maxcdcl`) are skipped; use Linux or [Dockerfile.bench](Dockerfile.bench).

## Input data

`data/matrices/{STEM}_Hx.txt`, `_Hz.txt`, `_Gx.txt`, `_Gz.txt` — see [data/README.md](data/README.md) and [NOTICE](NOTICE).

## Main commands

| Command | Purpose |
|---------|---------|
| `precompute-logicals STEM` | Write `Gx` / `Gz` from `Hx` / `Hz` |
| `python benchmarks/benchmark_solver_performance.py …` | Multi-solver distance benchmark |
| `python scripts/download_maxsat_solvers.py` | Install MaxSAT binaries under `bin/maxsat/` |
| `./scripts/run_benchmark_stems_dir.sh data/matrices` | Batch runs + log |

```bash
python benchmarks/benchmark_solver_performance.py --list-solvers
python scripts/parse_benchmark_log_to_latex.py logs/your_run.log
```

## Repository layout

```
QDistSAT/
├── src/qecc_sat/              # Library (pip install -e .)
│   ├── sat_solver.py          # PySAT backends
│   ├── maxsat_*.py            # RC2 + external MaxSAT
│   ├── qecc_distance.py       # Distance API
│   ├── distance/              # Encodings used by the benchmark
│   ├── io.py                  # Matrix I/O
│   ├── literature_distances.py
│   └── cli/precompute_logical_bases.py
├── data/matrices/             # Benchmark matrices (see NOTICE)
├── benchmarks/
│   └── benchmark_solver_performance.py
├── scripts/                   # MaxSAT download, LaTeX, batch shell
├── tests/
├── bin/maxsat/                # manifest + README (binaries gitignored)
├── LICENSE                    # GPL-3.0-or-later
├── NOTICE                     # Matrix + third-party attribution
└── docs/REPO_SCOPE.md
```

## Development

```bash
pip install -e ".[dev]"
python -m pytest tests/ -q
```

See [docs/PUBLISHING.md](docs/PUBLISHING.md) and [docs/REPO_SCOPE.md](docs/REPO_SCOPE.md).
