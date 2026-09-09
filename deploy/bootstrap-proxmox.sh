#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Create a Debian 12 LXC on this Proxmox node and install resume-tailor into
# it as a systemd service, joined to your tailnet.
#
# RUN THIS ON THE PROXMOX HOST (pve1 / pve2) as root.
#
# Prereqs, already copied to /root/ on this host:
#   - resume-tailor-app.tar.gz   (from deploy/package-app.sh)
#   - install-in-container.sh    (from this repo's deploy/)
#
# Required env vars:
#   CTID=210
#   TS_AUTHKEY=tskey-auth-xxxx           # https://login.tailscale.com/admin/settings/keys
#   CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat-… # run `claude setup-token` on a logged-in machine
#
# Optional env vars (defaults shown):
#   HOSTNAME=resume-tailor   STORAGE=local-lvm   BRIDGE=vmbr0
#   DISK_GB=8   RAM_MB=1024   CORES=2   SWAP_MB=512
#   TEMPLATE=(auto-download debian-12-standard)
#   APP_TARBALL=/root/resume-tailor-app.tar.gz
#   INSTALLER=/root/install-in-container.sh
#   CLAUDE_MODEL=sonnet
#   BIND_ADDR=127.0.0.1   PORT=8000       # app listens here; exposed via `tailscale serve`
# ---------------------------------------------------------------------------
set -euo pipefail

need() { [ -n "${!1:-}" ] || { echo "!! missing required env: $1"; exit 1; }; }
need CTID
need TS_AUTHKEY
need CLAUDE_CODE_OAUTH_TOKEN

HOSTNAME="${HOSTNAME:-resume-tailor}"
STORAGE="${STORAGE:-local-lvm}"
BRIDGE="${BRIDGE:-vmbr0}"
DISK_GB="${DISK_GB:-8}"
RAM_MB="${RAM_MB:-1024}"
SWAP_MB="${SWAP_MB:-512}"
CORES="${CORES:-2}"
APP_TARBALL="${APP_TARBALL:-/root/resume-tailor-app.tar.gz}"
INSTALLER="${INSTALLER:-/root/install-in-container.sh}"
CLAUDE_MODEL="${CLAUDE_MODEL:-sonnet}"
BIND_ADDR="${BIND_ADDR:-127.0.0.1}"
PORT="${PORT:-8000}"
TMPL_STORE="${TMPL_STORE:-local}"

command -v pct >/dev/null || { echo "!! pct not found — run this on a Proxmox host"; exit 1; }
[ -f "$APP_TARBALL" ] || { echo "!! app tarball not found: $APP_TARBALL"; exit 1; }
[ -f "$INSTALLER" ]   || { echo "!! installer not found: $INSTALLER"; exit 1; }
if pct status "$CTID" >/dev/null 2>&1; then
  echo "!! CTID $CTID already exists. Pick a free id or 'pct destroy $CTID' first."; exit 1
fi

# --- template -------------------------------------------------------------
if [ -z "${TEMPLATE:-}" ]; then
  echo ">> updating template catalog"
  pveam update >/dev/null || true
  TEMPLATE_NAME="$(pveam available --section system | awk '/debian-12-standard/{print $2}' | sort | tail -1)"
  [ -n "$TEMPLATE_NAME" ] || { echo "!! could not find debian-12-standard template"; exit 1; }
  if ! pveam list "$TMPL_STORE" | grep -q "$TEMPLATE_NAME"; then
    echo ">> downloading $TEMPLATE_NAME"
    pveam download "$TMPL_STORE" "$TEMPLATE_NAME"
  fi
  TEMPLATE="${TMPL_STORE}:vztmpl/${TEMPLATE_NAME}"
fi
echo ">> template: $TEMPLATE"

# --- create ------------------------------------------------------------
echo ">> creating CT $CTID ($HOSTNAME)"
pct create "$CTID" "$TEMPLATE" \
  --hostname "$HOSTNAME" \
  --cores "$CORES" --memory "$RAM_MB" --swap "$SWAP_MB" \
  --rootfs "${STORAGE}:${DISK_GB}" \
  --unprivileged 1 --features nesting=1 \
  --net0 "name=eth0,bridge=${BRIDGE},ip=dhcp" \
  --onboot 1 --start 0

# allow /dev/net/tun so Tailscale works inside the unprivileged CT
CONF="/etc/pve/lxc/${CTID}.conf"
if ! grep -q "net/tun" "$CONF"; then
  cat >>"$CONF" <<'EOF'
lxc.cgroup2.devices.allow: c 10:200 rwm
lxc.mount.entry: /dev/net/tun dev/net/tun none bind,create=file
EOF
fi

echo ">> starting CT $CTID"
pct start "$CTID"

echo ">> waiting for network in CT"
for i in $(seq 1 30); do
  if pct exec "$CTID" -- sh -c 'command -v getent >/dev/null && getent hosts deb.debian.org >/dev/null 2>&1'; then break; fi
  sleep 2
done

# --- push + run installer -------------------------------------------------
echo ">> pushing app + installer into CT"
pct push "$CTID" "$APP_TARBALL" /root/resume-tailor-app.tar.gz
pct push "$CTID" "$INSTALLER"   /root/install-in-container.sh
pct exec "$CTID" -- chmod +x /root/install-in-container.sh

echo ">> running in-container install"
pct exec "$CTID" -- env \
  TS_AUTHKEY="$TS_AUTHKEY" \
  TS_HOSTNAME="$HOSTNAME" \
  CLAUDE_CODE_OAUTH_TOKEN="$CLAUDE_CODE_OAUTH_TOKEN" \
  CLAUDE_MODEL="$CLAUDE_MODEL" \
  BIND_ADDR="$BIND_ADDR" PORT="$PORT" \
  bash /root/install-in-container.sh

echo
echo "==========================================================="
echo " CT $CTID ($HOSTNAME) is up."
TSIP="$(pct exec "$CTID" -- tailscale ip -4 2>/dev/null | head -1 || true)"
echo " Tailscale IP : ${TSIP:-<pending>}"
echo " Access URL   : https://${HOSTNAME}.<your-tailnet>.ts.net/   (tailscale serve)"
echo
echo " Logs   : pct exec $CTID -- journalctl -u resume-tailor -f"
echo " Shell  : pct enter $CTID"
echo "==========================================================="
