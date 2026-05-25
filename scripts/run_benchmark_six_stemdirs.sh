#!/usr/bin/env bash
# Run benchmark_solver_performance on six experiment directories in parallel.
# Each directory gets its own background process and log file.
#
# Directories (under data/ by default): BB BB2 QT QT2 LP LP2
#
# Usage:
#   ./scripts/run_benchmark_six_stemdirs.sh
#   ./scripts/run_benchmark_six_stemdirs.sh --timeout 120
#   ./scripts/run_benchmark_six_stemdirs.sh --foreground --timeout 60
#   ./scripts/run_benchmark_six_stemdirs.sh --dry-run
#
# Logs: logs/<DIR>_bench_MMDD_HHMMSS.log
# PIDs: logs/six_stemdirs_MMDD_HHMMSS.pids
#
set -euo pipefail

DEFAULT_TIMEOUT=60
STEM_DIRS=(BB BB2 QT QT2 LP LP2)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

DATA_ROOT="${REPO_ROOT}/data"
LOG_DIR="${REPO_ROOT}/logs"
TIMEOUT="${DEFAULT_TIMEOUT}"
JOBS=1
FOREGROUND=0
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: run_benchmark_six_stemdirs.sh [OPTIONS]

Run benchmarks on data/{BB,BB2,QT,QT2,LP,LP2} in parallel (six processes).
Uses default --solvers (all PySAT backends + distqldpc + codedistance).
Per-stem max distance follows literature / benchmark defaults (no -d override).

Options:
  -t, --timeout SEC   Per-config wall-clock timeout (default: 60)
  -j, --jobs N        Parallel workers inside each directory run (default: 1)
  --data-root DIR     Parent of BB, BB2, … (default: REPO/data)
  --log-dir DIR       Log output directory (default: REPO/logs)
  --foreground        Wait for all six runs to finish (default: detach)
  --dry-run           Print commands without executing
  -h, --help          Show this help

Environment:
  PYTHON              Python executable (else VIRTUAL_ENV, then venv/ or .venv/)
  DATA_ROOT, LOG_DIR  Override defaults before flags

Requires: project venv with pip install -e ".[dev]" (pysat + qecc_sat).

Examples:
  ./scripts/run_benchmark_six_stemdirs.sh
  ./scripts/run_benchmark_six_stemdirs.sh -t 300 --foreground
  tail -f logs/BB_bench_*.log
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -t|--timeout)
      TIMEOUT="$2"
      shift 2
      ;;
    -j|--jobs)
      JOBS="$2"
      shift 2
      ;;
    --data-root)
      DATA_ROOT="$2"
      shift 2
      ;;
    --log-dir)
      LOG_DIR="$2"
      shift 2
      ;;
    --foreground)
      FOREGROUND=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

[[ "${DATA_ROOT}" != /* ]] && DATA_ROOT="${REPO_ROOT}/${DATA_ROOT}"
[[ "${LOG_DIR}" != /* ]] && LOG_DIR="${REPO_ROOT}/${LOG_DIR}"

# shellcheck source=_benchmark_env.sh
source "${SCRIPT_DIR}/_benchmark_env.sh"
resolve_benchmark_python "${REPO_ROOT}"
if [[ "${DRY_RUN}" -eq 0 ]]; then
  require_benchmark_python_deps "${REPO_ROOT}"
fi

cd "${REPO_ROOT}"
mkdir -p "${LOG_DIR}"

TS="$(date +%m%d_%H%M%S)"
PID_FILE="${LOG_DIR}/six_stemdirs_${TS}.pids"

missing=()
for name in "${STEM_DIRS[@]}"; do
  dir="${DATA_ROOT}/${name}"
  if [[ ! -d "${dir}" ]]; then
    missing+=("${dir}")
  fi
done
if [[ ${#missing[@]} -gt 0 ]]; then
  echo "Error: missing stem directories:" >&2
  printf '  %s\n' "${missing[@]}" >&2
  exit 1
fi

echo "# repo=${REPO_ROOT}" >&2
echo "# python=${PYTHON}" >&2
echo "# timeout=${TIMEOUT}s per config, jobs=${JOBS} per directory" >&2
echo "# solvers=default (all tools)" >&2
echo "# pid file: ${PID_FILE}" >&2

{
  echo "# started $(date '+%Y-%m-%dT%H:%M:%S%z')"
  echo "# timeout=${TIMEOUT} jobs=${JOBS}"
} > "${PID_FILE}"

pids=()
for name in "${STEM_DIRS[@]}"; do
  stems_dir="${DATA_ROOT}/${name}"
  log_path="${LOG_DIR}/${name}_bench_${TS}.log"
  cmd=(
    "${PYTHON}" benchmarks/benchmark_solver_performance.py
    --stems-dir "${stems_dir}"
    --timeout "${TIMEOUT}"
    --no-auto-jobs
    --jobs "${JOBS}"
  )

  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo "[dry-run] ${name} -> ${log_path}"
    printf '  '; printf '%q ' "${cmd[@]}"; echo '>& "${log_path}" 2>&1 &'
    echo "${name} dry-run" >> "${PID_FILE}"
    continue
  fi

  {
    echo "# $(date '+%Y-%m-%dT%H:%M:%S%z')  $0"
    echo "# stems-dir=${stems_dir}"
    echo "# cmd: ${cmd[*]}"
  } > "${log_path}"

  "${cmd[@]}" >> "${log_path}" 2>&1 &
  pid=$!
  pids+=("${pid}")
  echo "${name} ${pid} ${log_path}" >> "${PID_FILE}"
  echo "started ${name} pid=${pid} log=${log_path}" >&2
done

if [[ "${DRY_RUN}" -eq 1 ]]; then
  exit 0
fi

if [[ "${FOREGROUND}" -eq 1 ]]; then
  fail=0
  for pid in "${pids[@]}"; do
    if ! wait "${pid}"; then
      fail=1
    fi
  done
  echo "# finished $(date '+%Y-%m-%dT%H:%M:%S%z')" >> "${PID_FILE}"
  if [[ "${fail}" -ne 0 ]]; then
    echo "One or more benchmark processes failed (see logs/)." >&2
    exit 1
  fi
  echo "All six benchmarks finished." >&2
else
  echo "Six benchmarks running in background. Monitor:" >&2
  echo "  tail -f ${LOG_DIR}/{BB,BB2,QT,QT2,LP,LP2}_bench_${TS}.log" >&2
  echo "  wait \$(awk '{print \$2}' ${PID_FILE})   # wait for all" >&2
fi
