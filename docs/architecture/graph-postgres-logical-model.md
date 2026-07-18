# Grafo lógico sobre PostgreSQL

Fecha: 2026-07-14

Este documento define la capa de grafo lógico de Orbika construida sobre
PostgreSQL. La meta no es reemplazar la base relacional, sino usarla como base
operativa única para representar relaciones, evidencia y decisiones de matching
sin romper el flujo actual.

## Propósito

- Mejorar el matching de repuestos con relaciones explícitas y trazables.
- Dar contexto estructurado a la revisión agéntica.
- Evitar depender de archivos sueltos o reglas implícitas difíciles de auditar.
- Mantener compatibilidad con el CLI, la API y la UI actuales.

## Principio rector

PostgreSQL sigue siendo la fuente de verdad. El grafo es una forma de modelar
relaciones dentro de PostgreSQL, no una nueva fuente paralela.

Eso significa:

- ninguna relación importante debe existir solo en memoria;
- ninguna recomendación debe salir sin evidencia rastreable;
- ningún nodo o arista debe nacer de inferencias opacas no reproducibles;
- los archivos locales pueden existir como respaldo, pero no como lógica
  primaria de producción.

## Qué entendemos por grafo

Un grafo lógico en Orbika es el conjunto de:

- nodos: entidades operativas;
- aristas: relaciones válidas entre entidades;
- evidencia: razones verificables que explican por qué existe la relación.

### Nodos principales

- `email`
- `quote`
- `vehicle`
- `workshop`
- `part`
- `provider`
- `provider_snapshot`
- `provider_product`
- `supplier_match`
- `agentic_review`
- `customer_preference`

### Aristas principales

- `email -> quote`
- `quote -> vehicle`
- `quote -> workshop`
- `quote -> part`
- `part -> supplier_match`
- `supplier_match -> provider_product`
- `provider_product -> provider_snapshot`
- `provider_snapshot -> provider`
- `part -> agentic_review`
- `agentic_review -> supplier_match`
- `part -> customer_preference`

## Qué ya existe hoy y se reutiliza

La base relacional ya cubre gran parte del grafo:

- `emails`
- `quotes`
- `vehicles`
- `workshops`
- `parts`
- `supplier_matches`
- `agentic_reviews`
- `customer_preferences`
- `provider_catalog_snapshots`
- `provider_products`
- `tasks`
- `events`

Esto es bueno porque evita duplicar datos. La nueva capa de grafo debe partir de
estas tablas, no sustituirlas.

## Evidencia válida

Para que una relación sea aceptable, debe poder explicarse con datos reales.

### Ejemplos de evidencia válida

- nombre del repuesto solicitado en la cotización;
- referencia validada;
- marca del vehículo;
- URL del producto del proveedor;
- snapshot de catálogo de origen;
- score determinista del matcher;
- comentario de revisión agéntica;
- razón operativa registrada en DB.

### Lo que no es evidencia suficiente

- texto ambiguo sin origen;
- coincidencias “porque sí”;
- links fuera del catálogo ingestado sin trazabilidad;
- reglas duras escondidas en el front;
- lógica dispersa en archivos temporales sin persistencia.

## Reglas anti-código-fantasma

Para que la unión de grafo no se degrade:

1. Toda relación derivada debe guardar su origen.
2. Todo cálculo de score debe ser reproducible.
3. Toda preferencia debe tener alcance y vigencia.
4. Toda ruta de decisión debe poder reconstruirse por `quote_key` y `part_id`.
5. Toda migración debe ser aditiva o reversible.
6. Ningún archivo local debe actuar como autoridad final si la DB existe.

## Diseño recomendado

### Capa relacional base

Se mantiene el esquema actual como base:

- cotización = `quote`
- repuesto solicitado = `part`
- candidato = `supplier_match`
- decisión asistida = `agentic_review`

### Capa de grafo lógico

El grafo se expresa como consultas y vistas sobre tablas existentes.

Ventajas:

- cero duplicación inicial;
- menor riesgo de migración;
- trazabilidad directa;
- fácil rollback.

### Capa materializada futura

Solo si hace falta rendimiento o explotar rutas complejas, se pueden crear
tablas auxiliares materializadas como:

- `graph_nodes`
- `graph_edges`
- `match_paths`
- `evidence_links`

Pero no se crean por defecto hasta que el flujo base esté estable.

## Flujo operativo propuesto

1. Ingesta de cotización.
2. Persistencia en PostgreSQL.
3. Ingesta de catálogos de proveedores.
4. Creación de candidatos deterministas.
5. Proyección de relaciones como grafo lógico.
6. Revisión agéntica usando nodos, aristas y evidencia.
7. Publicación en API y front.

## Buenas prácticas para esta capa

- usar claves estables (`quote_key`, `part_id`, `provider_id`);
- guardar versiones de algoritmo;
- registrar `source_path`, `source_hash` o `detail_url_hash` cuando aplique;
- mantener partición conceptual entre raw input, derived data y operator output;
- agregar índices para navegación por `quote`, `part`, `provider` y `snapshot`;
- evitar columnas que solo existan para “acomodar” la UI;
- preferir tablas auditablemente pequeñas antes que JSON gigante opaco.

## Riesgos a evitar

- mezclar heurísticas de matching con presentación web;
- depender de snapshots como lógica primaria;
- inferir compatibilidades sin evidencia;
- introducir una segunda fuente de verdad en archivos;
- crear relaciones no idempotentes;
- inflar el modelo con tablas innecesarias antes de validar valor real.

## Fases de implementación

### Fase 0: congelar línea base

- respaldar documentos y archivos críticos;
- confirmar tablas existentes;
- anotar dependencias actuales del matcher y la revisión agéntica.

### Fase 1: grafo lógico en consultas

- mapear nodos y aristas desde tablas actuales;
- exponer vistas o repositorios de lectura;
- mantener sin cambios la salida funcional.

### Fase 2: evidencia persistida

- guardar rutas de decisión y explicación en DB;
- mantener trazabilidad por parte y proveedor.

### Fase 3: materialización parcial

- si el rendimiento lo requiere, crear tablas auxiliares de aristas;
- solo después de validar beneficios medibles.

## Criterios de aceptación

La capa de grafo se considerará sana cuando:

- el matcher use DB como fuente primaria;
- la revisión agéntica reciba evidencia estructurada;
- el front pueda mostrar rutas de decisión;
- no exista dependencia operativa de archivos fantasma;
- el pipeline siga funcionando en WSL y sin romper el CLI.

## Decisión técnica recomendada

Para Orbika, la mejor práctica es:

**PostgreSQL + grafo lógico + evidencia persistida**

antes de considerar una base de grafos separada.

Eso reduce complejidad, mejora mantenibilidad y conserva el control
operacional que el proyecto ya tiene.
