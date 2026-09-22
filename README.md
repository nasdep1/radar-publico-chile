# Radar Público Chile

**Etapa actual:** integración inicial con la API oficial de Mercado Público.

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

## Tests

```bash
pytest
```

Los tests unitarios usan mocks: no consultan la API real ni requieren ticket.

## Estructura

```
src/config.py                   Carga .env y define host, path, timeout.
src/sources/mercado_publico.py  MercadoPublicoClient (fecha, activas, código).
scripts/test_mercado_publico_api.py  Prueba de integración con la API real.
tests/test_mercado_publico.py   Tests unitarios con mocks.
data/                           Datos locales (no se versionan).
```

## API utilizada

`https://api.mercadopublico.cl/servicios/v1/publico/licitaciones.json`

Solo se usan parámetros documentados: `ticket`, `fecha` (DDMMAAAA), `estado`
(`activas` o los códigos 5, 6, 7, 8, 18, 19) y `codigo`. La API **no** ofrece
búsqueda libre por texto.

### Estructura real del JSON

**Listado por fecha**: observado el 22-09-2026 con `fecha=22092026`, que
devolvió 780 licitaciones.

- Claves de nivel superior: `Cantidad`, `FechaCreacion`, `Version`, `Listado`.
- Claves de cada registro de `Listado`: `CodigoExterno`, `Nombre`,
  `CodigoEstado`, `FechaCierre`.
- El código de licitación está en `CodigoExterno` (ejemplo: `1019-102-LE26`).

**Detalle por código**: **pendiente de verificar con la API real**. La primera
consulta de detalle, hecha inmediatamente después del listado, respondió HTTP 429:

```json
{"Codigo":10500,"Mensaje":"Lo sentimos. Hemos detectado que existen peticiones simultáneas."}
```

Por eso se agregaron la pausa antes del detalle y los reintentos ante 429. Cuando
el detalle responda correctamente, documentar aquí su estructura y sus diferencias
con el listado (el script imprime las claves que solo aparecen en el detalle).

No se define todavía un modelo de licitación ni un esquema de base de datos.

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
