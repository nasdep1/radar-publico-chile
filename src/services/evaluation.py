"""Reporte de evaluación manual de candidatas (solo lee datos locales).

La selección reproduce el filtro de la ingesta: los mismos términos
(`terms_for_query`) aplicados con `filter_candidates` sobre el Nombre.
"""

import csv
import json
import re

from src.services.candidate_filter import filter_candidates
from src.services.normalizer import normalize_text

SEPARADOR_VALORES = " | "

CSV_COLUMNS = (
    "codigo_externo",
    "nombre",
    "nombre_organismo",
    "estado",
    "fecha_publicacion",
    "fecha_cierre",
    "descripcion",
    "monto_estimado",
    "tipo",
    "direccion_entrega",
    "items_nombres",
    "items_descripciones",
    "categorias",
    "terminos_coincidentes",
    "relevante_manual",
    "observacion_manual",
)


def extract_items(items_json) -> list:
    """Elementos de Items.Listado (estructura real: {"Cantidad", "Listado": [...]})."""
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


def _text_values(items, key) -> list:
    values = []
    for item in items:
        value = item.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = str(value)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
    return values


def summarize_items(items_json) -> dict:
    """Combina NombreProducto, Descripcion y Categoria (esta última sin duplicados)."""
    items = extract_items(items_json)
    return {
        "items_nombres": SEPARADOR_VALORES.join(_text_values(items, "NombreProducto")),
        "items_descripciones": SEPARADOR_VALORES.join(_text_values(items, "Descripcion")),
        "categorias": SEPARADOR_VALORES.join(dict.fromkeys(_text_values(items, "Categoria"))),
    }


def format_monto(value) -> str:
    if value is None:
        return ""
    return str(int(value)) if float(value).is_integer() else str(value)


def select_candidates(licitaciones, terms):
    """Aplica el mismo filtro por Nombre que la ingesta."""
    return filter_candidates(licitaciones, terms)


def build_rows(licitaciones, terms) -> list:
    """Filas del reporte para las licitaciones con detalle que pasan el filtro."""
    con_detalle = [l for l in licitaciones if l.get("detalle_descargado")]
    resultado = select_candidates(con_detalle, terms)
    rows = []
    for licitacion in resultado.candidatas:
        row = {column: licitacion.get(column) for column in CSV_COLUMNS}
        row.update(summarize_items(licitacion.get("items_json")))
        row["monto_estimado"] = format_monto(licitacion.get("monto_estimado"))
        row["terminos_coincidentes"] = SEPARADOR_VALORES.join(
            resultado.coincidencias[licitacion["codigo_externo"]]
        )
        row["relevante_manual"] = ""
        row["observacion_manual"] = ""
        rows.append({k: "" if v is None else v for k, v in row.items()})
    return rows


def candidates_without_detail(licitaciones, terms) -> list:
    """Códigos que pasan el filtro pero aún no tienen detalle descargado."""
    sin_detalle = [l for l in licitaciones if not l.get("detalle_descargado")]
    return [l["codigo_externo"] for l in select_candidates(sin_detalle, terms).candidatas]


def query_slug(query: str) -> str:
    """"Seguridad Municipal" -> "seguridad_municipal"."""
    return re.sub(r"[^a-z0-9]+", "_", normalize_text(query)).strip("_") or "consulta"


def write_csv(rows, path) -> None:
    """CSV UTF-8 con BOM (Excel y Numbers muestran bien las tildes)."""
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _cell(value, width: int) -> str:
    text = " ".join(str(value).split())
    if len(text) > width:
        text = text[: width - 1] + "…"
    return text.ljust(width)


def format_table(rows) -> str:
    """Tabla simple: CODIGO | NOMBRE | ORGANISMO | TERMINOS COINCIDENTES."""
    widths = (16, 50, 35)
    header = " | ".join(
        [_cell("CODIGO", widths[0]), _cell("NOMBRE", widths[1]), _cell("ORGANISMO", widths[2]),
         "TERMINOS COINCIDENTES"]
    )
    lines = [header, "-" * len(header)]
    for row in rows:
        lines.append(" | ".join([
            _cell(row["codigo_externo"], widths[0]),
            _cell(row["nombre"], widths[1]),
            _cell(row["nombre_organismo"], widths[2]),
            row["terminos_coincidentes"],
        ]))
    return "\n".join(lines)
