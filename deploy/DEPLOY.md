# Deploying resume-tailor to a Proxmox LXC on your tailnet

> **This is one self-host example**, not a requirement. For most people
> `pip install resume-tailor` or `docker compose up` (see the main README) is
> enough. This runbook is here because it's how the author runs it — a Proxmox
> LXC exposed only on a Tailscale tailnet. `pve1`/`pve2` below are example
> Proxmox node names; substitute your own host, tailnet, and container ID.

End state: a Debian 12 unprivileged LXC on `pve1` (or `pve2`) running the
resume-tailor web app as a `systemd` service, reachable from any device on your
tailnet at `https://resume-tailor.<your-tailnet>.ts.net/` (via `tailscale serve`
— tailnet-only, **not** public Funnel).

```
workstation ──package-app.sh──▶ resume-tailor-app.tar.gz
      │  scp tarball + 2 scripts
      ▼
Proxmox host ──bootstrap-proxmox.sh──▶ pct create LXC ──▶ install-in-container.sh
      │                                                        ├─ apt: python, libreoffice
      │                                                        ├─ tailscale up --ssh
      │                                                        ├─ claude CLI + OAuth token
      │                                                        ├─ venv + pip install -e
      │                                                        ├─ systemd: resume-tailor.service
      │                                                        └─ tailscale serve :443 → 127.0.0.1:8000
      ▼
  tailnet ──▶ https://resume-tailor.<tailnet>.ts.net/
```

---

## 1. Prerequisites (on your workstation)

### a. A long-lived Claude token (no API billing — uses your Pro/Max plan)

On a machine where `claude` is logged in:

```bash
claude setup-token
```

Copy the token it prints (`sk-ant-oat-…`). This is `CLAUDE_CODE_OAUTH_TOKEN`.

### b. A Tailscale auth key

<https://login.tailscale.com/admin/settings/keys> → **Generate auth key**.
Reusable off, ephemeral off. Optionally tag it (e.g. `tag:server`). Copy
`tskey-auth-…` → this is `TS_AUTHKEY`.

### c. Enable HTTPS in your tailnet (one-time, for `tailscale serve`)

Tailscale admin console → **DNS** → enable **HTTPS Certificates**.

---

## 2. Package the app

```bash
cd ~/resume-tailor
bash deploy/package-app.sh
# bundles code only. To also ship your master profiles:
INCLUDE_PROFILE=1 bash deploy/package-app.sh
```

Produces `dist/resume-tailor-app.tar.gz`.

---

## 3. Copy to the Proxmox host

```bash
scp dist/resume-tailor-app.tar.gz \
    deploy/bootstrap-proxmox.sh \
    deploy/install-in-container.sh \
    root@pve1:/root/
```

(`pve1` is a stand-in for your Proxmox host — its LAN name or tailnet IP.)

---

## 4. Run the bootstrap on the Proxmox host

```bash
ssh root@pve1
cd /root

CTID=210 \
TS_AUTHKEY='tskey-auth-xxxxxxxxxxxx' \
CLAUDE_CODE_OAUTH_TOKEN='sk-ant-oat-xxxxxxxx' \
bash bootstrap-proxmox.sh
```

Common overrides:

```bash
CTID=210 HOSTNAME=resume-tailor STORAGE=local-lvm BRIDGE=vmbr0 \
DISK_GB=10 RAM_MB=1536 CORES=2 CLAUDE_MODEL=sonnet \
TS_AUTHKEY=... CLAUDE_CODE_OAUTH_TOKEN=... \
bash bootstrap-proxmox.sh
```

It creates the container, adds `/dev/net/tun` so Tailscale works in an
unprivileged CT, pushes the app in, and runs `install-in-container.sh`.

Takes ~3–6 min (apt + LibreOffice is the slow part).

---

## 5. Verify

```bash
# on the Proxmox host
pct exec 210 -- systemctl status resume-tailor
pct exec 210 -- curl -fsS http://127.0.0.1:8000/healthz
pct exec 210 -- tailscale serve status
pct exec 210 -- tailscale ip -4
```

Then from any tailnet device (laptop, iPhone, iPad):

```
https://resume-tailor.<your-tailnet>.ts.net/
```

---

## 6. Load your master profiles

The container starts with a scaffolded `default` profile. Push your real ones:

```bash
# from your workstation — copy the whole profiles tree in
tar czf - -C ~/resume-tailor/profile profiles settings.yaml | \
  ssh root@pve1 'pct exec 210 -- tar xzf - -C /opt/resume-tailor/home/profile'
pct exec 210 -- chown -R rtailor:rtailor /opt/resume-tailor/home
pct exec 210 -- systemctl restart resume-tailor
```

Or bake them in at package time with `INCLUDE_PROFILE=1` and copy them into
`/opt/resume-tailor/home/profile/` during install.

---

## 7. Updating later

```bash
# from your workstation
scp deploy/redeploy.sh root@pve1:/root/resume-tailor-redeploy.sh   # first time only
# then, from ~/resume-tailor on your workstation, or on the host:
CTID=210 bash deploy/redeploy.sh
```

`redeploy.sh` repackages, pushes, `pip install -e`, and restarts — it never
touches `profile/`, `data/` (the tracker DB), or `outputs/`.

---

## Notes & troubleshooting

| Thing | Detail |
|---|---|
| **Data location** | Everything lives in `/opt/resume-tailor/home/` — `profile/`, `data/applications.db`, `outputs/`. Back this path up. |
| **AI auth** | `CLAUDE_CODE_OAUTH_TOKEN` in `/etc/resume-tailor.env`. Regenerate with `claude setup-token`, edit the file, `systemctl restart resume-tailor`. |
| **Logs** | `pct exec 210 -- journalctl -u resume-tailor -f` |
| **PDF fidelity** | LibreOffice is installed in the container, so PDFs are converted from the DOCX (not the fpdf2 fallback). |
| **No `tailscale serve`** | If HTTPS certs aren't enabled you'll see a warning. Enable them, then `pct exec 210 -- tailscale serve --bg --https=443 http://127.0.0.1:8000`. |
| **Raw port instead of serve** | `pct exec 210 -- tailscale serve reset`, then run the service with `--host 0.0.0.0` (edit the unit) and hit `http://<ct-tailscale-ip>:8000`. Exposes on the container's LAN too. |
| **Firewall** | Nothing is published to the internet. `tailscale serve` ≠ `tailscale funnel`. |
| **Resource use** | ~150–300 MB RAM idle; a tailor run spikes CPU for 2–3 min. `DISK_GB=8` fits app + LibreOffice + a few hundred outputs. |
| **Destroy** | `pct stop 210 && pct destroy 210` — and delete the node from the Tailscale admin console. |
