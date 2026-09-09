# Contributing

```bash
git clone https://github.com/RegatteVarshithReddy/resume-tailor
cd resume-tailor
python -m venv .venv && source .venv/bin/activate
pip install -e ".[api,dev]"
pytest            # runs offline via the `mock` engine
ruff check .
```

- Tests must not need network or an API key — use `--engine mock` / `engine: mock`.
- Keep the runtime dependency list small; anything provider-specific stays optional
  (`[api]`) or stdlib (the OpenAI-compatible client is stdlib on purpose).
- Never commit `profile/`, `.env`, or `profile/secrets.yaml`.
- `deploy/` is one self-host example (Proxmox + Tailscale); it is not required and
  not covered by CI.

Bugs / ideas: open an issue.
