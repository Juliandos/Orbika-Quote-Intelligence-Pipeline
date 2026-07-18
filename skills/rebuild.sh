#!/usr/bin/env bash
# Reconstruye y despliega un servicio tras editar código. Uso: ./rebuild.sh <servicio>
# servicios: orbika-web | orbika-api | orbika-runner | searxng
set -eu
SVC="${1:?falta servicio (orbika-web|orbika-api|orbika-runner)}"
cd ~/desarrollos/orbika-runtime
echo "[$(date)] build $SVC ..."
docker compose build "$SVC"
echo "[$(date)] up -d $SVC ..."
docker compose up -d "$SVC"
sleep 3
docker compose ps --format '{{.Name}} {{.Status}}' | grep "$SVC" || true
echo "recuerda: la web es PWA → Ctrl+Shift+R en el cliente para ver cambios."
