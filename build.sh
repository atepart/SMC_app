#!/usr/bin/env bash
set -euo pipefail

APP_NAME="AOCapp"

if [ -z "${PYTHON_BIN:-}" ]; then
  if [ -x ".venv/bin/python" ]; then
    PYTHON_BIN=".venv/bin/python"
  else
    PYTHON_BIN="python"
  fi
fi

"$PYTHON_BIN" -m PyInstaller aocapp/__main__.py \
  -n "$APP_NAME" \
  --onedir \
  --icon=assets/aocapp-icon.ico \
  --noconsole \
  --windowed \
  -y \
  --add-data="assets:assets"
