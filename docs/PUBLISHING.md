# Publishing to GitHub

Checklist before the first public push.

## 1. Repository hygiene

The following are **gitignored** and should stay local (or be regenerated):

| Path | Notes |
|------|--------|
| `venv/`, `.venv/` | Recreate with `python -m venv venv && pip install -e ".[dev]"` |
| `bin/maxsat/*` (except `manifest.json`, `README.md`) | Run `python3 scripts/download_maxsat_solvers.py --bench` on Linux x86_64 |
| `logs/*.log` | Benchmark output |
| `*.zip`, `*.prof` at repo root | Old exports / profiling |
| Experimental scripts | Full list: [REPO_SCOPE.md](REPO_SCOPE.md) (`tools/`, extra `benchmarks/*.py`, `packages/`, `local/`, …) |

After `git add -A`, run `git status` and confirm nothing from [REPO_SCOPE.md](REPO_SCOPE.md) appears under “Changes to be committed”.

Safe to **delete locally** if you want a smaller working tree (not needed for git):

```bash
rm -f bb.prof bb_profile.svg result.log benchmark.zip "benchmark 2.zip" cwc_benchmark.zip
rm -rf build/ dist/ __pycache__/ distance_check_sat.egg-info/ bb33/
rm -f benchmarks/benchmark.zip
```

## 2. Initialize git (if not already)

```bash
cd /path/to/QDistSAT
git init
git add -A
git status   # confirm no venv/, bin/maxsat binaries, logs, or REPO_SCOPE paths
git commit -m "Initial public release of QDistSAT"
```

## 3. Create GitHub repo

1. Create an empty repository on GitHub (no README/license if you already have them here).
2. Add remote and push:

```bash
git remote add origin git@github.com:guluchen/QDistSAT.git
git branch -M main
git push -u origin main
```

## 4. Optional: Linux benchmarks via Docker

MSE MaxSAT binaries are Linux ELF. On macOS, use the bench image:

```bash
docker build -f Dockerfile.bench -t qdistsat-bench .
# Mount repo and run benchmarks inside the container (see bin/maxsat/README.md)
```

## 5. CI

GitHub Actions runs `pytest` on push/PR (`.github/workflows/ci.yml`). No MaxSAT zip download in CI—unit tests only.

## 6. License and attribution

- **QDistSAT** code: GPL-3.0-or-later ([LICENSE](LICENSE), [NOTICE](NOTICE)).
- **Benchmark matrices:** same attribution as [DistQLDPC](https://github.com/guluchen/DistQLDPC) / codeDistancePYPI (see NOTICE).
- **MaxSAT binaries:** upstream licenses after `download_maxsat_solvers.py`.

Update `pyproject.toml` `[project.urls]` when the GitHub remote is known.
