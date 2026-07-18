# Orbika Tauri / Instalador Windows

Referencia vigente para el cliente Windows despues de la reconstruccion Debian 13.

Actualizado: 2026-07-18.

## Estado Actual

La produccion real de Orbika ya no depende de WSL ni de un backend local en Windows.

El backend, la base de datos, la busqueda web y el runner viven en Debian 13:

```text
/home/julian/desarrollos/orbika          codigo fuente
/home/julian/desarrollos/orbika-runtime  compose, secretos runtime y servicios Docker
```

Tauri queda como cliente liviano para Windows: una ventana de escritorio que abre la consola web servida por el portatil/servidor. No debe contener DB, Python, Gmail tokens ni sesion SURA.

## Que Cambio Frente A La Etapa WSL

Antes:

- WSL levantaba PostgreSQL, API y frontend.
- El frontend corria en `localhost:3000`.
- La API corria en `localhost:8001`.
- Postgres usaba host `5433`.
- El build Windows requeria copiar codigo desde WSL a NTFS o compilar en Windows nativo.

Ahora:

- Debian 13 levanta todo con Docker Compose.
- Traefik sirve web y API bajo el mismo host.
- El runner vive 24/7 como contenedor.
- El instalador Windows solo abre la consola.

## Verificacion Del Cliente

Antes de entregar un instalador o acceso Windows:

1. Confirmar que la web responde desde el servidor.
2. Confirmar que la API responde bajo `/api`.
3. Confirmar que el equipo Windows puede llegar al host por LAN/Tailscale.
4. Instalar/abrir el cliente.
5. Validar que el usuario ve cotizaciones y puede abrir enlaces de producto.

## Reconstruir El Instalador

Un instalador `.exe`/`.msi` de Windows debe compilarse en Windows nativo o en CI con runner Windows.

Flujo recomendado:

```powershell
git clone https://github.com/Juliandos/Orbika-Quote-Intelligence-Pipeline C:\orbika
cd C:\orbika\apps\web
npm install
npm run build
cd C:\orbika\apps\desktop
cargo tauri build
```

Si el shell Tauri solo abre una URL remota, normalmente no hace falta reconstruirlo cuando cambian API o frontend en Debian.

## Notas Historicas

Las instrucciones antiguas sobre Docker Desktop, WSL `Ubuntu-26.04`, `localhost:3000`, `localhost:8001`, `5433`, `wsl --shutdown` y copias por `\\wsl.localhost` pertenecen a la etapa anterior. Mantenerlas como diagnostico historico, no como runbook actual.
