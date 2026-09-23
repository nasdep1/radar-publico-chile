# Radar Público Chile

**Etapa actual (2.2):** scoring contextual de relevancia evaluado contra un
ground truth manual, y diagnóstico de la fecha usada en las consultas.

## Arquitectura actual

```
Mercado Público API
        ↓
Listado diario            1 consulta por fecha (~800 licitaciones básicas)
        ↓
Filtro de candidatos      palabras clave sobre el Nombre (sin IA)
        ↓
Detalle de candidatos     1 consulta por candidata SIN detalle en SQLite
        ↓
Normalización             src/services/normalizer.py
        ↓
SQLite                    data/radar_publico.db (caché y auditoría)
        ↓
Scoring contextual        src/services/contextual_relevance.py (sin IA)
        ↓
Relevante / no relevante
```

### Por qué NO descargamos automáticamente todos los detalles

- El listado diario trae unas 800 licitaciones, pero solo con 4 campos básicos.
  El detalle exige **una consulta por licitación**.
- Descargar todos los detalles costaría ~800 solicitudes por día consultado,
  frente al límite de 10.000 por ticket.
- La API rechaza peticiones seguidas o simultáneas (HTTP 429, código 10500), así
  que las consultas deben ser secuenciales y con pausa: ~800 detalles tardarían
  más de 40 minutos.
- La mayoría de las licitaciones no son pertinentes para una búsqueda concreta.

Por eso el Nombre del listado funciona como un primer filtro barato y solo se
pide el detalle de las candidatas. Además, SQLite actúa como caché: una
licitación con detalle ya descargado no se vuelve a consultar.

## Requisitos

- Python 3.11 o superior (recomendado).
- Un ticket personal de la API de Mercado Público.
- Acceso de red a `api.mercadopublico.cl` (HTTPS, puerto 443).

## Instalación

Desde la raíz del proyecto:

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell)**

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Configuración

1. Copia `.env.example` como `.env`:
   - macOS / Linux: `cp .env.example .env`
   - Windows: `copy .env.example .env`
2. Abre `.env` y pega tu ticket después de `MERCADOPUBLICO_TICKET=`.

`.env` está en `.gitignore` y nunca debe subirse al repositorio. Si la variable
`MERCADOPUBLICO_TICKET` ya existe en el entorno del sistema, tiene prioridad sobre `.env`.

## Ejecución de la prueba real

Con el entorno virtual activado, desde la raíz del proyecto:

```bash
python scripts/test_mercado_publico_api.py
```

El script:

1. valida la configuración (sin mostrar el ticket);
2. consulta el listado de licitaciones del día actual; si no hay resultados,
   retrocede de a un día, hasta 7 días como máximo;
3. muestra solo la estructura del JSON (claves y cantidades, sin volcar datos);
4. identifica el código de la primera licitación a partir de las claves reales;
5. espera 3 segundos (`PAUSA_ANTES_DE_DETALLE_SEGUNDOS` en el script) y consulta
   el detalle de **una sola** licitación.

Consumo máximo: 8 consultas de listado + 1 de detalle (el límite diario de la API
es de 10.000 solicitudes por ticket). Si la API responde HTTP 429, el cliente
reintenta esa misma consulta como máximo 3 veces, esperando 3, 6 y 12 segundos
(`RETRY_429_DELAYS` en `src/config.py`). Ningún otro error se reintenta. Termina con `INTEGRACIÓN MERCADO PÚBLICO: OK`
solo si todos los pasos se completan contra la API real.

## Ingesta de prueba

Con el entorno virtual activado, desde la raíz del proyecto:

```bash
python scripts/ingest_mercado_publico.py --date 2026-09-22 --query "seguridad municipal"
```

- `--date YYYY-MM-DD`: fecha del listado (por defecto, hoy).
- `--query`: consulta de prueba. Solo `"seguridad municipal"` tiene una lista
  manual de términos relacionados (seguridad, cámaras, televigilancia, CCTV,
  patrullaje, alarmas, etc.); cualquier otra consulta se usa tal cual, como
  único término. No es un sistema general de expansión semántica.

Pasos:

