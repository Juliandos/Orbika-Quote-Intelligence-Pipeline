# Auditoria Nivel Produccion - Orbika

Fecha: 2026-07-18.

Alcance: Orbika corriendo en portatil/servidor Debian 13 con Docker Compose desde `/home/julian/desarrollos/orbika-runtime`.

## Resumen Ejecutivo

El sistema esta en un estado mucho mas avanzado que la etapa WSL anterior: ya opera como stack Docker nativo en Debian, con web, API, runner, Postgres, Redis, SearXNG y Traefik.

Veredicto actual:

- Apto para uso real supervisado.
- Muy cerca de produccion formal.
- Pendientes principales: backup automatico verificable, monitoreo/alertas y reduccion del punto unico de fallo.

## 1. Disponibilidad

Estado esperado:

- 7 servicios Docker: `traefik`, `orbika-web`, `orbika-api`, `orbika-runner`, `orbika-postgres`, `searxng`, `orbika-redis`.
- Politica `restart: unless-stopped`.
- API bajo `/api`.
- Web bajo `/`.

Verificacion:

```bash
cd /home/julian/desarrollos/orbika-runtime
docker compose ps
curl -I http://127.0.0.1/
curl -I http://127.0.0.1/api/dashboard
```

## 2. Datos E Integridad

- PostgreSQL usa volumen persistente `orbika_postgres_data`.
- Existe al menos un backup manual observado en `~/backups` con tamano no vacio.
- `skills/backup-db.sh` existe y rota los ultimos 14 dumps.
- La automatizacion por cron debe verificarse desde el usuario correcto del portatil.

Verificacion:

```bash
ls -lh ~/backups
crontab -l
docker exec orbika-postgres psql -U orbika -d orbika_local -tAc "SELECT count(*) FROM quotes;"
```

Riesgo vigente: si los backups quedan solo en el mismo disco, un fallo fisico del portatil puede perder datos. Copiar periodicamente a disco externo o nube.

## 3. Fiabilidad

Riesgos pendientes:

- El portatil sigue siendo punto unico de fallo.
- La red debe mantenerse estable, idealmente por cable o con WiFi sin ahorro de energia agresivo.
- Falta alerta automatica si muere el runner, expira la sesion SURA/Gmail o se llena el disco.

## 4. Seguridad

Bien:

- Secretos runtime fuera del repo, en `orbika-runtime/secrets`.
- Servicios internos conectados por redes Docker.
- Cliente Windows debe operar como shell liviano, sin DB ni secretos.

Pendiente:

- Revisar puertos expuestos.
- Revisar dashboard Traefik si esta habilitado.
- Rotar cualquier credencial que haya quedado en documentos historicos.
- No publicar docs con claves reales en GitHub.

## 5. Calidad Funcional

Funcional:

- Ingesta Gmail/SURA.
- Matching determinista contra catalogos.
- Busqueda web via SearXNG.
- Revision IA con proveedor configurado.
- Persistencia en PostgreSQL.
- Panel Operacion para reprocesar matching y revision IA.

Limitaciones conocidas:

- Precio/stock automatico web todavia depende de integraciones futuras.
- La calidad de resultados web puede requerir filtros por proveedor/dominio.
- Algunos docs historicos aun pueden mencionar WSL y deben tratarse como archivo, no guia vigente.

## Plan De Cierre

1. Verificar o montar cron diario para `skills/backup-db.sh`.
2. Copiar backups fuera del disco principal.
3. Agregar healthcheck con alerta para runner, API, disco, Gmail/SURA y backup.
4. Revisar exposicion de Traefik/puertos.
5. Hacer prueba de recuperacion: restaurar un dump en base temporal.
6. Mantener docs vigentes separados de docs historicos.

## Veredicto

Orbika esta apto para operar en piloto/uso real supervisado. Para llamarlo produccion sin vigilancia, cerrar backup externo y monitoreo basico.
