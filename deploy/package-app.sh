#!/usr/bin/env bash
# Package the app source into dist/resume-tailor-app.tar.gz for deployment.
# Run this on your workstation (the machine with the code).
set -euo pipefail
cd "$(dirname "$0")/.."

OUT="dist/resume-tailor-app.tar.gz"
mkdir -p dist

INCLUDE_PROFILE="${INCLUDE_PROFILE:-0}"
EXCLUDES=(
  --exclude=".git" --exclude=".venv" --exclude="dist"
  --exclude="__pycache__" --exclude="*.pyc"
  --exclude="./outputs" --exclude="./data"
  --exclude="*.bak" --exclude="*.migrated"
  --exclude="src/resume_tailor.egg-info"
)
# NB: outputs/ and data/ excludes are anchored with ./ on purpose — an
# unanchored --exclude=data also matches src/resume_tailor/data/, which holds
# the packaged init templates and must ship.
if [ "$INCLUDE_PROFILE" != "1" ]; then
  EXCLUDES+=(--exclude="profile")
  echo ">> profile/ EXCLUDED (set INCLUDE_PROFILE=1 to bundle your master profiles)"
else
  echo ">> profile/ INCLUDED"
fi

tar czf "$OUT" "${EXCLUDES[@]}" \
  pyproject.toml README.md USAGE.md LICENSE setup.sh src deploy

echo ">> wrote $OUT ($(du -h "$OUT" | cut -f1))"
echo ">> next: scp it to your Proxmox host, e.g."
echo "     scp $OUT deploy/bootstrap-proxmox.sh deploy/install-in-container.sh root@YOUR_PROXMOX_HOST:/root/"
