# Plan de mejora de Quote Intelligence

Fecha del diagnóstico: 2026-07-10

Este documento registra el diagnóstico técnico del flujo de extracción, matching
determinista y revisión agéntica. El caso de auditoría principal es la
cotización `HHW977_ Fuiste Seleccionado para cotizar _SURA`.

## Resumen del proyecto

Orbika es una consola local para ayudar a un taller a responder cotizaciones
de repuestos. El flujo general es:

1. `tools/gmail_quote_extractor.py` lee mensajes de Gmail en modo solo lectura
   y obtiene el enlace de cotización de Orbika.
2. `tools/orbika_quote_extractor.py` abre la cotización, extrae vehículo,
   taller y repuestos solicitados, y distingue una cotización vacía de una
   cotización con productos.
3. `tools/incremental_orbika_quote_runner.py` mantiene el estado de ejecución,
   procesa cotizaciones nuevas o pendientes y conserva archivos compatibles en
   `local/orbika_incremental/`.
4. Los extractores de `tools/*catalog_extractor*.py` recorren las superficies
   públicas de cada proveedor y escriben snapshots bajo
   `supplier_catalog/providers/<provider>/snapshots/<fecha>/`.
5. `tools/supplier_quote_matcher.py` carga el snapshot más reciente de cada
   proveedor, aplana catálogos heterogéneos, crea índices y produce candidatos
   deterministas por repuesto.
6. `tools/agentic_match_reviewer.py` recibe esos candidatos, aplica una segunda
   capa heurística o un LLM cuando está configurado, y guarda la revisión.
7. `tools/postgres_quote_persistence.py` y el backend FastAPI persisten y
   sirven el resultado; Next.js lo presenta en la consola de operación.

PostgreSQL es la fuente operativa actual, pero los JSON locales siguen siendo
necesarios para compatibilidad, reanudación, auditoría y depuración. Por eso una
mejora no debe asumir que el frontend o PostgreSQL reemplazaron completamente
los artefactos locales.

## Funcionamiento actual del matcher, la revisión agéntica y los extractores

### Extractores y snapshots

El repositorio tiene extractores independientes por proveedor, lo cual es
correcto porque las superficies son muy diferentes. Hay proveedores con:

- listados paginados y URL cambiante, como Totus y Repuestera;
- grillas AJAX o paginación HTML sin cambio de URL, como Autorecambios;
- colecciones Shopify y productos repetidos, como Tus Autopartes;
- catálogos grandes que requieren descubrimiento en navegador y detalle,
  como Autopartesya, Partcar e Imotriz;
- datos sembrados o superficies cuya validación viva aún está documentada como
  pendiente, especialmente algunos extractores antiguos.

Los snapshots recientes muestran que los proveedores grandes concentran la
mayor cobertura:

| Proveedor | Snapshot observado | Productos |
| --- | --- | ---: |
| Partcar | 2026-06-26 a 2026-06-28 | 9.268 |
| Importadoras Asociadas | 2026-06-30 | 6.825 |
| Imotriz | 2026-06-30 | 3.788 |
| Redpuestos | 2026-07-01 | 3.410 |
| Totus | 2026-07-08 | 3.214 |
| Imotriz Soluciones Automotrices | 2026-07-07 | 1.859 |
| Autopartesya | 2026-07-03 | 1.656 |
| Internacional de Partes | 2026-07-07 | 1.424 |
| Propartes | 2026-07-02 | 843 |
| Motorpartes | 2026-07-02 | 747 |
| Importadora EuroBrasil | 2026-07-07 | 512 |
| Autorecambios LTDA | 2026-07-07 | 215 |
| Repuestera | 2026-07-08 | 135 |
| Tus Autopartes | 2026-07-08 | 86 |

Estos conteos no prueban por sí solos que un proveedor esté completo. Un
snapshot grande puede tener títulos pobres, productos duplicados, categorías
mezcladas o campos críticos ausentes. Para matching, un catálogo de 6.000
productos sin referencia, descripción o aplicación vehicular puede ser menos
útil que uno de 500 productos bien estructurados.

