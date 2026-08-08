#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$ROOT_DIR/.venv"

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install -r "$ROOT_DIR/requirements.txt"

if ! command -v exiftool >/dev/null 2>&1; then
  echo
  echo "Aviso: exiftool no esta instalado o no esta en PATH."
  echo "Instalacion sugerida:"
  echo "- macOS: brew install exiftool"
  echo "- Ubuntu/Debian: sudo apt install libimage-exiftool-perl"
  echo "- Windows: instala ExifTool y agrega su carpeta al PATH"
fi

echo
echo "Entorno listo."
echo "Activalo con:"
echo "source \"$VENV_DIR/bin/activate\""
