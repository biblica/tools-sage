#!/bin/sh
set -eu

TOOLS_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

find_python() {
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
                printf '%s\n' "$candidate"
                return 0
            fi
        fi
    done
    return 1
}

while ! PYTHON=$(find_python); do
    printf '%s\n' \
        'ERROR: Python 3.10 or later was not found.' \
        'ACTION REQUIRED: Install System Python 3.10 or later and add it to PATH.' \
        'SAGE will create its managed runtime in SAGEdata/.system/runtime/venv after System Python is available.' >&2
    if [ ! -t 0 ]; then
        printf '%s\n' 'Re-run this installer after System Python has been added to PATH.' >&2
        exit 1
    fi
    printf '%s' 'After adding System Python, press Enter to retry or type Q to quit: ' >&2
    if ! IFS= read -r python_action; then
        exit 1
    fi
    case "$python_action" in
        [Qq]) exit 1 ;;
    esac
done

exec "$PYTHON" "$TOOLS_DIR/clone_and_install.py" "$@"