Las notas de extracción muestran aprendizajes importantes ya incorporados:

- las páginas deben estabilizarse antes de extraer y antes de cambiar de página;
- los conteos visibles, las tarjetas ocultas y los conteos por categoría no son
  equivalentes;
- los proveedores con verificación humana necesitan reanudar desde la página
  exacta y conservar evidencia intermedia;
- la deduplicación debe hacerse por URL de producto, no por categoría;
- los códigos visibles de algunos proveedores son códigos internos y no deben
  promoverse automáticamente a referencia exacta;
- los fallos de detalle y timeouts deben quedar registrados, no desaparecer del
  resultado final.

El problema pendiente es de observabilidad: el snapshot final normalmente dice
cuántos productos se guardaron, pero no siempre permite responder rápidamente
cuántos fueron visibles, cuántos fallaron, qué páginas fallaron y qué campos
faltaron por proveedor.

### `tools/supplier_quote_matcher.py`

El matcher:

- descubre el snapshot más reciente por proveedor;
- usa flatteners específicos para algunos catálogos y un flattener común para
  otros;
- convierte cada producto en `ProviderItem`;
- indexa referencias, tokens y taxonomías;
- infiere familia y señal primaria del repuesto solicitado y del producto;
- recupera candidatos por referencia, tokens y taxonomía;
- puntúa referencia, familia, señal, tokens, similitud del nombre, marca,
  línea, versión y texto vehicular;
- agrega advertencias de año, lado, marca y vehículo;
- produce `exact_reference`, `vehicle_compatible`, `category_only` o
  `manual_confirmation_required`;
- limita y compacta los resultados guardados para no inflar PostgreSQL y los
  archivos operativos.

La capa ya tiene reglas valiosas: una referencia exacta puede alcanzar 100,
las incompatibilidades duras pueden llevar el candidato a cero, las familias
específicas tienen caps de score y los proveedores con evidencia débil tienen
límites especiales.

El problema es que el score todavía puede sumar muchas señales débiles. La
taxonomía, el texto del vehículo y palabras como `bomper`, `base`, `aceite` o
`filtro` pueden mantener alto un candidato aunque la familia comercial real no
coincida. En un catálogo grande eso genera candidatos que parecen razonables
numéricamente pero son incorrectos para un mecánico.

### `tools/agentic_match_reviewer.py`

Actualmente existen dos modos:

- `HeuristicMatchReviewer`, usado como fallback cuando no hay LLM configurado;
- `LLMMatchReviewer`, usado solo si están disponibles LangChain, `OPENAI_API_KEY`
  y un nombre de modelo.

La revisión heurística recibe hasta los candidatos del matcher y ajusta el
score usando señal primaria, marca/línea/versión del vehículo, solapamiento
léxico, lado, año, preferencias y evidencia RAG. Puede poner un candidato en
cero si detecta una señal incompatible, pero después selecciona los resultados
deduplicados sin un umbral de aceptación explícito suficientemente estricto.

La revisión LLM actual pide JSON con `selected_indexes` y `notes`, pero no exige
un veredicto individual por candidato, una razón estructurada, evidencia
utilizada, nivel de confianza ni una explicación que se conserve por opción.
Además, si el LLM selecciona un índice, se copia el candidato original y no se
garantiza que la decisión haya respetado todas las reglas duras del matcher.

Conclusión: la revisión agéntica actual sí agrega algo de valor en modo
heurístico, especialmente para lado, familia y vehículo, pero todavía no es un
filtro final serio. Primero debe recibir una lista limpia y después debe
clasificar, rechazar y explicar con un contrato estructurado. El LLM no debe
ser el mecanismo que rescata una recuperación contaminada.

## Evaluación de `customer_preference_store.py`

El módulo no hace matching. Carga preferencias globales, por aseguradora,
taller o marca de vehículo y entrega un bundle al matcher y a la revisión:

