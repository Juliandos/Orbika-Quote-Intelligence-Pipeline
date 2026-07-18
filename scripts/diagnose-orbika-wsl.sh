#!/usr/bin/env bash
set -euo pipefail

echo '== docker =='
docker.exe version || true

echo '== ports =='
ss -ltnp | grep -E ':(5433|8001|3000)\b' || true

echo '== api health =='
curl -fsS http://127.0.0.1:8001/api/health || true

echo '== web head =='
curl -I -s http://127.0.0.1:3000 | head -n 5 || true

echo '== web log tail =='
tail -n 20 local/launcher/web.log || true

echo '== api log tail =='
tail -n 20 local/launcher/api.log || true
