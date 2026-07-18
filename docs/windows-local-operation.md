# Windows Local Operation

Este documento queda como referencia historica de la etapa Windows + WSL.

Actualizado: 2026-07-18.

## Estado Actual

Orbika ya no opera como stack local dentro de WSL. El sistema vigente corre en Debian 13 nativo con Docker Compose:

- Codigo: `/home/julian/desarrollos/orbika`
- Runtime: `/home/julian/desarrollos/orbika-runtime`
- Web: servida por `orbika-web` via Traefik.
- API: `orbika-api` bajo `/api`.
- Ingesta: `orbika-runner` 24/7.
- Datos: `orbika-postgres`.
- Busqueda/cache: `searxng` y `orbika-redis`.

## Que Sigue Siendo Util

Los scripts en `scripts/windows/` y el paquete Tauri pueden seguir sirviendo para entregar una app/atajo a usuarios Windows, pero ya no son el mecanismo principal para levantar backend, frontend ni base de datos.

El `.exe` de Windows debe tratarse como cliente liviano: abre la consola publicada por el servidor. No debe contener secretos, base de datos ni runtime Python.

## Que No Debe Asumirse

- No asumir distro WSL `Ubuntu-26.04`.
- No asumir Docker Desktop.
- No asumir PostgreSQL en host `5433`.
- No asumir API local en `8001`.
- No asumir frontend local en `3000`.
- No usar `tools/local_console_launcher.py` como operacion principal de produccion.

## Operacion Vigente

Usar:

```bash
cd /home/julian/desarrollos/orbika-runtime
docker compose ps
docker compose logs --tail=50 orbika-runner
docker compose up -d
```

Ver tambien:

- `docs/MANUAL-TECNICO.md`
- `docs/pre-production-checklist.md`
- `docs/project-context-handoff.md`

## Si Se Retoma El Cliente Windows

Para un cliente Windows, el objetivo recomendado es:

1. Mantener backend y datos en Debian.
2. Empaquetar un shell Tauri o instalador que abra la URL del servidor.
3. No compilar ni levantar Postgres/API/Next.js dentro del PC del usuario.
4. Documentar solo instalacion y soporte remoto en `MANUAL-USUARIO.md`.