- proveedores preferidos o evitados;
- marcas preferidas o evitadas;
- preferencia por referencia exacta;
- tolerancia de año;
- máximo de opciones por repuesto;
- notas y scopes aplicados.

La función `load_customer_preferences_for_quote` usa preferencias embebidas en
la cotización o consulta PostgreSQL si existen. El matcher ajusta score y límite
de opciones; la revisión agéntica también lee parte de ese bundle.

Veredicto actual: debe mantenerse temporalmente, pero aislado y con influencia
limitada. No debe poder convertir un producto de familia incorrecta en un match
válido. En el estado actual es una capa secundaria y parcialmente infrautilizada;
si se llenan preferencias sin auditoría puede introducir ruido y hacer que el
resultado dependa de hábitos históricos en lugar de evidencia del producto.

Recomendación: conservar solo preferencias de proveedor, marca y límite de
opciones después de las reglas duras. Desactivar por defecto tolerancia de año
y preferencias de marca hasta tener pruebas de que mejoran casos reales. Toda
preferencia aplicada debe aparecer en la explicación y en una métrica de
regresión.

## Diagnóstico principal

El fallo dominante es la combinación de cuatro problemas:

1. Los snapshots no siempre contienen el mismo nivel de detalle. Algunos
   productos tienen título y URL, pero no descripción, referencia, aplicación
   vehicular o categoría confiable.
2. El retrieval permite entrar por tokens o taxonomías demasiado generales.
3. El scorer puede elevar un candidato de familia distinta con señales
   vehiculares o palabras compartidas.
4. La revisión heurística no tiene una política de rechazo y aceptación por
   familia suficientemente estricta.

El caso HHW977 lo demuestra de forma concreta. En el snapshot procesado hay 38
repuestos y también 38 revisiones, pero varias opciones equivocadas alcanzan
68%, 78%, 87% u 88%.

Ejemplo confirmado: para “Filtro de aceite” el primer resultado de Procar sí es
un filtro de aceite, pero también aparecen filtros de aire acondicionado de
Importadoras Asociadas con 88% y tipo `vehicle_compatible`. Para “Aceite 1/4”
la primera opción es un filtro de aceite con referencia `26320-2F000-MAN`.
Esto no es un problema de falta de razonamiento: es una falta de exclusión de
familia y de interpretación del nombre solicitado.

Otro ejemplo: “Base antena” devuelve como mejor opción `Base-Carcaza-Filtro-
Sportage`, y como segunda opción una tarjeta contaminada de Redpuestos que
contiene texto de muchos productos. Esto indica además un problema de calidad
de extracción o de parsing de tarjetas, no solamente de ranking.

## Por qué faltan productos que sí aparecen en internet

Las causas posibles deben separarse así:

- **Superficie no extraída:** el proveedor puede mostrar el producto en una
  categoría, búsqueda o detalle que el extractor no visita.
- **Paginación incompleta:** una transición prematura, timeout o última página
  no procesada puede perder productos.
- **Verificación humana:** el extractor puede conservar un snapshot anterior si
  no logra resolver o reanudar la verificación.
- **Detalle fallido:** el listado descubre la URL, pero el fetch de detalle
  falla; si el producto no se conserva como registro parcial, desaparece.
- **Naming o URL diferente:** el producto puede usar “soporte”, “guía”,
  “defensa”, “bocel”, “paso rueda” o un código OEM sin el nombre de la
  cotización.
- **Snapshot antiguo:** el producto puede existir hoy y no existir en la fecha
  del snapshot usado por el matcher.
- **Flattening/indexación:** el producto puede estar en `extracted.json` pero
  perderse si el flattener lee otra clave, no normaliza la referencia o no crea
  tokens útiles.
- **Retrieval demasiado estrecho:** el producto existe y está indexado, pero
  ningún token o taxonomía del repuesto activa su recuperación.
- **Scoring o caps:** el candidato se recupera y luego queda por debajo de
  productos peores por tener menos texto vehicular o marca.
- **Revisión final:** un producto correcto puede quedar fuera si la revisión
  conserva solo tres opciones y no distingue bien entre parcial e incorrecto.
