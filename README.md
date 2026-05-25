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
sudo apt install -y python3-venv python3-pip git make libgmp-dev
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

# optional: external MaxSAT on Linux x86_64 (see below)
python3 scripts/download_maxsat_solvers.py --bench

# logical bases (if Gx/Gz missing; requires pip install above)
precompute-logicals BB_108_8_10

# benchmark (rc2-* needs no download; maxcdcl from --bench above)
python3 benchmarks/benchmark_solver_performance.py --stem BB_108_8_10 -d 10 \
  --solvers rc2-glucose42 maxcdcl evalmaxsat
```

Use `python3` (not bare `python`) on Debian unless you installed `python-is-python3`. Inside an active venv, `python` also works after `pip install` succeeds.

On macOS, MSE `linux_elf` solvers (e.g. `maxcdcl`) are skipped; use Linux or [Dockerfile.bench](Dockerfile.bench).

## External MaxSAT solvers (optional)

Only needed if you pass external names to `--solvers` (e.g. `maxcdcl`, `evalmaxsat`). **PySAT backends** (`rc2-glucose42`, `rc2-g3`, …) work after `pip install` alone.

**Linux x86_64** — `--bench` downloads all MSE zip solvers (`cashw-coreplus`, `maxcdcl`, …) and builds Open-WBO. If GMP is missing, the script tries `sudo apt install -y libgmp-dev` (Debian/Ubuntu) automatically:

```bash
python3 scripts/download_maxsat_solvers.py --bench
python3 scripts/download_maxsat_solvers.py --list   # optional: verify status (OK = ready)
```

Use `--no-install-deps` to skip auto apt/brew. On macOS, `--bench` may run `brew install gmp` (MSE zips still need Linux to run).

| You want | Command |
|----------|---------|
| All external binaries (MSE zips + `open-wbo`) | `--bench` |
| MSE zips only (no Open-WBO build) | `python3 scripts/download_maxsat_solvers.py` (no flags) |
| One solver | `--only maxcdcl` |
| Build only Open-WBO | `--build open-wbo` |

Details: [bin/maxsat/README.md](bin/maxsat/README.md).

## Input data

`data/matrices/{STEM}_Hx.txt`, `_Hz.txt`, `_Gx.txt`, `_Gz.txt` — see [data/README.md](data/README.md) and [NOTICE](NOTICE).

## Main commands

| Command | Purpose |
|---------|---------|
| `precompute-logicals STEM` | Write `Gx` / `Gz` from `Hx` / `Hz` |
| `python3 benchmarks/benchmark_solver_performance.py …` | Multi-solver distance benchmark |
| `python3 scripts/download_maxsat_solvers.py --bench` | Install default external MaxSAT binaries |
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
├── scripts/                   # MaxSAT download, LaTeX, batch shell
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