1. consulta el listado diario (1 solicitud);
2. filtra candidatas por Nombre (minúsculas, sin tildes, espacios compactados;
   el término debe aparecer al inicio de una palabra: `camara` coincide con
   `CÁMARAS`);
3. guarda todas las licitaciones básicas en SQLite (`detalle_descargado = 0`),
   sin sobrescribir detalles ya guardados;
4. para cada candidata: si ya tiene detalle en SQLite muestra `[cache] CÓDIGO`
   y no llama a la API; si no, espera 3 s (`DETAIL_REQUEST_PAUSE`), consulta el
   detalle, lo normaliza, lo guarda y muestra `[API] CÓDIGO`;
5. muestra la estructura de `Items` de la primera candidata con detalle, sin
   volcar su contenido;
6. muestra un resumen: licitaciones, candidatas, detalles desde API y caché,
   y errores.

Ejecutarlo dos veces con los mismos parámetros no vuelve a descargar detalles.
Un error en una candidata se informa y no detiene las demás.

La base `data/radar_publico.db` no se versiona: contiene datos descargados,
incluidos los contactos de los responsables que publica la API.

## Evaluación manual de candidatas

```bash
python scripts/evaluate_candidates.py --query "seguridad municipal" --date 2026-09-22
```

Lee **solo** la base SQLite local (no llama a Mercado Público) y genera
`data/evaluacion_seguridad_municipal_2026-09-22.csv` con las candidatas que ya
tienen detalle y cuyo `query_date` es esa fecha (sin `--date`: todas las fechas,
en `data/evaluacion_seguridad_municipal.csv`). La selección usa exactamente el mismo filtro por Nombre y los mismos
términos que la ingesta (`src/services/query_terms.py`).

El CSV incluye los datos principales de cada licitación y además:

- `items_nombres` y `items_descripciones`: `NombreProducto` y `Descripcion` de
  todos los ítems, separados por ` | `;
- `categorias`: `Categoria` de los ítems, sin duplicados;
- `terminos_coincidentes`: términos del filtro que aparecen en el Nombre;
- `relevante_manual` y `observacion_manual`: vacías, para completarlas a mano.

Está en UTF-8 con BOM, separado por comas, para que Excel y Numbers muestren bien
las tildes. Si el CSV ya existe, el script no lo sobrescribe (podría tener
evaluaciones manuales); usa `--sobrescribir` para reemplazarlo.

## Relevancia contextual (Etapa 2.2)

### Filtro de candidatos vs. scoring contextual

- **Filtro de candidatos** (`candidate_filter.py`): barato y amplio. Busca
  palabras sueltas en el Nombre del listado ("seguridad", "cámara"...) para
  decidir de qué licitaciones vale la pena descargar el detalle. No se modificó.
- **Scoring contextual** (`contextual_relevance.py`): trabaja solo sobre
  licitaciones con detalle. Combina título, descripción, organismo comprador y
  nombres, descripciones y categorías de los ítems para decidir si la
  licitación trata realmente de *seguridad pública municipal*.

Una palabra aislada no equivale al concepto: "cámara" puede ser sanitaria o
médica, y "seguridad" puede ser hospitalaria, militar o informática.

### Cómo puntúa

- **Señales positivas**: seguridad pública/ciudadana, prevención del delito,
  patrullaje comunitario/municipal/preventivo, televigilancia, lectores de
  patentes, alarmas comunitarias. CCTV y "cámaras de seguridad" solo suman de
  verdad con contexto municipal. Suma también un comprador que es una
  **municipalidad** ("I. Municipalidad de...", "Municipalidad de..."); una
  "Corporación Municipal" no cuenta como municipalidad.
- **Señales negativas**: salud/medicina, saneamiento (cámaras de
  alcantarillado), militar/penitenciario, ciberseguridad, instituciones no
  municipales (tribunales, SII, IPS, Servicio Médico Legal, museos), guardias y
  vigilancia de recintos, y comprador no municipal.
- **Combinaciones**: cámaras + contexto municipal suma; guardias o cámaras +
  hospital/institución/recinto resta.