- **Refresco operativo:** `provider_refresh.py` ejecuta todos los extractores,
  pero si alguno falla continúa usando snapshots disponibles. El reporte puede
  indicar `completed_with_failures` en extracción y aun así completar matching;
  esto debe quedar como estado degradado visible, no como éxito pleno.

Con los datos actuales no se puede afirmar para cada URL manual de HHW977 que
esté en el snapshot sin una comparación URL por URL. Sí está confirmado que
varios productos buenos ya aparecen en `respuestasis.txt` o en la salida de
matching, mientras que otros hallazgos manuales no aparecen entre los mejores
candidatos. Para cada producto debe generarse una auditoría automática con los
estados `en_snapshot`, `indexado`, `recuperado`, `aceptado` o `no_confirmado`.

## Auditoría del caso HHW977

| Repuesto | Evidencia actual | Diagnóstico |
| --- | --- | --- |
| Base antena | `Base-Carcaza-Filtro-Sportage`, 55%, manual | Incorrecto. La palabra `base` y el vehículo dominaron; falta familia de base de antena. |
| Guía lateral izquierda bomper | Defensa/bomper de Partcar, 68% | Parcial o incorrecto. Se recuperó bomper, pero no guía lateral. El candidato correcto manual debe verificarse en snapshot e índice. |
| Guía lateral derecha bomper | Candidatos de bomper, 88% | El score sobrevalora `bomper` y vehículo; no prueba guía lateral. |
| Broches insonorizante tapa motor | Candidatos por vehículo/carrocería | Debe exigir clip/broche/pin e insonorizante/capot; la coincidencia por Kia no basta. |
| Puertas | Candidatos de manija, vidrio o amortiguador | Familia puerta debe bloquear accesorios distintos salvo evidencia explícita. |
| Bocel estribo | Bocel de compuerta/defensa | Parcial como máximo; falta `estribo` y la posición. |
| Absorbedor bomper | Guía soporte de bomper | Incorrecto o débil; `bomper` compartido no prueba absorbedor. |
| Direccional guardabarro | Candidatos de direccional/defensa | Puede ser parcial/correcto según lado y ubicación; requiere comprobar `guardafango` o `RH`. |
| Filtro de aceite | Procar sí coincide; filtros A/C también al 88% | Error confirmado de familia: aceite motor no es aire acondicionado. |
| Aceite 1/4 | Filtro de aceite como primera opción | Error confirmado de familia: aceite/fluido no es filtro. |
| Líquido refrigerante | Candidato genérico al 54% | No debe recomendarse sin fluido/refrigerante/anticongelante y presentación. |
| Bisagras de capó | Bisagra Focus o resultados genéricos | Parcial/incorrecto; debe exigir capó y penalizar vehículo diferente. |
| Bocel guardafango | Candidatos débiles de bocel | Parcial si coincide bocel y guardafango; requiere lado y aplicación Kia. |
| Bocel exploradora | Candidatos de categoría o accesorios | Incorrecto salvo que diga bocel/reflectivo de exploradora. |
| Bomper superior/inferior | Bomper genérico | Parcial si la variante superior/inferior coincide; no basta `bomper`. |
| Guardafango | Pin guardafango | Incorrecto: pin/clip no es guardafango. |
| Guardapolvo | Paso rueda/guardapolvo | Parcial si coincide lado y delantero; debe preferirse coincidencia directa. |
| Exploradora | Exploradora de otra aplicación | Parcial o incorrecto según año/modelo; la familia sí coincide, pero falta fitment. |
| Base exploradora | Soporte/base genérico | Manual como máximo sin producto explícito de base exploradora. |
| Bisagra puerta | Una opción adecuada y otras genéricas | Debe separarse bisagra superior/inferior, puerta delantera y lado. |
| Kit plumillas | Sin match correcto | El retrieval debe exigir kit/plumilla y no aceptar limpiaparabrisas genérico sin evidencia. |
| Broches bocel | Candidatos de bocel o broches genéricos | Debe exigir clip/broche y bocel/guardafango; no aceptar bocel completo. |
| Porta bocín | Bocín o piezas de suspensión | Parcial solo si coincide soporte/porta bocín; bocín completo no es porta. |
| Parlante y tweeters | Sin match | Correcto no recomendar basura; falta cobertura de audio o nombres indexados. |

