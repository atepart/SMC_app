#!/usr/bin/env bash
set -euo pipefail

APP_NAME="SMC_app"

if [ -z "${PYTHON_BIN:-}" ]; then
  if [ -x ".venv/bin/python" ]; then
    PYTHON_BIN=".venv/bin/python"
  else
    PYTHON_BIN="python"
  fi
fi

echo "Building updater..."
"$PYTHON_BIN" -m PyInstaller updater.py \
  -n "updater" \
  --onefile \
  --windowed \
  --noconsole \
  -y

echo "Building main app..."
"$PYTHON_BIN" -m PyInstaller aocapp/__main__.py \
  -n "$APP_NAME" \
  --onedir \
  --icon=assets/aocapp-icon.ico \
  --noconsole \
  --windowed \
  -y \
  --add-data="assets:assets"

echo "Bundling updater into main app..."
if [ -d "dist/${APP_NAME}.app" ]; then
    # macOS bundle
    cp dist/updater.app/Contents/MacOS/updater "dist/${APP_NAME}.app/Contents/MacOS/updater" || cp dist/updater "dist/${APP_NAME}.app/Contents/MacOS/updater"
else
    # Windows/Linux onedir
    cp dist/updater "dist/${APP_NAME}/updater" || cp dist/updater.exe "dist/${APP_NAME}/updater.exe" || true
fi

echo "Build complete."