- Una coincidencia en el título pesa ×1,5, en descripción o ítems ×1 y en
  categorías ×0,5. Cada señal cuenta una vez.
- `score >= umbral` → relevante. Umbral por defecto: **6**.

Señales, pesos, combinaciones, factores y umbral están en **un solo lugar**: el
perfil `SEGURIDAD_MUNICIPAL` de `src/services/contextual_relevance.py`. Cada
resultado incluye las señales que se activaron (término y campo) y una
explicación. No hay reglas por código de licitación ni por municipio concreto
(un test lo verifica).

### Evaluación contra el ground truth

```bash
python scripts/evaluate_relevance.py --query "seguridad municipal"
python scripts/evaluate_relevance.py --query "seguridad municipal" --threshold 5
python scripts/evaluate_relevance.py --query "seguridad municipal" --mostrar-todo
```

Lee solo SQLite y `tests/data/ground_truth_seguridad_municipal.csv` (22
candidatas del 22-09-2026 etiquetadas a mano). Muestra la matriz de confusión
(TP, FP, TN, FN), Precision, Recall y F1, primero para el baseline (filtro por
título) y luego para el scoring. Lista cada falso positivo y falso negativo con
su score y sus señales. Positivo = verdaderamente relacionada con seguridad
pública municipal.

**Baseline** (filtro por título): 22 candidatas, 5 relevantes y 17 no
relevantes → precisión 5/22 = **22,7 %**.

**Resultados del scoring contextual**: *pendientes de la ejecución local*. El
scorer se diseñó con reglas conceptuales, sin acceso a los textos reales de las
22 licitaciones; las métricas reales se obtienen al ejecutar
`evaluate_relevance.py` sobre la base local.

### Limitaciones

- **22 ejemplos no demuestran precisión general.** Sirven como conjunto de
  calibración y evaluación inicial.
- **Recall sobre 22 candidatas ≠ recall global.** Solo conocemos etiquetas de
  las 22 candidatas que pasaron el filtro por título. Podemos medir precision y
  recall del scorer *dentro* de ese conjunto, pero **no** cuántas licitaciones
  relevantes de las ~850 del listado quedaron fuera del filtro inicial. No es
  correcto afirmar que Radar encuentra el 100 % de las licitaciones relevantes.
- El ground truth incluye procesos que pueden ser relicitaciones del mismo
  proyecto (4063-9-LP26 y 4063-13-LP26), lo que puede inflar las métricas.

### Deuda técnica

- **Recall global**: etiquetar una muestra de licitaciones que NO pasaron el
  filtro por título para estimar cuántas relevantes se pierden.
- **Procesos relacionados / relicitaciones**: detectar llamados sucesivos del
  mismo proyecto y agruparlos.
- `query_date` guarda una sola fecha por licitación (la última consulta que la
  devolvió); si la misma licitación aparece en consultas de varias fechas, se
  conserva solo la más reciente.

## Fechas: query_date, fecha_publicacion y fecha_captura

| Columna | Significado |
|---|---|
| `query_date` | Fecha (YYYY-MM-DD) **enviada a Mercado Público** en la consulta de listado que devolvió el registro. Responde a "¿qué devolvió la API cuando consultamos esa fecha?". |
| `fecha_publicacion` | `Fechas.FechaPublicacion` del detalle: cuándo se publicó el proceso. |
| `fecha_captura` | Cuándo Radar guardó el registro por primera vez. |

No son equivalentes: la consulta con `fecha=22092026` devolvió candidatas con
`FechaPublicacion` de agosto y de septiembre. La semántica exacta del parámetro
`fecha` **no está verificada**; para investigarla:

```bash
python scripts/diagnose_date_semantics.py --query-date 2026-09-22
```

No llama a la API. Para las licitaciones con detalle cuyo `query_date` es esa
fecha, muestra CÓDIGO, FECHA CONSULTADA, FECHA PUBLICACION, FECHA CREACION,
FECHA CIERRE y ESTADO; cuenta cuántas FechaPublicacion son iguales, anteriores
o posteriores a la fecha consultada, con la mínima y la máxima, y hace lo mismo
con FechaCreacion y FechaCierre. También compara la FechaCierre de todo el
listado de esa consulta. `--incluir-sin-query-date` agrega los registros
guardados antes de la migración.

