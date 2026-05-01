#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

APP_MODULE="${APP_MODULE:-app.main:app}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
VENV_DIR="${VENV_DIR:-.venv}"
INSTALL_TEST_DEPS="${INSTALL_TEST_DEPS:-1}"
RELOAD="${RELOAD:-1}"

log() {
  printf '[start] %s\n' "$*"
}

die() {
  printf '[start] error: %s\n' "$*" >&2
  exit 1
}

is_false() {
  case "$1" in
    0|false|FALSE|False|no|NO|No|off|OFF|Off)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

python_satisfies_project() {
  local python_bin="$1"

  "$python_bin" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 12) else 1)
PY
}

uvicorn_args=("$APP_MODULE" "--host" "$HOST" "--port" "$PORT")
if ! is_false "$RELOAD"; then
  uvicorn_args+=("--reload")
fi

if (($# > 0)); then
  uvicorn_args+=("$@")
fi

if command -v uv >/dev/null 2>&1; then
  if [[ ! -d "$VENV_DIR" ]]; then
    log "creating virtualenv with uv using Python ${PYTHON_VERSION}"
    uv venv --python "$PYTHON_VERSION" "$VENV_DIR"
  elif [[ -x "$VENV_DIR/bin/python" ]] && ! python_satisfies_project "$VENV_DIR/bin/python"; then
    die "$VENV_DIR uses Python < 3.12. Recreate it with: rm -rf $VENV_DIR && ./start.sh"
  fi

  sync_args=()
  if ! is_false "$INSTALL_TEST_DEPS"; then
    sync_args+=("--extra" "test")
  fi

  log "syncing dependencies with uv"
  uv sync "${sync_args[@]}"

  log "starting http://${HOST}:${PORT}"
  exec uv run uvicorn "${uvicorn_args[@]}"
fi

venv_python="$VENV_DIR/bin/python"

if [[ -x "$venv_python" ]]; then
  python_satisfies_project "$venv_python" || die "$VENV_DIR uses Python < 3.12"
else
  python_bin="${PYTHON_BIN:-python3.12}"
  if ! command -v "$python_bin" >/dev/null 2>&1; then
    python_bin="${PYTHON_FALLBACK:-python3}"
  fi

  command -v "$python_bin" >/dev/null 2>&1 || die "Python 3.12+ is required, or install uv: https://docs.astral.sh/uv/"
  python_satisfies_project "$python_bin" || die "$python_bin is not Python 3.12+"

  log "creating virtualenv with $python_bin"
  "$python_bin" -m venv "$VENV_DIR"
  venv_python="$VENV_DIR/bin/python"
fi

[[ -x "$venv_python" ]] || die "virtualenv Python not found at $venv_python"

if ! "$venv_python" -m pip --version >/dev/null 2>&1; then
  log "bootstrapping pip in $VENV_DIR"
  "$venv_python" -m ensurepip --upgrade >/dev/null || die "could not bootstrap pip; install uv or recreate $VENV_DIR"
fi

log "installing dependencies with pip"
"$venv_python" -m pip install --upgrade pip
if ! is_false "$INSTALL_TEST_DEPS"; then
  "$venv_python" -m pip install -e ".[test]"
else
  "$venv_python" -m pip install -e .
fi

log "starting http://${HOST}:${PORT}"
exec "$venv_python" -m uvicorn "${uvicorn_args[@]}"
