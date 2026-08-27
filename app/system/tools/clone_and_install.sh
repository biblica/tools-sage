#!/bin/sh
set -eu

TOOLS_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
APP_ROOT=$(CDPATH= cd -- "$TOOLS_DIR/../.." && pwd)
exec "$APP_ROOT/sage-python" "$TOOLS_DIR/clone_and_install.py" "$@"