La tabla clasifica con base en la evidencia local y en los hallazgos manuales del
usuario. Cuando no se consultó el detalle vivo del proveedor en esta auditoría,
la presencia del producto correcto queda como hipótesis hasta comparar el URL
con el snapshot y abrir el detalle.

## Plan paso a paso

### Fase 1: quick wins

Objetivo: evitar recomendaciones obviamente absurdas sin cambiar la arquitectura.

Archivos: `supplier_quote_matcher.py`, `agentic_match_reviewer.py`, tests de
matcher y revisión.

Cambios:

- agregar una familia obligatoria y una familia prohibida por repuesto;
- bloquear filtros de aceite contra filtros de aire/A-C;
- bloquear fluidos contra filtros, piezas de carrocería y mecánica;
- bloquear piezas completas contra clips, bases, soportes y accesorios;
- exigir `kit` cuando el solicitado diga kit, con tolerancia explícita para
  sinónimos documentados;
- establecer un umbral de aceptación y permitir salida vacía;
- conservar la razón de rechazo por candidato.

Validación: ampliar fixtures con los 38 repuestos HHW977 y exigir que ningún
match de familia incompatible supere la salida final.

Riesgo: bajar cobertura en nombres ambiguos. Mitigación: enviar esos casos a
`manual_confirmation_required`, no eliminarlos silenciosamente.

### Fase 2: endurecimiento del matching determinista

Objetivo: recuperar candidatos relevantes y ordenar por evidencia real.

Cambios:

- separar `part_family`, `part_variant`, `position` y `vehicle_fitment`;
- usar referencias OEM como evidencia fuerte solo cuando estén normalizadas;
- aplicar penalización fuerte por familia distinta antes de sumar vehículo;
- exigir coincidencia de familia para que la marca o el modelo aporten score;
- separar marca del vehículo, marca del fabricante y marca del producto;
- crear alias controlados: guía/soporte, bocel/moldura, guardapolvo/paso rueda,
  exploradora/faro auxiliar, pero no alias entre familias distintas;
- aplicar thresholds por familia, no un único threshold global.

Validación: matriz de confusión por familia y medición de precisión@1,
precisión@3, tasa de candidatos incompatibles y tasa de salida vacía correcta.

### Fase 3: mejora de extractores

Objetivo: aumentar cobertura y evidencia útil por producto.

Cambios:

- guardar `source_page_url`, página, categoría, estado de detalle y errores;
- conservar productos descubiertos aunque falle el detalle, con
  `detail_fetch_status=failed`;
- generar `diff.json` y `summary.md` por proveedor;
- medir páginas esperadas, páginas visitadas, productos visibles, productos
  extraídos, URLs únicas y campos faltantes;
- priorizar Partcar, Importadoras Asociadas, Imotriz, Redpuestos, Totus,
  Autopartesya e Imotriz Soluciones Automotrices;
- revisar en vivo las superficies donde las notas todavía dicen “live
  validation pending”;
- refrescar primero la grilla y luego los detalles de productos relevantes.

Validación: prueba de cobertura por proveedor y comparación URL por URL para
los hallazgos manuales de HHW977.

### Fase 4: mejora de revisión agéntica

Objetivo: convertir la revisión en un filtro final útil y barato.

Contrato recomendado por candidato:

```json
{
  "decision": "accept|partial|reject|manual",
  "rank": 1,
  "reason_code": "same_family|wrong_family|vehicle_mismatch|weak_evidence",
  "evidence": ["family", "reference", "vehicle", "brand"],
  "comment": "texto breve en espanol para el taller"
}
```

