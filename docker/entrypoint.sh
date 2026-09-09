#!/bin/sh
# Scaffold the data dir on first run, then exec the given command.
set -e
: "${RESUME_TAILOR_HOME:=/data}"
if [ ! -f "$RESUME_TAILOR_HOME/profile/settings.yaml" ]; then
  echo ">> first run — scaffolding $RESUME_TAILOR_HOME"
  mkdir -p "$RESUME_TAILOR_HOME"
  resume-tailor init || true
fi
exec "$@"
