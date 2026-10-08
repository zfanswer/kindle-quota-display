#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
exec "${PYTHON_BIN:-python3}" -m quota_display.collector "$@"
