#!/usr/bin/env bash
# One-time setup for resume-tailor (local, from a clone).
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
echo ">> Using $($PY --version)"

if [ ! -d .venv ]; then
  echo ">> Creating virtualenv (.venv)"
  "$PY" -m venv .venv || {
    echo "!! 'python -m venv' failed. Install the venv module:"
    echo "     Debian/Ubuntu:  sudo apt install python3-venv python3-pip"
    echo "     Fedora:         sudo dnf install python3-virtualenv python3-pip"
    echo "     macOS:          brew install python"
    exit 1
  }
fi

VENV_PY=".venv/bin/python"
"$VENV_PY" -m pip install --upgrade pip >/dev/null
echo ">> Installing resume-tailor + dependencies"
"$VENV_PY" -m pip install -e .
# add the native Anthropic SDK only if you plan to use  --engine anthropic:
#   .venv/bin/pip install -e '.[api]'

echo
echo ">> Done. Then:"
echo "     source .venv/bin/activate"
echo "     resume-tailor init                 # scaffolds profile/ + settings.yaml"
echo "     \$EDITOR profile/profiles/default/master_profile.yaml   # your real resume, once"
echo "     resume-tailor web                  # http://127.0.0.1:8000  -> Settings tab to pick a provider"
echo
echo "   Try it immediately with no API key:  resume-tailor tailor --engine mock --jd examples/sample_job.txt"
echo
if ! command -v libreoffice >/dev/null 2>&1 && ! command -v soffice >/dev/null 2>&1; then
  echo ">> (optional) LibreOffice gives pixel-faithful PDF from the DOCX."
  echo "   Without it, PDFs use a built-in renderer that mirrors the layout."
fi