**Migración**: al abrir una base existente se agrega la columna `query_date`
con `ALTER TABLE` solo si falta (verificado con `PRAGMA table_info`). La base no
se borra y los registros previos quedan con `query_date` NULL: su valor no se
inventa. Al volver a ejecutar la ingesta de una fecha, el listado asigna
`query_date` a esas licitaciones, incluidas las que ya tienen detalle, sin
volver a descargarlo.

`evaluate_candidates.py --date YYYY-MM-DD` filtra por `query_date` (no por
FechaPublicacion) y genera `data/evaluacion_<consulta>_<fecha>.csv`.

## Tests

```bash
pytest
```

Los tests usan mocks y bases SQLite temporales: no consultan la API real, no
requieren ticket y no tocan `data/radar_publico.db`.

## Estructura

```
src/config.py                               Carga .env; host, path, timeout, pausas, ruta de la base.
src/database.py                             Conexión y esquema SQLite (tabla licitaciones).
src/sources/mercado_publico.py              MercadoPublicoClient (fecha, activas, código).
src/services/normalizer.py                  Normalización de listado y detalle; diagnóstico de Items.
src/services/candidate_filter.py            Filtro de candidatas por palabras clave en el Nombre.
src/services/ingestion.py                   Pasos de la ingesta: listado y detalle con caché.
src/services/query_terms.py                 Términos de la consulta de prueba (compartidos).
src/services/evaluation.py                  Reporte CSV de evaluación manual.
src/services/contextual_relevance.py        Scoring contextual (perfil seguridad municipal).
src/services/relevance_evaluation.py        Ground truth, matriz de confusión y métricas.
src/services/date_diagnostics.py            Comparación de query_date con fechas del proceso.
src/repositories/licitaciones_repository.py Acceso a SQLite (queries parametrizadas, sin ORM).
scripts/test_mercado_publico_api.py         Prueba de integración de la Etapa 1.
scripts/ingest_mercado_publico.py           Ingesta de prueba de la Etapa 2.
scripts/evaluate_candidates.py              Reporte de evaluación (solo lee SQLite).
scripts/evaluate_relevance.py               Métricas del scoring contra el ground truth.
scripts/diagnose_date_semantics.py          Diagnóstico de la fecha consultada.
tests/                                      Tests con mocks y SQLite temporal.
tests/data/                                 Ground truth versionado.
data/                                       Datos locales (no se versionan).
```

## Modelo SQLite

Tabla `licitaciones` (clave primaria `codigo_externo`):

| Columna | Origen en la API |
|---|---|
| `codigo_externo` | `CodigoExterno` |
| `nombre` | `Nombre` |
| `codigo_estado` | `CodigoEstado` (entero o NULL) |
| `estado` | `Estado` (solo detalle) |
| `descripcion` | `Descripcion` (solo detalle) |
| `fecha_cierre` | `FechaCierre` (o `Fechas.FechaCierre`) |
| `fecha_publicacion` | `Fechas.FechaPublicacion` |
| `codigo_organismo`, `nombre_organismo` | `Comprador.CodigoOrganismo`, `Comprador.NombreOrganismo` |
| `tipo`, `moneda` | `Tipo`, `Moneda` |
| `monto_estimado` | `MontoEstimado`, convertido a número solo si es interpretable; si no, NULL |
| `direccion_entrega`, `direccion_visita` | `DireccionEntrega`, `DireccionVisita` |
| `items_json`, `adjudicacion_json` | `Items`, `Adjudicacion` como JSON, sin interpretar |
| `raw_json` | registro original completo, para auditoría |
| `detalle_descargado` | 0 = solo listado, 1 = detalle descargado |
| `fecha_captura`, `fecha_actualizacion` | primera inserción y última actualización (hora local ISO 8601) |
| `query_date` | fecha enviada al endpoint de listado (YYYY-MM-DD); NULL en registros anteriores a la migración |

Las fechas se guardan tal como llegan de la API.

## API utilizada

`https://api.mercadopublico.cl/servicios/v1/publico/licitaciones.json`

