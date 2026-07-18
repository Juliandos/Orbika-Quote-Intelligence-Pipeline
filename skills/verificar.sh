#!/usr/bin/env bash
# Salud del stack Orbika. Uso: ./verificar.sh
set -u
cd ~/desarrollos/orbika-runtime 2>/dev/null || true
echo "=== Contenedores ==="
docker compose ps --format '{{.Name}}  {{.Status}}' 2>/dev/null || docker ps --format '{{.Names}} {{.Status}}' | grep -iE 'orbika|traefik|searxng'
echo "=== Servicio ==="
printf "web  -> %s\n" "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/)"
printf "api  -> %s\n" "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/api/dashboard)"
echo "=== Datos ==="
echo "quotes: $(docker exec orbika-postgres psql -U orbika -d orbika_local -tAc 'SELECT count(*) FROM quotes' 2>/dev/null)"
echo "redis claves: $(docker exec orbika-redis redis-cli DBSIZE 2>/dev/null | grep -o '[0-9]*')"
echo "=== Sistema ==="
echo "RAM: $(free -h|awk '/Mem/{print $3\"/\"$2}') | Disco: $(df -h /|awk 'NR==2{print $4\" libre\"}') | uptime: $(uptime -p)"
