#!/usr/bin/env bash
# AEGIS-LINK - macOS/Linux run script. Creates .venv on first run, then starts the server.
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements-dev.txt
fi
echo "AEGIS-LINK on http://localhost:8000  (phones: see /api/lan)"
exec .venv/bin/python -m uvicorn backend.app:app --host 0.0.0.0 --port "${AEGIS_PORT:-8000}"
