#!/bin/sh
set -eu
SAGE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$SAGE_ROOT/system/bin/sage" "$@"
