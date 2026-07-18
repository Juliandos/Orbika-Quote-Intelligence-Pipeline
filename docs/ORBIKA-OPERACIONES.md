# Orbika - Manual De Operaciones

Manual operativo vigente para Orbika en Debian 13.

Actualizado: 2026-07-18.

## 1. Resumen

Orbika corre en el portatil/servidor Debian del negocio. El equipo usa una consola web o un cliente Windows liviano; el backend, la base de datos y la ingesta quedan en el servidor.

Flujo:

1. Gmail recibe correos SURA.
2. `orbika-runner` abre los enlaces de cotizacion.
3. Extrae vehiculo, taller y repuestos.
4. Hace matching contra proveedores y busqueda web.
5. Ejecuta revision IA cuando aplica.
6. Guarda resultados en PostgreSQL.
7. `orbika-api` y `orbika-web` muestran la consola.

## 2. Rutas Locales

| Ruta | Uso |
|---|---|
| `/home/julian/desarrollos/orbika` | Codigo fuente |
| `/home/julian/desarrollos/orbika-runtime` | Compose, secretos runtime y configuracion de despliegue |
| `/home/julian/desarrollos/orbika-runtime/secrets` | Credenciales y sesiones, no versionar |
| `/home/julian/desarrollos/orbika/skills` | Scripts de verificacion, backup y soporte |

## 3. Servicios Docker

El compose vigente esta en:

```bash
/home/julian/desarrollos/orbika-runtime/docker-compose.yml
```

Servicios esperados:

- `traefik`
- `orbika-web`
- `orbika-api`
- `orbika-runner`
- `orbika-postgres`
- `searxng`
- `orbika-redis`

## 4. Comandos De Operacion

```bash
cd /home/julian/desarrollos/orbika-runtime

docker compose ps
docker compose up -d
docker compose logs --tail=80 orbika-runner
docker compose logs --tail=80 orbika-api
docker compose restart orbika-api
docker compose restart orbika-runner
```

Chequeo rapido:

```bash
bash /home/julian/desarrollos/orbika/skills/verificar.sh
```

## 5. Verificar Web, API Y Datos

```bash
curl -I http://127.0.0.1/
curl -I http://127.0.0.1/api/dashboard
docker exec orbika-postgres psql -U orbika -d orbika_local -tAc "SELECT count(*) FROM quotes;"
docker exec orbika-postgres psql -U orbika -d orbika_local -tAc "SELECT count(*) FROM provider_products;"
```

## 6. Runner 24/7

El runner revisa Gmail cada 5 minutos (`300s`).

Para ver actividad:

```bash
docker logs orbika-runner --tail 120
```

Buscar senales como:

- ciclos recientes de Gmail;
- cotizaciones procesadas;
- `sleeping=300s`;
- errores de login SURA;
- errores de red o Playwright.

## 7. Reprocesamiento Desde La Consola

El panel `Operacion` llama a:

```text
POST /api/tasks/supplier-matching/run
POST /api/tasks/agentic-review/run
```

Puede correr sobre todas las cotizaciones o solo las marcadas.

Para revisar tareas:

```bash
curl -s http://127.0.0.1/api/tasks
docker logs orbika-api --tail 100
```

## 8. Backups

Backup manual:

```bash
mkdir -p ~/backups
docker exec orbika-postgres pg_dump -U orbika -d orbika_local --format=custom --no-owner --no-privileges > ~/backups/orbika_$(date +%F_%H%M).dump
```

Si `skills/backup-db.sh` esta instalado en cron, verificar:

```bash
crontab -l
ls -lh ~/backups | tail
```

Punto importante: un backup en el mismo disco protege contra errores logicos, pero no contra dano del portatil. Copiar periodicamente a un medio externo o nube.

## 9. Actualizar Codigo En Produccion

Despues de editar en `/home/julian/desarrollos/orbika`:

```bash
cd /home/julian/desarrollos/orbika-runtime
docker compose build orbika-api
docker compose up -d orbika-api
```

Para frontend:

```bash
cd /home/julian/desarrollos/orbika-runtime
docker compose build orbika-web
docker compose up -d orbika-web
```

Para runner:

```bash
cd /home/julian/desarrollos/orbika-runtime
docker compose build orbika-runner
docker compose up -d orbika-runner
```

## 10. Troubleshooting

| Sintoma | Revisar |
|---|---|
| Web no carga | `docker compose ps`, `orbika-web`, Traefik, red |
| API no responde | `docker logs orbika-api --tail 100` |
| No entran cotizaciones | `docker logs orbika-runner --tail 120`, Gmail, sesion SURA |
| DB no responde | healthcheck de `orbika-postgres`, volumen `orbika_postgres_data` |
| Matching/revision falla | logs de `orbika-api`, endpoints `/api/tasks` |
| Cliente Windows no abre | conectividad a servidor, Tailscale/LAN, URL configurada |

## 11. Seguridad

- No escribir credenciales reales en documentos versionados.
- Mantener secretos en `orbika-runtime/secrets`.
- No subir `storage-state.json`, tokens Gmail ni dumps reales.
- Revisar exposicion de Traefik/dashboard y puertos abiertos.
- Rotar credenciales compartidas si se filtraron en docs antiguos.

## 12. Contexto Corto Para Soporte

```text
Orbika corre en Debian 13 con Docker Compose.
Codigo: /home/julian/desarrollos/orbika
Runtime: /home/julian/desarrollos/orbika-runtime
Servicios: traefik, orbika-web, orbika-api, orbika-runner, orbika-postgres, searxng, orbika-redis.
La API esta bajo /api, la web bajo /.
PostgreSQL es la fuente de verdad.
El runner revisa Gmail/SURA cada 300s y persiste en Postgres.
Antes de borrar o modificar datos, hacer pg_dump.
```
