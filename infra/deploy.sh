#!/usr/bin/env bash
# Deploy on triagebox-vm: git pull + deps + restart. No CI, same as Duna.
set -euo pipefail
cd "$(dirname "$0")/.."

git pull --ff-only
.venv/bin/pip install -q -r requirements.txt -r requirements-transcribe.txt
sudo systemctl restart triagebox
sleep 2
curl -fsS http://127.0.0.1:8080/api/health && echo && echo "Deploy OK"
