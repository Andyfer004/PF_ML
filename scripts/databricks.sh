#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI_PATH="$PROJECT_DIR/.cache/databricks/bin/databricks"

if [[ ! -x "$CLI_PATH" ]]; then
  CLI_PATH="$(command -v databricks || true)"
  if [[ -z "$CLI_PATH" ]]; then
    echo "Instala Databricks CLI y configura el perfil PF-ML como indica README.md." >&2
    exit 1
  fi
fi

exec "$CLI_PATH" "$@" --profile PF-ML
