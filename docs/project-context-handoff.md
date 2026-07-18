# Orbika Project Context Handoff

Este es el punto de entrada corto y confiable para abrir una nueva conversacion sobre Orbika sin arrastrar contexto viejo de WSL.

Actualizado: 2026-07-18.

## Identidad Actual

- Codigo fuente local: `/home/julian/desarrollos/orbika`
- Runtime de produccion local: `/home/julian/desarrollos/orbika-runtime`
- Sistema operativo actual: Debian 13 nativo en el portatil del negocio.
- Etapa anterior remota: GitHub `Juliandos/Orbika-Quote-Intelligence-Pipeline`, ultimo HEAD conocido antes de esta vinculacion: `b1d7ddbe3a5f6093aac5bee4ebff3b04f025a256`.
- La etapa WSL/Windows local queda como historial. Ya no debe asumirse como arquitectura vigente.

## Que Hace Orbika

Orbika es una consola operativa para cotizaciones de autopartes SURA:

1. Lee correos de Gmail de la cuenta operativa.
2. Abre los enlaces de cotizacion de SURA con Playwright usando sesion guardada fuera del repo.
3. Extrae vehiculo, taller y repuestos.
4. Cruza cada repuesto contra catalogos de proveedores en PostgreSQL.
5. Enriquece con busqueda web via SearXNG y cache Redis.
6. Revisa/prioriza opciones con IA via API compatible OpenAI/Gemini.
7. Persiste cotizaciones, matches, revisiones y grafo logico en PostgreSQL.
8. Expone todo en FastAPI y en una consola web/PWA empaquetable para Windows con Tauri.

## Arquitectura Vigente

El despliegue real corre con Docker Compose desde `orbika-runtime/docker-compose.yml`.

```text
Traefik (:80)
  ├─ PathPrefix(/)    -> orbika-web (Next.js export + nginx)
  └─ PathPrefix(/api) -> orbika-api (FastAPI)

orbika-api
  └─ orbika-postgres (PostgreSQL 16 + pgvector)

orbika-runner (Python + Playwright, 24/7)
  ├─ Gmail / SURA
  ├─ orbika-postgres
  ├─ searxng
  ├─ orbika-redis
  └─ Gemini / proveedor LLM configurado
```

Servicios esperados:

- `orbika-web`
- `orbika-api`
- `orbika-runner`
- `orbika-postgres`
- `searxng`
- `orbika-redis`
- `traefik`

Todos los servicios productivos deben tener `restart: unless-stopped`.

## Fuentes De Verdad

- PostgreSQL es la fuente de verdad operacional.
- `orbika-runtime/secrets/` contiene secretos y sesiones. No se versiona.
- `local/`, perfiles de navegador, dumps y snapshots generados son evidencia runtime, no documentacion primaria.
- Los documentos historicos pueden ayudar a entender decisiones, pero no deben mandar sobre el compose/runtime actual.

## Documentos Que Leer Primero

1. `docs/MANUAL-TECNICO.md`
   Resumen tecnico vigente: arquitectura, componentes, operacion, mantenimiento, backups y seguridad.
2. `docs/MANUAL-USUARIO.md`
   Documento para el negocio: instalacion, uso de la consola y preguntas frecuentes.
3. `docs/ORBIKA-SISTEMA.md`
   Vista tecnica del sistema: datos, API, grafo logico y deuda tecnica actual.
4. `docs/AUDITORIA-PRODUCCION.md`
   Riesgos reales de produccion y plan de cierre.
5. `docs/architecture/postgres-data-model-v1.md`
   Modelo de datos relacional. Leer como diseno/base tecnica, no como estado unico de produccion.
6. `docs/architecture/graph-postgres-logical-model.md`
   Modelo de grafo logico proyectado desde Postgres.
7. `docs/architecture/quote-intelligence-improvement-plan.md`
   Inteligencia de matching, busqueda web, preferencias y calidad.

## Documentos Historicos O De Baja Prioridad

Estos documentos nacieron antes de la reconstruccion Debian/runtime y pueden contener rutas WSL, puertos locales antiguos o instrucciones Windows-local:

- `docs/windows-local-operation.md`
- `docs/PRODUCCION-TAURI.md`
- `docs/pre-production-checklist.md`
- `docs/architecture/desktop-packaging-plan.md`
- `docs/architecture/orbika-implementation-phases.md`
- `docs/architecture/postgres-local-setup.md`

Usarlos solo como historial o como referencia para empaquetado, no como guia de operacion actual.

## Operacion Actual

Comandos base:

```bash
cd /home/julian/desarrollos/orbika-runtime
docker compose ps
docker compose logs --tail=50 orbika-runner
docker compose up -d
```

Chequeo rapido:

```bash
bash /home/julian/desarrollos/orbika/skills/verificar.sh
```

Notas:

- La web debe responder en `http://127.0.0.1/`.
- La API debe responder bajo `http://127.0.0.1/api/...`.
- El runner revisa Gmail cada 300 segundos.
- El reprocesamiento desde el panel Operacion llama endpoints `/api/tasks/supplier-matching/run` y `/api/tasks/agentic-review/run`.

## Reglas Para Nuevos Cambios

- No reintroducir supuestos WSL como requisito operativo.
- No versionar secretos, tokens, dumps, sesiones Playwright ni credenciales reales.
- Mantener backend/UI en espanol cuando sea texto visible del producto.
- Si cambia frontend/backend en Docker, reconstruir la imagen correspondiente antes de validar.
- Si cambia documentacion de operacion, contrastarla contra `orbika-runtime/docker-compose.yml`.
- Antes de publicar en GitHub, revisar que no haya credenciales en docs, compose de produccion o backups.

## Prompt Seed Para Una Nueva Conversacion

```text
Actua como agente de coding senior dentro del repositorio local Orbika.

Contexto vigente:
- Codigo: /home/julian/desarrollos/orbika
- Runtime: /home/julian/desarrollos/orbika-runtime
- Sistema: Debian 13 nativo, no WSL
- Produccion local: Docker Compose con Traefik, web, API, runner, Postgres, Redis y SearXNG
- Fuente de verdad: PostgreSQL
- No versionar secretos ni runtime local

Lee primero:
- docs/project-context-handoff.md
- docs/MANUAL-TECNICO.md
- docs/ORBIKA-SISTEMA.md
- docs/AUDITORIA-PRODUCCION.md

Quiero continuar con: <tarea>
```
