#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
if [[ ! -f output/api_local/current.json ]]; then
  .venv/bin/python scripts/build_local_gold.py
fi
export GOLD_MANIFEST="$PROJECT_DIR/output/api_local/current.json"
exec .venv/bin/python -m uvicorn api.app.main:app --host 127.0.0.1 --port 8005
