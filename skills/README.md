# skills/ — Automatización de tareas Orbika

Scripts listos para que un agente de IA (o un humano) ejecute tareas repetitivas **sin reinventarlas y sin gastar tokens explorando**. Diseñados para correr en el portátil (o por SSH). Se pueden lanzar **en paralelo** (cada uno es independiente; los que tardan corren en background con `nohup`).

## Cómo usarlos
```bash
cd ~/desarrollos/orbika/skills
chmod +x *.sh   # una vez
./verificar.sh                 # salud del stack
./backup-db.sh                 # respaldo de la DB (¡monta esto en cron!)
./reprocesar.sh <quote_key> agentic   # revisión IA (o 'matching') a una cotización
./rebuild.sh orbika-web        # reconstruir + desplegar un servicio tras editar código
./screenshot.sh                # captura de la UI a /tmp/orbika-ui.png
```

## Trabajo en paralelo (ejemplo)
```bash
# reprocesar varias cotizaciones a la vez, sin bloquear:
for qk in QK1 QK2 QK3; do nohup ./reprocesar.sh "$qk" agentic > /tmp/rep_$qk.log 2>&1 & done
```

## Skills disponibles
| Script | Qué hace | Tarda |
|---|---|---|
| `verificar.sh` | Salud: contenedores, web/api 200, DB count, Redis, disco | ~5s |
| `backup-db.sh` | `pg_dump` de la DB a `~/backups/` (rota los últimos 14) | ~10s |
| `reprocesar.sh` | Dispara matching o revisión IA sobre una cotización y espera el resultado | 30s–3min |
| `rebuild.sh` | `docker compose build + up -d` de un servicio | 30s–3min |
| `screenshot.sh` | Navega la UI con el Chromium del runner y saca captura | ~15s |

## Montar el backup automático (recomendado — hoy NO existe)
```bash
( crontab -l 2>/dev/null; echo "0 3 * * * /home/julian/desarrollos/orbika/skills/backup-db.sh >> /home/julian/backups/backup.log 2>&1" ) | crontab -
```
