#!/usr/bin/env bash
#
# deploy.sh — actualiza Triagebox en la VM con un solo comando.
#
# Qué hace, en orden:
#   1. git pull de la última versión.
#   2. Instala/actualiza dependencias Python (solo las base; el proveedor
#      por defecto es groq y no necesita faster-whisper).
#   3. Reinicia el servicio (systemd) y comprueba /api/health.
#
# Uso (dentro de la VM, desde cualquier carpeta):
#   cd ~/triagebox && bash infra/deploy.sh
#
# Requisitos previos (solo la primera vez, ver README.md → "Production"):
#   - repo clonado, .venv creado, .env + apps.yml puestos, servicio instalado.
#
# Nota: si usas TRANSCRIBE_PROVIDER=local (faster-whisper), instala una vez
#   .venv/bin/pip install -r requirements-transcribe.txt
# y descomenta la línea marcada abajo para mantenerlo al día en cada deploy.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> [1/3] Actualizando código (git pull)"
git pull --ff-only

echo "==> [2/3] Instalando dependencias Python"
.venv/bin/pip install -q -r requirements.txt
# Proveedor local (opcional): descomenta si transcribes con faster-whisper.
# .venv/bin/pip install -q -r requirements-transcribe.txt

echo "==> [3/3] Reiniciando el servicio"
sudo systemctl restart triagebox
sleep 2
curl -fsS http://127.0.0.1:8080/api/health && echo && echo "==> Deploy OK"
