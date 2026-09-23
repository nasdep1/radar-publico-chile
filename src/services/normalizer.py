"""Normalización de licitaciones de Mercado Público.

Trabaja sobre la estructura real observada (septiembre de 2026):

- Listado diario: {"Cantidad", "FechaCreacion", "Version", "Listado": [...]},
  cada registro con CodigoExterno, Nombre, CodigoEstado, FechaCierre.
- Detalle por código: misma envoltura; el primer elemento de "Listado" trae
  CodigoExterno, Nombre, Descripcion, Estado, Comprador{CodigoOrganismo,
  NombreOrganismo}, Fechas{FechaPublicacion, ...}, MontoEstimado, Items, etc.

Tolera campos nulos o ausentes, diccionarios y listas vacías y tipos
inesperados: en esos casos el valor normalizado es None.
"""

import json
import math
import re
import unicodedata

_WHITESPACE_RE = re.compile(r"\s+")
# Punto como separador de miles: "2.000", "1.500.000".
_THOUSANDS_RE = re.compile(r"^-?\d{1,3}(\.\d{3})+$")


# --- Texto ------------------------------------------------------------------

def normalize_text(text) -> str:
    """Minúsculas, sin tildes ni diéresis y con espacios compactados.

    "  CÁMARAS   de Seguridad " -> "camaras de seguridad"
    """
    if not isinstance(text, str):
        return ""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    without_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _WHITESPACE_RE.sub(" ", without_marks).strip()


# --- Conversión de valores ----------------------------------------------------

def _to_text(value):
    """Texto limpio para valores escalares; None si está vacío o no es escalar."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return None


def _to_int(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def parse_monto(value):
    """Convierte un monto a float solo cuando es claramente interpretable.

    Acepta números y strings numéricos, incluido el formato chileno con punto
    de miles y coma decimal ("1.500.000,50"). Devuelve None para valores
    nulos, vacíos, booleanos, no finitos o no interpretables.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if not isinstance(value, str):
        return None

    text = value.strip().replace("$", "").replace(" ", "")
    if not text:
        return None
    if "," in text:
        # Formato chileno: punto de miles, coma decimal ("1.500.000,50").
        text = text.replace(".", "").replace(",", ".")
    elif _THOUSANDS_RE.match(text):
        # Solo puntos de miles ("2.000", "1.500.000").
        text = text.replace(".", "")
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _to_json(value):
    """Serializa estructuras para auditoría; None si el valor es None."""
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


# --- Envolturas de la API ---------------------------------------------------

def extract_listado(response) -> list:
    """Registros del listado diario (clave real: "Listado")."""
    listado = _dict(response).get("Listado")
    return listado if isinstance(listado, list) else []


def extract_detail_record(response):
    """Primer registro del detalle por código, o None si no existe."""
    for record in extract_listado(response):
        return record if isinstance(record, dict) else None
    return None


def extract_items(items_json) -> list:
    """Elementos de Items.Listado (estructura real: {"Cantidad", "Listado": [...]}).

    Acepta el JSON guardado en `items_json` o el objeto ya decodificado.
    """
    if not items_json:
        return []
    try:
        items = json.loads(items_json) if isinstance(items_json, str) else items_json
    except ValueError:
        return []
    listado = items.get("Listado") if isinstance(items, dict) else None
    if not isinstance(listado, list):
        return []
    return [item for item in listado if isinstance(item, dict)]


def item_text_values(items, key) -> list:
    """Valores de texto no vacíos de `key` en cada ítem (los números se convierten a texto)."""
    values = []
    for item in items:
        value = _to_text(item.get(key))
        if value is not None:
            values.append(value)
    return values


# --- Normalizadores -----------------------------------------------------------

def normalize_list_item(item):
    """Normaliza un registro del listado diario.

    Devuelve None si el registro no es un objeto o no trae CodigoExterno.
    """
    if not isinstance(item, dict):
        return None
    codigo = _to_text(item.get("CodigoExterno"))
    if codigo is None:
        return None
    return {
        "codigo_externo": codigo,
        "nombre": _to_text(item.get("Nombre")),
        "codigo_estado": _to_int(item.get("CodigoEstado")),
        "fecha_cierre": _to_text(item.get("FechaCierre")),
        "raw_json": _to_json(item),
        "detalle_descargado": 0,
    }


def normalize_detail(detail):
    """Normaliza un registro de detalle al esquema de la tabla `licitaciones`.

    Recibe el registro (primer elemento de "Listado") o la respuesta completa.
    Devuelve None si no hay registro o no trae CodigoExterno. No incluye
    fecha_captura ni fecha_actualizacion: las asigna el repositorio.
    """
    if isinstance(detail, dict) and "CodigoExterno" not in detail:
        detail = extract_detail_record(detail)
    if not isinstance(detail, dict):
        return None
    codigo = _to_text(detail.get("CodigoExterno"))
    if codigo is None:
        return None

    comprador = _dict(detail.get("Comprador"))
    fechas = _dict(detail.get("Fechas"))

    return {
        "codigo_externo": codigo,
        "nombre": _to_text(detail.get("Nombre")),
        "codigo_estado": _to_int(detail.get("CodigoEstado")),
        "estado": _to_text(detail.get("Estado")),
        "descripcion": _to_text(detail.get("Descripcion")),
        "fecha_cierre": _to_text(detail.get("FechaCierre")) or _to_text(fechas.get("FechaCierre")),
        "fecha_publicacion": _to_text(fechas.get("FechaPublicacion")),
        "codigo_organismo": _to_text(comprador.get("CodigoOrganismo")),
        "nombre_organismo": _to_text(comprador.get("NombreOrganismo")),
        "tipo": _to_text(detail.get("Tipo")),
        "moneda": _to_text(detail.get("Moneda")),
        "monto_estimado": parse_monto(detail.get("MontoEstimado")),
        "direccion_entrega": _to_text(detail.get("DireccionEntrega")),
        "direccion_visita": _to_text(detail.get("DireccionVisita")),
        "items_json": _to_json(detail.get("Items")),
        "adjudicacion_json": _to_json(detail.get("Adjudicacion")),
        "raw_json": _to_json(detail),
        "detalle_descargado": 1,
    }


# --- Diagnóstico de Items -----------------------------------------------------

def describe_items(items) -> dict:
    """Resume la estructura de `Items` sin volcar su contenido.

    No asume una estructura definitiva: informa el tipo, las claves de nivel
    superior, qué clave contiene una lista (preferentemente "Listado"), cuántos
    elementos tiene y las claves del primer elemento.
    """
    info = {
        "tipo": type(items).__name__,
        "claves": None,
        "clave_lista": None,
        "cantidad_elementos": None,
        "claves_primer_item": None,
    }
    lista = None
    if isinstance(items, dict):
        info["claves"] = list(items)
        if isinstance(items.get("Listado"), list):
            info["clave_lista"], lista = "Listado", items["Listado"]
        else:
            for key, value in items.items():
                if isinstance(value, list):
                    info["clave_lista"], lista = key, value
                    break
    elif isinstance(items, list):
        info["clave_lista"], lista = "(lista directa)", items

    if lista is not None:
        info["cantidad_elementos"] = len(lista)
        if lista and isinstance(lista[0], dict):
            info["claves_primer_item"] = list(lista[0])
    return info
