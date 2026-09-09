#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Runs INSIDE the Debian 12 LXC. Installs resume-tailor as a systemd service,
# joins Tailscale, and exposes the app on the tailnet via `tailscale serve`.
#
# Invoked by bootstrap-proxmox.sh, but safe to run by hand (idempotent).
#
# Env: TS_AUTHKEY (req), CLAUDE_CODE_OAUTH_TOKEN (req),
#      TS_HOSTNAME=resume-tailor, CLAUDE_MODEL=sonnet,
#      BIND_ADDR=127.0.0.1, PORT=8000
# ---------------------------------------------------------------------------
set -euo pipefail

: "${TS_AUTHKEY:?set TS_AUTHKEY}"
: "${CLAUDE_CODE_OAUTH_TOKEN:?set CLAUDE_CODE_OAUTH_TOKEN}"
TS_HOSTNAME="${TS_HOSTNAME:-resume-tailor}"
CLAUDE_MODEL="${CLAUDE_MODEL:-sonnet}"
BIND_ADDR="${BIND_ADDR:-127.0.0.1}"
PORT="${PORT:-8000}"

APP_DIR=/opt/resume-tailor/app
VENV=/opt/resume-tailor/venv
RT_HOME=/opt/resume-tailor/home
ENVFILE=/etc/resume-tailor.env
SVC_USER=rtailor
REDIR_PY=/opt/resume-tailor/redirect.py

echo ">> [1/8] apt packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
  python3 python3-venv python3-pip ca-certificates curl jq unzip \
  libreoffice-writer fonts-dejavu fonts-liberation
apt-get clean

echo ">> [2/8] tailscale"
if ! command -v tailscale >/dev/null; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi
systemctl enable --now tailscaled
# --accept-risk=lose-ssh: when deploying from a machine whose ssh to the Proxmox
# host runs over Tailscale, SSH_CONNECTION is inherited into this `pct exec` and
# `tailscale up --ssh` aborts thinking it will drop the session. It won't — this
# is a fresh CT, not the host serving that session.
tailscale up --authkey "$TS_AUTHKEY" --hostname "$TS_HOSTNAME" --ssh --accept-risk=lose-ssh
tailscale status || true

echo ">> [3/8] service user + claude CLI"
# Create the service user first: the systemd service runs as $SVC_USER, so the
# claude binary has to live somewhere that user can execute. Installing it as
# root under /root/.local is useless — $SVC_USER cannot traverse /root.
id -u "$SVC_USER" >/dev/null 2>&1 || useradd --system --create-home --home-dir /opt/resume-tailor --shell /usr/sbin/nologin "$SVC_USER"
mkdir -p /opt/resume-tailor
chown "$SVC_USER":"$SVC_USER" /opt/resume-tailor

if [ ! -x /opt/resume-tailor/.local/bin/claude ]; then
  /usr/sbin/runuser -u "$SVC_USER" -- env HOME=/opt/resume-tailor bash -c \
    'curl -fsSL https://claude.ai/install.sh | bash' || {
    echo "!! claude install failed; install it as $SVC_USER and re-run"; exit 1; }
fi
ln -sf /opt/resume-tailor/.local/bin/claude /usr/local/bin/claude
/usr/sbin/runuser -u "$SVC_USER" -- env HOME=/opt/resume-tailor /usr/local/bin/claude --version || true

echo ">> [4/8] app source"
mkdir -p "$APP_DIR" "$RT_HOME"
rm -rf "$APP_DIR".new && mkdir -p "$APP_DIR".new
tar xzf /root/resume-tailor-app.tar.gz -C "$APP_DIR".new
rm -rf "$APP_DIR" && mv "$APP_DIR".new "$APP_DIR"

echo ">> [5/8] python venv"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip -q
"$VENV/bin/pip" install -e "$APP_DIR" -q

echo ">> [6/8] RESUME_TAILOR_HOME scaffold"
mkdir -p "$RT_HOME"
if [ ! -f "$RT_HOME/profile/settings.yaml" ]; then
  ( cd "$RT_HOME" && RESUME_TAILOR_HOME="$RT_HOME" "$VENV/bin/resume-tailor" init )
fi
chown -R "$SVC_USER":"$SVC_USER" /opt/resume-tailor

cat > "$ENVFILE" <<EOF
RESUME_TAILOR_HOME=$RT_HOME
RESUME_TAILOR_MODEL=$CLAUDE_MODEL
CLAUDE_CODE_OAUTH_TOKEN=$CLAUDE_CODE_OAUTH_TOKEN
PATH=$VENV/bin:/usr/local/bin:/usr/bin:/bin
EOF
chmod 600 "$ENVFILE"

echo ">> [7/8] systemd service"
cat > /etc/systemd/system/resume-tailor.service <<EOF
[Unit]
Description=resume-tailor web app
After=network-online.target tailscaled.service
Wants=network-online.target

[Service]
Type=simple
User=$SVC_USER
EnvironmentFile=$ENVFILE
WorkingDirectory=$RT_HOME
ExecStart=$VENV/bin/resume-tailor web --host $BIND_ADDR --port $PORT
Restart=always
RestartSec=3
NoNewPrivileges=true
ProtectSystem=full
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now resume-tailor
sleep 2
systemctl --no-pager --lines=15 status resume-tailor || true

echo ">> [8/8] expose on tailnet via tailscale serve (HTTPS, tailnet-only, NOT public)"
tailscale serve --bg --https=443 "http://${BIND_ADDR}:${PORT}" || \
  tailscale serve --bg "${PORT}" || \
  echo "!! 'tailscale serve' failed — enable HTTPS certs in the tailnet admin console, then: tailscale serve --bg --https=443 http://${BIND_ADDR}:${PORT}"

# port 80 -> 443 redirect: tailscale serve can't redirect, so a tiny 301
# responder sits on 127.0.0.1:8081 and serve --http=80 proxies to it.
# redirect.py normally uses the request's Host header; REDIRECT_HOST is only the
# fallback for a Host-less request. Derive this CT's MagicDNS name for it.
REDIRECT_HOST="$(tailscale status --json 2>/dev/null \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' 2>/dev/null || true)"
install -m 644 -o "$SVC_USER" -g "$SVC_USER" "$APP_DIR/deploy/redirect.py" "$REDIR_PY"
cat > /etc/systemd/system/resume-tailor-redirect.service <<EOF
[Unit]
Description=resume-tailor HTTP->HTTPS redirect (port 80 via tailscale serve)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SVC_USER
Environment=REDIRECT_HOST=${REDIRECT_HOST:-resume-tailor.example.ts.net}
ExecStart=/usr/bin/python3 $REDIR_PY
Restart=always
RestartSec=3
NoNewPrivileges=true
ProtectSystem=full
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now resume-tailor-redirect
tailscale serve --bg --http=80 http://127.0.0.1:8081 || \
  echo "!! serve --http=80 failed; https still works, only the port-80 redirect is missing"
tailscale serve status || true

echo
echo ">> done. curl check:"
curl -fsS "http://${BIND_ADDR}:${PORT}/healthz" && echo " OK"
echo ">> URL: https://${TS_HOSTNAME}.<your-tailnet>.ts.net/"
