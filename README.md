# Radar Público Chile

**Etapa actual (2):** normalización, caché local en SQLite y filtrado de
licitaciones candidatas de Mercado Público.

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
src/repositories/licitaciones_repository.py Acceso a SQLite (queries parametrizadas, sin ORM).
scripts/test_mercado_publico_api.py         Prueba de integración de la Etapa 1.
scripts/ingest_mercado_publico.py           Ingesta de prueba de la Etapa 2.
tests/                                      Tests con mocks y SQLite temporal.
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
- `Items`: **estructura pendiente de documentar**. La ingesta muestra su tipo,
  sus claves y las claves del primer ítem.

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
