#!/bin/sh
set -eu
HS_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python3 -m venv "$HS_DIR/.venv"
"$HS_DIR/.venv/bin/python" -m pip install -r "$HS_DIR/requirements.txt"
echo "Ready. Run: $HS_DIR/hs status"
