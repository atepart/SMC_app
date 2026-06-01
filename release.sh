#!/usr/bin/env bash
set -euo pipefail

Tag=""

while getopts "t:" arg; do
  case "$arg" in
    t) Tag="$OPTARG" ;;
  esac
done

if [ -z "$Tag" ]; then
  echo "Usage: ./release.sh -t <tag>"
  exit 1
fi

cat > aocapp/application/version.py <<EOF
"""Application version metadata."""

__all__ = ["__version__", "REPO_SLUG"]

__version__ = "$Tag"
REPO_SLUG = "atepart/SMC_app"
EOF

git add aocapp/application/version.py
git commit -m "Release $Tag"
git tag -a "$Tag" -m "Version $Tag"

git push origin --tags
git push
