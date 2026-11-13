#!/bin/sh
set -eu
HS_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ ! -x "$HS_DIR/.venv/bin/python" ]; then
    echo "Run $HS_DIR/setup.sh first." >&2
    exit 1
fi
exec "$HS_DIR/.venv/bin/python" "$HS_DIR/heater_shaker.py" "$@"
