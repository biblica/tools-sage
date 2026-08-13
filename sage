#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$ROOT_DIR/core${PYTHONPATH:+:$PYTHONPATH}"

find_python() {
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
                printf '%s\n' "$candidate"
                return 0
            fi
        fi
    done
    if command -v py >/dev/null 2>&1; then
        if py -3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
            printf '%s\n' 'py -3'
            return 0
        fi
    fi
    return 1
}

VENV_PYTHON="$ROOT_DIR/.venv/bin/python"
if [ -x "$VENV_PYTHON" ] && "$VENV_PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    BOOTSTRAP_CMD="$VENV_PYTHON"
else
    BOOTSTRAP_CMD=$(find_python) || {
        printf '%s\n' 'SAGE ERROR' 'Result: BLOCKED' '- Python 3.10 or later was not found.' >&2
        printf '%s\n' '- Install Python 3.10+; SAGE will create and manage its local .venv on the next launch.' >&2
        exit 2
    }
fi

cd "$ROOT_DIR"
if [ "$BOOTSTRAP_CMD" = 'py -3' ]; then
    py -3 "$ROOT_DIR/scripts/bootstrap_runtime.py" "$ROOT_DIR" || exit $?
else
    "$BOOTSTRAP_CMD" "$ROOT_DIR/scripts/bootstrap_runtime.py" "$ROOT_DIR" || exit $?
fi

if [ ! -x "$VENV_PYTHON" ]; then
    printf '%s\n' 'SAGE ERROR' 'Result: BLOCKED' '- Local .venv validation completed without a runnable Python interpreter.' >&2
    exit 2
fi
exec "$VENV_PYTHON" -m sage_core.cli "$@"
