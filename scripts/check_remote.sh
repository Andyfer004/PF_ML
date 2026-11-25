#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bash "$PROJECT_DIR/scripts/databricks.sh" current-user me --output json
ssh -i "$HOME/.ssh/proyecto_ed25519" -o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=yes cc3105-03@165.22.137.8 'id'
