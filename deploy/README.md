# deploy/ — one self-host example

**Not required.** For most people `pip install` + `resume-tailor web`, or
`docker compose up` (repo root), is enough.

This directory is how the author self-hosts: a Debian LXC on a Proxmox host,
reachable **only on a Tailscale tailnet**, HTTPS via `tailscale serve`, run as a
systemd service, with a headless `claude setup-token` so the Claude Code
subscription is used and there's no API bill.

| file | role |
|---|---|
| `DEPLOY.md` | the full runbook (read this first) |
| `package-app.sh` | bundle the app into `dist/resume-tailor-app.tar.gz` (run on your workstation) |
| `bootstrap-proxmox.sh` | create the LXC (run on the Proxmox host) |
| `install-in-container.sh` | venv + systemd + Tailscale + token, inside the container |
| `redeploy.sh` | push a code update without touching `profile/`, `data/`, `outputs/` |
| `redirect.py` | tiny stdlib HTTP→HTTPS 301 responder behind `tailscale serve --http=80` |

Substitute your own Proxmox host, tailnet name, and container ID throughout —
`pve1`/`pve2` and `CTID=210` are placeholders. This path is not covered by CI.
