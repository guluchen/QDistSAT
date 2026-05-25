# MaxSAT solver binaries

External MaxSAT executables used by `qecc_sat` (optional; PySAT `rc2-*` solvers need no download).

## Install (from repo root)

**Recommended** — README benchmark defaults on Linux x86_64 (`maxcdcl`, `evalmaxsat`, `open-wbo`):

```bash
# Debian/Ubuntu: sudo apt install -y git make libgmp-dev
python3 scripts/download_maxsat_solvers.py --bench
python3 scripts/download_maxsat_solvers.py --list
```

| Goal | Command |
|------|---------|
| Benchmark defaults (`maxcdcl`, `evalmaxsat`, `open-wbo`) | `--bench` |
| Every MSE zip in `manifest.json` | no flags |
| Pick solvers | `--only maxcdcl evalmaxsat` |
| Build only Open-WBO | `--build open-wbo` |

Re-run `--bench` safely: already-installed runnable binaries are skipped unless you pass `--force`.

## Layout

```
bin/maxsat/
  manifest.json
  maxcdcl/MaxCDCL/bin/maxcdcl_static   # from --bench
  evalmaxsat/EvalMaxSAT/bin/EvalMaxSAT
  open-wbo/open-wbo                  # from --bench (compiled)
```

Override root: `export QEECC_SAT_MAXSAT_DIR=/path/to/maxsat`

MSE zips are **Linux x86-64 ELF**. On macOS they install but benchmarks skip them; use Linux or [Dockerfile.bench](../../Dockerfile.bench).

## Benchmark

```bash
python3 benchmarks/benchmark_solver_performance.py --list-solvers
python3 benchmarks/benchmark_solver_performance.py --stem BB_108_8_10 -d 10 \
  --solvers rc2-glucose42 maxcdcl evalmaxsat
```
