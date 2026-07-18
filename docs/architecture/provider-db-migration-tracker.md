# Provider DB Migration Tracker

Este archivo es el registro vivo para migrar el matching de proveedores y las revisiones asociadas desde archivos del filesystem hacia PostgreSQL, sin romper el flujo CLI actual.

La regla operativa es simple:

- Los snapshots y CSVs de proveedores siguen existiendo como evidencia y respaldo.
- La base de datos debe ser la fuente de verdad operativa.
- `supplier_quote_matcher.py` debe terminar leyendo desde la DB.
- El front y la API deben consumir solo DB para mostrar resultados.

## Objetivo

Migrar el flujo de catÃ¡logo de proveedores y matching de cotizaciones a una arquitectura DB-first, conservando compatibilidad temporal con los snapshots actuales.

## Alcance

- ExtracciÃ³n de proveedores.
- Ingesta de catÃ¡logos extraÃ­dos hacia PostgreSQL.
- Matching determinista de cotizaciones.
- RevisiÃ³n agÃ©ntica y bÃºsqueda web.
- Persistencia final para API y front.

## Secuencia de migraciÃ³n

### Fase 1. Inventario y espejo

- Mantener los extractores vivos generando snapshots.
- Crear una ingesta que copie snapshots a PostgreSQL.
- No eliminar la lectura por filesystem todavÃ­a.

VerificaciÃ³n:

- El snapshot del proveedor existe.
- La tabla espejo en DB contiene los mismos productos.
- El conteo de productos en DB coincide con el snapshot o queda explÃ­citamente reportada la diferencia.

### Fase 2. Repositorio unificado

- Introducir una capa de acceso tipo repositorio para catÃ¡logo de proveedores.
- Exponer la misma estructura lÃ³gica que hoy usa `supplier_quote_matcher.py`.
- Permitir dos implementaciones:
  - DB
  - snapshot local como fallback

VerificaciÃ³n:

- El matcher puede cargar catÃ¡logos desde DB.
- Si DB no estÃ¡ disponible, el fallback local sigue funcionando.
- El top 3 de matches por repuesto se mantiene estable o dentro de tolerancia razonable.

### Fase 3. DB como lectura primaria

- Cambiar `supplier_quote_matcher.py` para consultar DB por defecto.
- Dejar el filesystem como respaldo temporal.

VerificaciÃ³n:

- Un quote procesado desde DB produce resultados equivalentes al flujo anterior.
- No se rompe `provider_refresh.py`.
- El CLI actual sigue funcionando.

### Fase 4. Persistencia final y consumo

- Confirmar que la revisiÃ³n agÃ©ntica, los internet matches y los matches de proveedores se escriben bien en DB.
- Asegurar que `apps/api` y `apps/web` lean la versiÃ³n persistida.

VerificaciÃ³n:

- La API devuelve los matches correctos.
- El front muestra los links y la revisiÃ³n agÃ©ntica.
- No depende de archivos locales para renderizar el estado operativo.

### Fase 5. ReducciÃ³n de dependencia de archivos

- Mantener los snapshots solo como respaldo, auditorÃ­a o debug.
- Evitar que el flujo operativo dependa de rutas locales para decidir matches.

VerificaciÃ³n:

- El sistema puede operar aunque el front no lea snapshots.
- Los snapshots siguen disponibles para revisiÃ³n manual.

## Tablas mÃ­nimas sugeridas

### `provider_catalog_snapshots`

- `id`
- `provider_id`
- `snapshot_date`
- `source_path`
- `source_hash`
- `product_count`
- `status`
- `notes`
- `created_at`
- `loaded_at`

### `provider_products`

- `id`
- `snapshot_id`
- `provider_id`
- `product_name`
- `normalized_name`
- `reference`
- `sku`
- `supplier_item_code`
- `brand`
- `category_name`
- `subcategory_name`
- `detail_url`
- `detail_url_hash`
- `price`
- `currency`
- `availability`
- `searchable_text`
- `taxonomy_labels`
- `raw_payload`
- `created_at`
- `updated_at`

## Ãndices mÃ­nimos

- `provider_catalog_snapshots(provider_id, snapshot_date desc)`
- `provider_products(provider_id)`
- `provider_products(reference)`
- `provider_products(detail_url_hash)`
- `provider_products(snapshot_id)`

## Archivos concretos a migrar

- `tools/supplier_quote_matcher.py`
- `tools/provider_refresh.py`
- `tools/postgres_quote_persistence.py`
- `tools/incremental_orbika_quote_runner.py`
- `tools/agentic_match_reviewer.py`
- `apps/api/orbika_console_api/postgres_store.py`
- `apps/web/app/page.tsx`

## BitÃ¡cora de avances

Registra cada avance cuando una verificaciÃ³n quede cerrada.

| Fecha | Paso | Estado | VerificaciÃ³n | Evidencia |
| --- | --- | --- | --- | --- |
| 2026-07-13 | Definir migraciÃ³n DB-first para proveedor | Hecho | Se acordÃ³ que la DB debe ser la fuente operativa de verdad y que snapshots quedan como respaldo. | ConversaciÃ³n con el operador y anÃ¡lisis del flujo actual. |
| 2026-07-13 | Identificar dependencia actual del matcher | Hecho | `supplier_quote_matcher.py` sigue cargando el Ã­ndice desde `supplier_catalog/providers/.../snapshots/...`. | RevisiÃ³n directa del cÃ³digo. |
| 2026-07-13 | Definir tablas mÃ­nimas | Hecho | Se definieron tablas espejo para catÃ¡logo y snapshot. | Este documento. |

