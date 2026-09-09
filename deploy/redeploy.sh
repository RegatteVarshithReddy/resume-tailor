#!/usr/bin/env bash
# Push new app code into an already-provisioned container and restart the service.
# Run on the Proxmox host. Does NOT touch the profile, data, or outputs in RESUME_TAILOR_HOME.
#
#   CTID=210 ./redeploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."
: "${CTID:?set CTID}"

APP_TARBALL="dist/resume-tailor-app.tar.gz"
INCLUDE_PROFILE="${INCLUDE_PROFILE:-0}" bash deploy/package-app.sh

echo ">> pushing to CT $CTID"
pct push "$CTID" "$APP_TARBALL" /root/resume-tailor-app.tar.gz

pct exec "$CTID" -- bash -c '
set -e
APP_DIR=/opt/resume-tailor/app
VENV=/opt/resume-tailor/venv
systemctl stop resume-tailor
rm -rf "$APP_DIR".new && mkdir -p "$APP_DIR".new
tar xzf /root/resume-tailor-app.tar.gz -C "$APP_DIR".new
rm -rf "$APP_DIR" && mv "$APP_DIR".new "$APP_DIR"
chown -R rtailor:rtailor /opt/resume-tailor
"$VENV/bin/pip" install -e "$APP_DIR" -q
systemctl start resume-tailor
sleep 2
systemctl --no-pager --lines=8 status resume-tailor
'
echo ">> redeploy complete"