Las reglas duras deben ejecutarse antes del LLM. El modelo solo debe comparar
los candidatos restantes, devolver decisiones estructuradas y no inventar
datos. La salida debe permitir cero candidatos. Un modelo barato puede revisar
3 a 5 candidatos por repuesto si recibe campos normalizados en vez de texto
crudo.

Validación: casos sintéticos de familia incompatible, referencia exacta, marca
flexible para consumibles, diferencia de lado y cotización vacía.

### Fase 5: refresco semanal

Objetivo: mantener catálogos actuales y detectar degradación.

Cambios:

- separar estado `completed`, `completed_with_warnings` y `failed`;
- impedir que un refresco se marque plenamente exitoso si un proveedor crítico
  falló o si su conteo cae por debajo de un umbral histórico;
- conservar snapshot anterior si el nuevo está vacío o anormalmente corto;
- registrar nuevos, removidos, cambiados y fallos de página/detalle;
- ejecutar proveedores grandes primero y proveedores con verificación humana en
  una cola que pueda reanudarse;
- refrescar índice solo después de validar el snapshot.

Validación: simulación de extractor fallido, snapshot vacío, caída del 50% y
producto removido.

### Fase 6: validación y métricas

Objetivo: medir calidad real, no solo cantidad de productos.

Métricas mínimas:

- cobertura de URLs por proveedor;
- porcentaje de productos con nombre, URL, referencia, marca y fitment;
- precisión@1 y precisión@3 por familia;
- falsos positivos por familia;
- porcentaje de decisiones `reject`, `partial`, `accept`, `manual`;
- cotizaciones vacías con cero matches;
- costo y latencia de revisión por cotización;
- cambios de cobertura entre snapshots.

## Mejoras a `supplier_quote_matcher.py`

Prioridad inmediata:

1. Inferir familia específica antes de recuperar candidatos.
2. Si la familia solicitada es específica, excluir familias incompatibles en
   retrieval, no solo capar el score al final.
3. Tratar palabras genéricas como `base`, `soporte`, `guía`, `aceite`, `filtro`
   y `bomper` como insuficientes por sí solas.
4. Crear reglas negativas explícitas: filtro de aceite contra filtro A/C o aire;
   aceite contra filtro; puerta contra manija/vidrio/amortiguador; exploradora
   contra base; guardafango contra pin; bocín contra porta bocín; bomper contra
   guía o absorbedor salvo evidencia de variante.
5. Dar más peso al nombre y referencia del producto que a la categoría del
   proveedor.
6. Permitir marca flexible para empaques, tuercas, balineras, fluidos y
   consumibles, pero exigirla con más fuerza para piezas de aplicación
   específica.
7. No usar texto contaminado de tarjetas concatenadas como referencia o nombre.
8. Exigir que el campo `match_type` refleje evidencia real: un producto de
   categoría no debe ser `vehicle_compatible` solo porque comparte Kia y
   Sportage.
9. Emitir `rejection_reasons` y `evidence_flags` en cada candidato descartado
   durante diagnóstico, aunque la salida compacta solo guarde los aceptados.
10. Mantener la deduplicación por URL, pero no deduplicar productos diferentes
    solo porque comparten marca o categoría.

## Mejoras a `agentic_match_reviewer.py`

La revisión debe tener tres pasos deterministas antes de llamar un LLM:

1. Eliminar candidatos con conflicto duro de familia, lado o referencia.
2. Clasificar la evidencia restante en fuerte, parcial, débil o insuficiente.
3. Enviar al modelo solo los mejores candidatos ya limpios.

El LLM debe recibir únicamente:

- nombre y referencia solicitados;
- marca, línea, versión y año del vehículo;
- familia, variante, lado y señales normalizadas;
- nombre, referencia, marca, fitment y URL de cada candidato;
- razones deterministas y advertencias.

Debe devolver JSON validado. Si el JSON falla, usar fallback heurístico y
registrar el fallo. La revisión debe poder rechazar todos los candidatos.
Los comentarios deben usar plantillas basadas en evidencia, por ejemplo:

