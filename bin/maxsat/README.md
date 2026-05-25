# MaxSAT solver binaries

External MaxSAT executables used by `qecc_sat` (optional; PySAT `rc2-*` solvers need no download).

## Install (from repo root)

**Recommended** — enough for the README benchmark on Linux x86_64:

```bash
python3 scripts/download_maxsat_solvers.py --bench
python3 scripts/download_maxsat_solvers.py --list
```

| Goal | Command |
|------|---------|
| Benchmark defaults (`maxcdcl`, `evalmaxsat`) | `--bench` |
| Every MSE zip in `manifest.json` | no flags |
| Pick solvers | `--only maxcdcl evalmaxsat` |
| Open-WBO | `--build open-wbo` (`git`, `make`, `libgmp-dev` / `brew install gmp`) |

Re-run `--bench` safely: already-installed runnable binaries are skipped unless you pass `--force`.

## Layout

```
bin/maxsat/
  manifest.json
  maxcdcl/MaxCDCL/bin/maxcdcl_static   # from --bench
  evalmaxsat/EvalMaxSAT/bin/EvalMaxSAT
```

Override root: `export QEECC_SAT_MAXSAT_DIR=/path/to/maxsat`

MSE zips are **Linux x86-64 ELF**. On macOS they install but benchmarks skip them; use Linux or [Dockerfile.bench](../../Dockerfile.bench).

## Benchmark

```bash
python3 benchmarks/benchmark_solver_performance.py --list-solvers
python3 benchmarks/benchmark_solver_performance.py --stem BB_108_8_10 -d 10 \
  --solvers rc2-glucose42 maxcdcl evalmaxsat
```
