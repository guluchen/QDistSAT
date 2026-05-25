# Shared by run_benchmark_*.sh — resolve venv Python and verify deps.
# shellcheck shell=bash

# Pick interpreter: $PYTHON > $VIRTUAL_ENV > repo venv/ or .venv/ > python3
resolve_benchmark_python() {
  local repo_root="$1"
  if [[ -n "${PYTHON:-}" ]]; then
    if [[ ! -x "${PYTHON}" ]]; then
      echo "Error: PYTHON is not executable: ${PYTHON}" >&2
      return 1
    fi
    return 0
  fi
  if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
    PYTHON="${VIRTUAL_ENV}/bin/python"
    return 0
  fi
  local cand
  for cand in "${repo_root}/.venv/bin/python" "${repo_root}/venv/bin/python"; do
    if [[ -x "${cand}" ]]; then
      PYTHON="${cand}"
      return 0
    fi
  done
  PYTHON="python3"
  return 0
}

# Print "idle<TAB>total<TAB>note" using the benchmark driver's idle sampler.
bench_estimate_idle_cpus() {
  local repo_root="$1"
  (cd "${repo_root}" && "${PYTHON}" benchmarks/benchmark_solver_performance.py --print-idle-cores)
}

require_benchmark_python_deps() {
  local repo_root="$1"
  if ! "${PYTHON}" -c "from pysat.card import EncType; import qecc_sat" 2>/dev/null; then
    echo "Error: benchmark dependencies missing for: ${PYTHON}" >&2
    echo "" >&2
    echo "  cd ${repo_root}" >&2
    echo "  python3 -m venv venv" >&2
    echo "  source venv/bin/activate" >&2
    echo "  python3 -m pip install -e \".[dev]\"" >&2
    echo "  python3 scripts/install_benchmark_deps.py   # optional: MaxSAT, codedistance, …" >&2
    echo "  ./scripts/run_benchmark_six_stemdirs.sh" >&2
    echo "" >&2
    echo "Or: export PYTHON=/path/to/venv/bin/python" >&2
    return 1
  fi
  return 0
}