Solo se usan parámetros documentados: `ticket`, `fecha` (DDMMAAAA), `estado`
(`activas` o los códigos 5, 6, 7, 8, 18, 19) y `codigo`. La API **no** ofrece
búsqueda libre por texto.

### Estructura real del JSON

**Listado por fecha**: observado el 22-09-2026 con `fecha=22092026` (780 y
luego 797 licitaciones: el listado del día crece durante la jornada).

- Claves de nivel superior: `Cantidad`, `FechaCreacion`, `Version`, `Listado`.
- Claves de cada registro de `Listado`: `CodigoExterno`, `Nombre`,
  `CodigoEstado`, `FechaCierre`.
- El código de licitación está en `CodigoExterno` (ejemplo: `1019-102-LE26`).

**Detalle por código**: verificado con la API real. Usa la misma envoltura
(`Cantidad`, `FechaCreacion`, `Version`, `Listado`); el detalle es el primer
elemento de `Listado`, con estas claves:

`CodigoExterno`, `Nombre`, `CodigoEstado`, `Descripcion`, `FechaCierre`,
`Estado`, `Comprador`, `DiasCierreLicitacion`, `Informada`, `CodigoTipo`, `Tipo`,
`TipoConvocatoria`, `Moneda`, `Etapas`, `EstadoEtapas`, `TomaRazon`,
`EstadoPublicidadOfertas`, `JustificacionPublicidad`, `Contrato`, `Obras`,
`CantidadReclamos`, `Fechas`, `UnidadTiempoEvaluacion`, `DireccionVisita`,
`DireccionEntrega`, `Estimacion`, `FuenteFinanciamiento`, `VisibilidadMonto`,
`MontoEstimado`, `Tiempo`, `UnidadTiempo`, `Modalidad`, `TipoPago`,
`NombreResponsablePago`, `EmailResponsablePago`, `NombreResponsableContrato`,
`EmailResponsableContrato`, `FonoResponsableContrato`, `ProhibicionContratacion`,
`SubContratacion`, `UnidadTiempoDuracionContrato`, `TiempoDuracionContrato`,
`TipoDuracionContrato`, `JustificacionMontoEstimado`, `ObservacionContract`,
`ExtensionPlazo`, `EsBaseTipo`, `UnidadTiempoContratoLicitacion`,
`ValorTiempoRenovacion`, `PeriodoTiempoRenovacion`, `EsRenovable`, `CodigoBIP`,
`Adjudicacion`, `Items`.

- `Comprador` incluye al menos `CodigoOrganismo` y `NombreOrganismo`.
- `Fechas` incluye varias fechas: `FechaCreacion`, `FechaCierre`, `FechaInicio`,
  `FechaPublicacion`, `FechaAdjudicacion`, `FechaEstimadaAdjudicacion`, etc.
- `Items` (verificado): objeto con `Cantidad` y `Listado`. Cada elemento de
  `Items.Listado` trae `Correlativo`, `CodigoProducto`, `CodigoCategoria`,
  `Categoria`, `NombreProducto`, `Descripcion`, `UnidadMedida`, `Cantidad` y
  `Adjudicacion`.

**Diferencias**: el listado solo trae 4 campos (código, nombre, estado y fecha
de cierre). Descripción, comprador, fechas, montos, ítems y adjudicación solo
están en el detalle.

Si la API responde HTTP 429 (`{"Codigo":10500,"Mensaje":"Lo sentimos. Hemos
detectado que existen peticiones simultáneas."}`), el cliente espera y reintenta.


## Decisión de diseño: búsqueda temática (etapas futuras, no implementada)

Como la API no tiene búsqueda libre, una consulta como *"seguridad municipal"*
deberá resolverse localmente:

1. obtener licitaciones candidatas;
2. almacenarlas localmente;
3. combinar título + descripción + productos/ítems disponibles;
4. buscar palabras clave;
5. expandir términos relacionados (p. ej. seguridad comunal, prevención del
   delito, televigilancia, CCTV, cámaras de seguridad, patrullaje, alarmas
   comunitarias);
6. calcular relevancia;
7. devolver resultados pertinentes.
