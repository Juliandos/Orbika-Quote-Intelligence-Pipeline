#!/usr/bin/env bash
# Respaldo de la DB Orbika. Uso: ./backup-db.sh  (montar en cron 3AM)
set -eu
DEST="${HOME}/backups"
mkdir -p "$DEST"
STAMP="$(date +%F_%H%M)"
FILE="${DEST}/orbika_${STAMP}.dump"
echo "[$(date)] pg_dump -> $FILE"
docker exec orbika-postgres pg_dump -U orbika -d orbika_local -Fc > "$FILE"
SIZE="$(du -h "$FILE" | cut -f1)"
echo "[$(date)] listo ($SIZE)"
# rotación: conservar los últimos 14
ls -1t "${DEST}"/orbika_*.dump 2>/dev/null | tail -n +15 | xargs -r rm -f
echo "[$(date)] backups actuales: $(ls -1 ${DEST}/orbika_*.dump 2>/dev/null | wc -l)"
# Restaurar:  docker exec -i orbika-postgres pg_restore -U orbika -d orbika_local --clean --if-exists < ARCHIVO.dump
