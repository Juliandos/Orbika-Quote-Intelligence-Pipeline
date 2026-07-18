# Manual Técnico — Orbika

**App:** Orbika (Consola ACCEDO) · **Cliente:** autolujoslaser · **Aseguradora:** SURA (Colombia)
**Servidor:** portátil Debian 13 (`~/desarrollos/orbika`) · **Actualizado:** 2026-07-17

---

## 1. Qué hace Orbika
1. **Recibe** correos de SURA en Gmail (`autolujoslaser1@gmail.com`).
2. **Extrae** repuestos + datos del vehículo (scraping del portal SURA con Playwright).
3. **Cruza** cada repuesto contra 32 proveedores (~35.500 productos) y contra **búsqueda web** (SearXNG → ML y otros).
4. **Prioriza** con IA (Gemini `gemini-flash-lite-latest`).
5. **Muestra** todo en una consola web.

## 2. Arquitectura
7 contenedores en `~/desarrollos/orbika-runtime/docker-compose.yml`:
```
              Traefik (:80)
             /            \
      PathPrefix(/)   PathPrefix(/api) prio100
          ↓                ↓
     orbika-web       orbika-api ── orbika-postgres (DB)
     (nginx)          (FastAPI)  ╲
                                  ╲─ orbika-runner (24/7) ─ searxng ─ orbika-redis
                                                          └─ Gemini (IA)
```
- Acceso mismo-origen: `http://<IP>/` (web) y `/api` (backend).
- Redes: `orbika-net` (DB interno), `proxy` (Traefik).

## 3. Componentes
| Componente | Tec | Función | mem |
|---|---|---|---|
| orbika-web | Next.js export + nginx | UI (bandeja, comparador, operación, actividad) | 128m |
| orbika-api | FastAPI | `/api/dashboard`, `/quotes`, `/tasks/*` | 2g |
| orbika-runner | Python + Playwright | 24/7: Gmail→SURA→matching→web→IA→persistencia | 3g |
| orbika-postgres | PG16 + pgvector | cotizaciones, catálogo, grafo (vistas) | 1g |
| searxng | metabuscador | búsqueda web (Google/DDG directos bloqueados) | 512m |
| orbika-redis | cache | caché de búsquedas web + páginas | 320m |
| traefik | reverse proxy | ruteo web/api | — |

## 4. Operación
- El portátil se enciende → **todo arranca solo** (docker autostart + `restart: unless-stopped`). Verificado con reinicio.
- El runner revisa Gmail cada 5 min y procesa cotizaciones nuevas (incluida la búsqueda web).
- **Reprocesar cotizaciones** (panel Operación): recalcular matching o revisión IA, sobre todas o solo las marcadas. **Funciona** (se arreglaron 4 bugs del task file-based en deploy DB-first: exporta la cotización desde la API, memoria 2g, `token_set` con año int, fechas en JSON).

## 5. Mantenimiento
- Estado: `bash ~/desarrollos/orbika/skills/verificar.sh`
- Logs: `docker logs orbika-runner --tail 50`
- Actualizar código: editar en `~/desarrollos/orbika/`, luego `docker compose build <servicio> && up -d` (⚠️ RECONSTRUIR la imagen).
- Reprocesar/verificar/backup/screenshot: usar `skills/` (ver `skills/README.md`).
- Acceso remoto: **Tailscale** (`ssh julian@orbika` desde el tailnet del negocio).
- Recetas completas: `.ai-context/04-COMANDOS.md`.

## 6. Datos y respaldo
- Data en el volumen `orbika_postgres_data`.
- Script disponible: `skills/backup-db.sh` genera dumps en `~/backups/` y conserva los últimos 14.
- Evidencia local: existe al menos un dump manual no vacío en `~/backups/`.
- Pendiente operativo: verificar desde el usuario correcto si el cron diario 3AM está montado (`crontab -l`).
- Restaurar: `docker exec -i orbika-postgres pg_restore -U orbika -d orbika_local --clean --if-exists < ARCHIVO.dump`.
- ⚠️ Si el backup queda en el mismo disco, copiar algún `.dump` a otro lado periódicamente.

## 7. El cliente (PC Windows)
`Orbika-Setup.exe` (en `~/desarrollos/orbika-installer/`) instala Tailscale + se une a la red del negocio + crea el ícono. Abre la consola apuntando al portátil por Tailscale (IP 100.87.228.111). No lleva DB ni Python.

## 8. Seguridad
- SSH por llave, UFW (22/80/443), secretos chmod 600, cliente aislado por ACL Tailscale (`tag:cliente`).
- Pendiente: dashboard Traefik (:8080) expuesto a LAN → restringir; firmar el `.exe`.

## 9. Troubleshooting
| Síntoma | Causa | Acción |
|---|---|---|
| Web no carga | contenedor/WiFi | `skills/verificar.sh` |
| Cotización sin matches web | procesada antes de activar web | botón "Revisión IA de selección" |
| Task de reprocesar falla | ver log en `orbika-api:/workspace/local/console_api/<id>.log` | — |
| `No route to host` | WiFi del portátil se cayó | reintentar; pasar a cable |
| Errores conocidos | — | `.ai-context/03-GOTCHAS.md` |