## Criterios para cerrar una fase

Una fase solo se marca como cerrada cuando se cumplan estas condiciones:

- Hay una verificaciÃ³n reproducible.
- El cambio no rompe el flujo CLI actual.
- El front sigue mostrando resultados vÃ¡lidos.
- El resultado nuevo estÃ¡ respaldado por evidencia concreta.

## Formato de actualizaciÃ³n

Cuando se complete un paso nuevo, agregar una fila en la bitÃ¡cora con:

- fecha;
- paso;
- estado;
- verificaciÃ³n;
- evidencia.

Si una verificaciÃ³n falla, registrar tambiÃ©n:

- sÃ­ntoma;
- causa probable;
- siguiente acciÃ³n.



| 2026-07-13 | Crear espejo de catalogo en PostgreSQL | Hecho | `provider_catalog_ingest.py` carga los snapshots vivos a `provider_catalog_snapshots` y `provider_products`. | `providers_seen=28`, `snapshots_upserted=28`, `products_upserted=35554`, `failed=0`. |
| 2026-07-13 | Cambiar matcher a DB-first | Hecho | `supplier_quote_matcher.py` consulta PostgreSQL por defecto y mantiene fallback local. | `load_provider_catalog_index()` devolvio `35554` items y `28` providers desde DB. |
| 2026-07-13 | Ajustar loader de snapshots para compatibilidad | Hecho | Se soporta `products[]` y el formato especial de `disfal`; se excluyo el artefacto espurio de `redpuestos`. | Ingesta en seco coincide con la DB espejo: `35554` productos. |
| 2026-07-14 | Crear vistas de grafo logico sobre PostgreSQL | Hecho | Se crearon `graph_nodes` y `graph_edges` como proyecciones trazables sobre `quotes`, `parts`, `supplier_matches`, `agentic_reviews` y catálogos de proveedores. La API ya expone `graph_context` en el detalle de cotizacion. | `migrations/versions/20260714_0004_graph_logical_views.py`, `tools/graph_postgres_repository.py`, `apps/api/orbika_console_api/postgres_store.py`. |
| 2026-07-14 | Corregir dependencia del helper de grafo en la API | Hecho | `apps/api/orbika_console_api/postgres_store.py` ahora importa `graph_store` interno del paquete de API, eliminando la dependencia de `tools/` dentro del contenedor. | `apps/api/orbika_console_api/graph_store.py`, `apps/api/orbika_console_api/postgres_store.py`. |
| 2026-07-14 | Hacer opcional Docker cuando PostgreSQL ya responde | Hecho | `tools/local_console_launcher.py` ahora acepta un PostgreSQL externo en `5433` sin exigir Docker, y falla con un mensaje claro si no hay DB ni Docker. | `tools/local_console_launcher.py`. |

| 2026-07-14 | Resolver cabezas múltiples de Alembic | Hecho | Se añadió una migración merge para unificar `20260625_0004` y `20260714_0004`, permitiendo `alembic upgrade head`. | `migrations/versions/20260714_0005_merge_rag_and_graph_heads.py`. |
| 2026-07-14 | Validar grafo en DB viva | Hecho | `graph_nodes` y `graph_edges` existen y devuelven datos reales en PostgreSQL. | `nodes=36683`, `edges=37287`, `alembic_version=20260714_0005`. |
| 2026-07-14 | Verificar arranque completo de consola | Hecho | `tools/local_console_launcher.py start` ahora aplica migraciones con `uv` y levanta servicios sobre la DB viva. | `api=200 OK`, `web=200 OK`, `alembic_version=20260714_0005`. |

| 2026-07-14 | Hacer DB-first trazable en supplier_quote_matcher | Hecho | supplier_quote_matcher.py ahora expone catalog.source, soporta catalog_source=db|db-first|snapshots y deja evidencia clara cuando usa PostgreSQL o fallback local. | Validado con .venv/bin/python: postgres y provider_catalog_snapshots+provider_products. |

| 2026-07-14 | Hacer persistente la busqueda web en la revision agendtica | Hecho | internet_quote_matcher.py ahora rescata snapshots cuando PostgreSQL no tiene el candidato y supplier_quote_matcher.py conserva internet_search e internet_matches al guardar. | Validado con d264fd6c97c8cd3080dc9681: parts_with_internet_matches=1 y link de Imotriz persistido. |

| 2026-07-14 | Forzar API DB-first por defecto | Hecho | Cuando existe DATABASE_URL, ORBIKA_API_STORE ahora resuelve a postgres por defecto; JSON queda solo como override explicito. | apps/api/orbika_console_api/config.py, tests/test_api_store_config.py |
| 2026-07-14 | Corregir clasificacion de links web en la API | Hecho | La revision agnostica/persistencia marcan `web_validated` como `internet_search`, para que el front muestre los enlaces en la pestaña de busqueda en internet. | Validado con `d264fd6c97c8cd3080dc9681`: `internet_count=2` en `/api/quotes/...`. |
