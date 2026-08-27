#!/bin/sh
set -eu
BUNDLE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
APP_ROOT="$BUNDLE_ROOT/app"
exec "$APP_ROOT/system/bin/sage" "$@"
