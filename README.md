# QDistSAT

Benchmark **SAT and MaxSAT solvers** on **minimum-distance** search for **CSS / QLDPC** codes,
using parity-check matrices `Hx`, `Hz` and logical bases `Gx`, `Gz`.

Matrix file layout and attribution: see [NOTICE](NOTICE).

**License:** GPL-3.0-or-later ([LICENSE](LICENSE)).

## Quick start

Clone with **HTTPS** or **SSH** (pick one):

```bash
# HTTPS — works everywhere; GitHub may prompt for a personal access token
git clone https://github.com/guluchen/QDistSAT.git

# SSH — if you use GitHub SSH keys (no username/password prompt)
git clone git@github.com:guluchen/QDistSAT.git
```

### Linux (Debian / Ubuntu)

Minimal Python on Debian often lacks `venv` and blocks system-wide `pip` (PEP 668). Install once:

```bash
sudo apt install -y python3-venv python3-pip git make g++ zlib1g-dev libgmp-dev
# if `python3 -m venv` still fails, match your version, e.g.:
# sudo apt install -y python3.12-venv
```

### Install and run

```bash
cd QDistSAT

# if a previous `venv` creation failed, remove it first:
# rm -rf venv

python3 -m venv venv
source venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e ".[dev]"

# optional solvers: SMT (z3py, cvc5) + MaxSAT binaries + DistQLDPC
python3 scripts/install_benchmark_deps.py
python3 scripts/install_benchmark_deps.py --list   # distqldpc / maxcdcl should be OK
# ./bin/distqldpc data/matrices/BB_108_8_10   # smoke test

# logical bases (if Gx/Gz missing; requires pip install above)
precompute-logicals BB_108_8_10

# benchmark (rc2-* needs no download; maxcdcl / distqldpc from --bench above; skip evalmaxsat — slow)
python3 benchmarks/benchmark_solver_performance.py --stem BB_108_8_10 -d 10 \
  --solvers rc2-glucose42 maxcdcl distqldpc
# distqldpc: two runs per stem (-no-card, -card-mto); parses c d_lb / c d_ub (needs Gx/Gz)
```

Use `python3` (not bare `python`) on Debian unless you installed `python-is-python3`. Inside an active venv, `python` also works after `pip install` succeeds.

On macOS, MSE `linux_elf` solvers (e.g. `maxcdcl`) are skipped; use Linux or [Dockerfile.bench](Dockerfile.bench).

## Benchmark dependencies (optional)

**PySAT** SAT/RC2 solvers work after `pip install -e ".[dev]"` only. For the **full default benchmark** (including `z3py`, `cvc5`, external MaxSAT, and [DistQLDPC](https://github.com/guluchen/DistQLDPC)):

```bash
python3 scripts/install_benchmark_deps.py
python3 scripts/install_benchmark_deps.py --list
```

This installs:

| Component | How |
|-----------|-----|
| `z3py`, `cvc5` | `pip install cvc5 z3-solver` (via `install_benchmark_deps.py`; `z3-solver` needs a wheel for your Python version) |
| `maxcdcl`, `evalmaxsat`, `cashw-*`, … | MSE zip download (Linux x86_64 only) |
| `open-wbo` | compiled locally (`libgmp-dev` / `brew install gmp`) |
| `distqldpc` | clone + `make` → `bin/distqldpc` (`no-card`, `card-mto`) |

On **macOS**, MSE `linux_elf` binaries install but are **skipped at run time**; `open-wbo` and DistQLDPC still work. System packages (Debian): `git make g++ zlib1g-dev libgmp-dev` — the download script can install GMP/zlib via apt/brew when missing.

Fine-grained installs:

| You want | Command |
|----------|---------|
| Everything (recommended) | `python3 scripts/install_benchmark_deps.py` |
| SMT only | `pip install -e ".[benchmark]"` or `pip install z3-solver cvc5` |
| MaxSAT + DistQLDPC only | `python3 scripts/download_maxsat_solvers.py --bench` |
| One MaxSAT solver | `python3 scripts/download_maxsat_solvers.py --only maxcdcl` |
| DistQLDPC only | `python3 scripts/install_distqldpc.py` |
| codeDistance comparison | `pip install -e ".[comparison]"` or `python3 scripts/install_benchmark_deps.py --with-comparison` |
| dist-m4ri (cd-m4ri-cc) | `python3 scripts/install_dist_m4ri.py` |

### codeDistance comparison (optional)

For benchmarking against [codeDistancePYPI](https://github.com/m-webster/codeDistancePYPI) methods **GurobiDist**, **MIPDist** (SCIP), **dist_m4ri_CC**, and **magmaMinWord** (Z-distance via `CSScodeDistance`):

```bash
pip install -e ".[comparison]"
# or: python3 scripts/install_benchmark_deps.py --with-comparison
python3 benchmarks/benchmark_solver_performance.py --list-solvers   # cd-* entries

python3 benchmarks/benchmark_solver_performance.py --stem BB_72_12_6 -d 6 \
  --solvers rc2-glucose42 codedistance
# or pick one: --solvers cd-gurobi cd-mip-scip cd-m4ri-cc cd-magma
```

The pip extra installs `codedistance` and `ortools` (MIPDist/SCIP). **GurobiDist** still needs a Gurobi license; **dist_m4ri_CC** is not a pip package — build the [dist-m4ri](https://github.com/QEC-pages/dist-m4ri/) binary with `python3 scripts/install_dist_m4ri.py` (needs `libm4ri-dev` / `brew install m4ri`); **magmaMinWord** needs Magma on `PATH`. These backends are not in the default `--solvers` list.

```bash
python3 scripts/install_dist_m4ri.py          # → bin/dist_m4ri
python3 scripts/install_dist_m4ri.py --status
```

Details: [bin/maxsat/README.md](bin/maxsat/README.md).

## Input data

`data/matrices/{STEM}_Hx.txt`, `_Hz.txt`, `_Gx.txt`, `_Gz.txt` — see [data/README.md](data/README.md) and [NOTICE](NOTICE).

## Main commands

| Command | Purpose |
|---------|---------|
| `precompute-logicals STEM` | Write `Gx` / `Gz` from `Hx` / `Hz` |
| `python3 benchmarks/benchmark_solver_performance.py …` | Multi-solver distance benchmark |
| `python3 scripts/install_benchmark_deps.py` | Install SMT pip extras + MaxSAT + DistQLDPC |
| `python3 scripts/download_maxsat_solvers.py --bench` | MaxSAT + DistQLDPC only |
| `./scripts/run_benchmark_stems_dir.sh data/matrices` | Batch runs + log |

```bash
python3 benchmarks/benchmark_solver_performance.py --list-solvers
python3 scripts/parse_benchmark_log_to_latex.py logs/your_run.log
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
├── scripts/                   # install_benchmark_deps, MaxSAT download, LaTeX
├── tests/
├── bin/maxsat/                # manifest + README (binaries gitignored)
├── LICENSE                    # GPL-3.0-or-later
├── NOTICE                     # Matrix + third-party attribution
└── docs/REPO_SCOPE.md
```

## Development

```bash
source venv/bin/activate   # after python3 -m venv venv
python3 -m pip install -e ".[dev]"
python3 -m pytest tests/ -q
```

See [docs/PUBLISHING.md](docs/PUBLISHING.md) and [docs/REPO_SCOPE.md](docs/REPO_SCOPE.md).
