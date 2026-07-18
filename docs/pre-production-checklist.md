# Orbika Production Checklist

Checklist vigente para el despliegue actual en Debian 13 nativo.

Actualizado: 2026-07-18.

## Proposito

Confirmar que Orbika esta listo para operar en el portatil/servidor actual:

- Docker levanta todos los servicios.
- La web y la API responden por Traefik.
- PostgreSQL conserva los datos.
- El runner procesa Gmail/SURA cada 5 minutos.
- El panel Operacion puede reprocesar matching y revision IA.
- Hay respaldo y ruta de recuperacion.

## Checklist Diario

- [ ] Estoy en Debian 13, no en una distro WSL.
- [ ] El codigo fuente esta en `/home/julian/desarrollos/orbika`.
- [ ] El runtime esta en `/home/julian/desarrollos/orbika-runtime`.
- [ ] `docker compose ps` muestra `orbika-web`, `orbika-api`, `orbika-runner`, `orbika-postgres`, `searxng`, `orbika-redis` y `traefik` arriba.
- [ ] La web responde en `http://127.0.0.1/`.
- [ ] La API responde en `http://127.0.0.1/api/dashboard`.
- [ ] PostgreSQL responde y `SELECT count(*) FROM quotes;` devuelve datos.
- [ ] Los logs de `orbika-runner` muestran ciclos recientes y espera de `300s`.
- [ ] La consola carga cotizaciones desde la API/PostgreSQL.
- [ ] El panel Operacion puede lanzar matching o revision IA sobre una seleccion.

## Comandos De Verificacion

```bash
cd /home/julian/desarrollos/orbika-runtime
docker compose ps
curl -I http://127.0.0.1/
curl -I http://127.0.0.1/api/dashboard
docker logs orbika-runner --tail 80
docker exec orbika-postgres psql -U orbika -d orbika_local -tAc "SELECT count(*) FROM quotes;"
```

Tambien se puede usar:

```bash
bash /home/julian/desarrollos/orbika/skills/verificar.sh
```

Si el usuario actual no tiene permiso sobre Docker, correr desde un usuario del grupo `docker` o usar `sudo` segun la configuracion del portatil.

## Smoke Test Funcional

1. Abrir la consola Orbika.
2. Seleccionar una cotizacion con repuestos reales.
3. Confirmar datos de vehiculo, taller y repuestos.
4. Confirmar que existen opciones de proveedor o web cuando apliquen.
5. Marcar una cotizacion.
6. Ejecutar `Operacion -> Matching de seleccion`.
7. Ejecutar `Operacion -> Revision IA de seleccion`.
8. Revisar `GET /api/tasks` o la vista Actividad para confirmar que las tareas terminan.

## Gate Antes De Entregar Al Negocio

- [ ] El portatil arranca y Docker inicia solo los contenedores (`restart: unless-stopped`).
- [ ] La red es estable o el portatil esta por cable.
- [ ] Existe backup automatico o manual reciente de PostgreSQL.
- [ ] Se probo restauracion o al menos se verifico que el dump no queda vacio.
- [ ] Los secretos estan fuera del repo.
- [ ] La documentacion para negocio no contiene credenciales reales.
- [ ] El instalador/atajo del cliente abre la URL correcta.
- [ ] `AUDITORIA-PRODUCCION.md` no contradice el estado real de backups, red o monitoreo.

## Que Hacer Si Algo Falla

- Si la web no responde: revisar `docker compose ps`, Traefik y `orbika-web`.
- Si la API no responde: revisar `docker logs orbika-api --tail 100`.
- Si no entran cotizaciones: revisar `docker logs orbika-runner --tail 100`, Gmail y sesion SURA.
- Si la DB falla: revisar healthcheck de `orbika-postgres` y volumen `orbika_postgres_data`.
- Si el reprocesamiento falla: revisar logs de `orbika-api` y archivos de tarea dentro del contenedor API.

## Nota Historica

La checklist anterior estaba escrita para WSL, puertos `5433/8001/3000` y launcher local. Eso corresponde a una etapa previa del proyecto. La operacion vigente es Debian 13 + Docker Compose en `orbika-runtime`.