- “Coincide la familia y la referencia; validar lado antes de cotizar.”
- “Coincide la familia, pero no aparece aplicación exacta para Sportage 2016.”
- “No recomendado: el producto es un filtro de aire acondicionado y se pidió
  filtro de aceite.”

No debe entregar comentarios genéricos como “información insuficiente” sin
decir qué campo faltó.

Para costo, la primera versión puede funcionar sin LLM en casos con reglas
claras y llamar un modelo barato solo para casos ambiguos. Esto reduce tokens y
mejora consistencia.

## Mejoras a extractores, snapshots e indexación

Cada snapshot debe incluir como mínimo:

- fecha y duración;
- páginas o colecciones descubiertas y visitadas;
- URLs visibles y URLs únicas;
- productos con detalle exitoso y fallido;
- campos faltantes por producto;
- errores y evidencia intermedia;
- diff contra el snapshot anterior;
- estado de completitud y advertencias.

Los proveedores grandes deben priorizarse por cobertura y por calidad de campos,
no solo por número de productos. Importadoras Asociadas, Imotriz, Partcar,
Redpuestos y Totus son críticos para encontrar piezas de carrocería y
aplicación; Imotriz y Redpuestos también muestran riesgo de contenido crudo o
tarjetas contaminadas que debe limpiarse antes del índice.

El índice debe guardar campos separados para título original, título
normalizado, referencia, SKU, marca, categoría, familia, variante, lado,
vehículo y fuente. No debe depender de un único texto concatenado.

## Estrategia de refresco semanal

El refresco recomendado es:

1. Ejecutar un preflight de navegador, red, Playwright, PostgreSQL y espacio.
2. Ejecutar primero proveedores críticos.
3. Escribir snapshot temporal y evidencia intermedia.
4. Validar que no esté vacío, que el conteo no caiga anormalmente y que haya
   URLs únicas.
5. Publicar el snapshot como “latest” solo si pasa la validación.
6. Generar diff y actualizar índice.
7. Ejecutar matching sobre una muestra de cotizaciones conocidas.
8. Ejecutar revisión agéntica solo después del matching validado.
9. Persistir PostgreSQL y publicar reporte operativo.

Un proveedor con captcha, modal o verificación humana debe quedar como
`needs_operator` y conservar página actual, URL, screenshot o HTML de evidencia
cuando sea posible. Un fallo de ese proveedor no debe borrar el snapshot sano
anterior ni presentarse como éxito completo.

## Riesgos y tradeoffs

- Endurecer familias puede aumentar salidas vacías; esto es preferible a
  recomendar piezas incompatibles, pero debe medirse.
- La marca no puede ser una regla absoluta: empaques, tuercas, balineras,
  llantas y fluidos pueden ser compatibles entre marcas.
- Más detalle de producto aumenta tiempo de extracción; priorizar detalles para
  candidatos o familias críticas puede reducir el costo.
- Un LLM barato puede clasificar, pero no debe interpretar snapshots crudos ni
  sustituir reglas duras.
- `customer_preference_store.py` puede ser útil para operación, pero debe tener
  un peso menor que familia, referencia y fitment.
- Las cifras de productos del snapshot no equivalen a cobertura real si faltan
  referencias, marcas o descripciones.

## Próximos pasos recomendados

1. Implementar primero las reglas de familia y el umbral de aceptación.
2. Crear fixtures de los 38 repuestos de HHW977 y sus hallazgos manuales.
3. Auditar URL por URL si los productos manuales están en snapshots, índice,
   retrieval y salida final.
4. Corregir la contaminación de tarjetas de Redpuestos y cualquier extractor
   que concatene múltiples productos en una referencia.
5. Cambiar la revisión agéntica a un contrato estructurado con rechazo real.
6. Endurecer `provider_refresh.py` para no declarar éxito pleno con extractores
   críticos fallidos.
7. Reextraer proveedores grandes y comparar métricas antes/después.
8. Solo después evaluar si las preferencias de cliente deben ampliarse.

