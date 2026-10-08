#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
python3 -m unittest discover -s tests -v
for script in collector/*.sh kindle/*.sh kindle/documents/*.sh scripts/*.sh; do sh -n "$script"; done
python3 -m quota_display.collector --fixture-dir tests/fixtures --fixture-now 2026-10-07T12:00:00Z --output build/preview/quota.json
python3 scripts/render-previews.py
