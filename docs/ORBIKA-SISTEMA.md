# Orbika Quote Intelligence - Documentacion Del Sistema

Actualizado: 2026-07-18.

Este documento describe el estado actual despues de la reconstruccion a Debian 13 nativo.

## 1. Que Es Orbika

Orbika es un pipeline de inteligencia de cotizacion de autopartes para SURA:

```text
Gmail
  -> Runner incremental Python/Playwright
  -> Portal SURA
  -> Extraccion de vehiculo, taller y repuestos
  -> Matching contra catalogos de proveedores
  -> Busqueda web via SearXNG
  -> Revision IA via proveedor compatible OpenAI/Gemini
  -> PostgreSQL
  -> FastAPI
  -> Consola web/PWA
```

## 2. Arquitectura De Ejecucion

El sistema corre en Debian 13 con Docker Compose.

- Codigo fuente: `/home/julian/desarrollos/orbika`
- Runtime: `/home/julian/desarrollos/orbika-runtime`
- Compose real: `/home/julian/desarrollos/orbika-runtime/docker-compose.yml`
- Secretos runtime: `/home/julian/desarrollos/orbika-runtime/secrets/`

Servicios:

| Servicio | Funcion |
|---|---|
| `traefik` | Reverse proxy local, enruta web y API |
| `orbika-web` | Next.js export servido por nginx |
| `orbika-api` | FastAPI, dashboard, quotes, tareas y eventos |
| `orbika-runner` | Ingesta 24/7 Gmail/SURA, matching, web e IA |
| `orbika-postgres` | PostgreSQL 16 + pgvector, fuente de verdad |
| `searxng` | Metabuscador para evidencia web |
| `orbika-redis` | Cache de busquedas web y paginas |

Diagrama:

```text
Traefik (:80)
  ├─ /      -> orbika-web
  └─ /api   -> orbika-api -> orbika-postgres

orbika-runner
  ├─ Gmail/SURA
  ├─ orbika-postgres
  ├─ searxng
  ├─ orbika-redis
  └─ Gemini/LLM configurado
```

## 3. Fuente De Verdad

PostgreSQL es la fuente de verdad operacional.

Los archivos JSON historicos o generados siguen siendo utiles para compatibilidad, depuracion o auditorias puntuales, pero la consola debe leer datos desde la API/PostgreSQL.

No se deben versionar:

- secretos OAuth;
- tokens Gmail;
- `storage-state.json` de Playwright/SURA;
- dumps reales de base de datos;
- perfiles de navegador;
- archivos en `orbika-runtime/secrets/`.

## 4. Modelo De Datos

Tablas principales:

| Tabla | Descripcion |
|---|---|
| `emails` | Correo entrante de Gmail |
| `quotes` | Solicitud de cotizacion |
| `vehicles` | Vehiculo asociado a la cotizacion |
| `workshops` | Taller o punto de entrega |
| `parts` | Repuestos solicitados |
| `supplier_matches` | Coincidencias contra catalogos |
| `agentic_reviews` | Revision IA/heuristica por repuesto |
| `provider_catalog_snapshots` | Snapshot de catalogo por proveedor |
| `provider_products` | Productos normalizados de proveedores |
| `tasks`, `events`, `daily_summaries` | Estado operativo y auditoria |

Relaciones base:

```text
emails  -> quotes
quotes  -> vehicles
quotes  -> workshops
quotes  -> parts
parts   -> supplier_matches
parts   -> agentic_reviews
agentic_reviews -> supplier_matches
provider_catalog_snapshots -> provider_products
```

## 5. Grafo Logico

Orbika mantiene una representacion de grafo logico sobre los mismos datos relacionales:

- `graph_nodes`
- `graph_edges`

Esto permite reconstruir el contexto de una cotizacion con nodos de correo, quote, vehiculo, taller, repuesto, match, producto, proveedor y revision IA.

El API usa `apps/api/orbika_console_api/graph_store.py` para cargar contexto de cotizacion cuando aplica.

## 6. API

Rutas principales:

```text
GET  /api/health
GET  /api/dashboard
GET  /api/quotes
GET  /api/quotes/{quote_key}
GET  /api/events
GET  /api/tasks
POST /api/tasks/incremental-runner/start
POST /api/tasks/{id}/stop
POST /api/tasks/supplier-matching/run
POST /api/tasks/agentic-review/run
POST /api/tasks/provider-refresh/run
```

En produccion local, Traefik publica la API bajo `/api`.

## 7. Runner Incremental

El runner vive como contenedor `orbika-runner`.

Responsabilidades:

- revisar Gmail cada `300s`;
- filtrar correos relevantes de SURA;
- abrir enlaces con Playwright;
- extraer datos de cotizacion;
- hacer matching contra proveedores;
- ejecutar busqueda web;
- pedir revision IA cuando esta configurada;
- persistir resultados en PostgreSQL.

Verificacion:

```bash
cd /home/julian/desarrollos/orbika-runtime
docker logs orbika-runner --tail 100
docker exec orbika-postgres psql -U orbika -d orbika_local -tAc "SELECT count(*) FROM quotes;"
```

## 8. Operacion

Comandos base:

```bash
cd /home/julian/desarrollos/orbika-runtime
docker compose ps
docker compose up -d
docker compose logs --tail=50 orbika-api
docker compose logs --tail=50 orbika-runner
```

Chequeo rapido:

```bash
bash /home/julian/desarrollos/orbika/skills/verificar.sh
```

## 9. Cliente Windows

El cliente Windows debe entenderse como shell liviano o acceso directo a la consola servida por Debian.

No debe correr:

- PostgreSQL;
- API FastAPI;
- runner Python;
- secretos Gmail/SURA;
- catalogos o dumps locales.

Ver `docs/MANUAL-USUARIO.md` y `docs/PRODUCCION-TAURI.md`.

## 10. Deuda Tecnica Y Pendientes

- Cerrar contradicciones historicas en documentos de arquitectura antiguos.
- Asegurar backup automatico externo o al menos fuera del disco principal.
- Agregar monitoreo/alertas basicas para runner, disco, Gmail/SURA y backups.
- Revisar exposicion de dashboards internos.
- Evitar credenciales reales en documentos antes de publicar en GitHub.
- Separar claramente docs vigentes de docs historicos.

## 11. Documentos Relacionados

- `docs/project-context-handoff.md`
- `docs/MANUAL-TECNICO.md`
- `docs/pre-production-checklist.md`
- `docs/AUDITORIA-PRODUCCION.md`
- `docs/architecture/postgres-data-model-v1.md`
- `docs/architecture/graph-postgres-logical-model.md`
