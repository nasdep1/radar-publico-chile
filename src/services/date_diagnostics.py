"""Diagnóstico de la semántica del parámetro `fecha` del listado de Mercado Público.

Solo describe datos ya guardados en SQLite; no llama a la API ni asume qué
significa el parámetro. Compara la fecha enviada en la consulta (`query_date`)
con las fechas reales de cada proceso.
"""

import json
import re
from dataclasses import dataclass, field

_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")

MENSAJE_DISCREPANCIA = (
    "La consulta con fecha {fecha} devolvió registros cuya FechaPublicacion no coincide "
    "con {fecha}. La semántica exacta del parámetro requiere validación adicional."
)


def date_part(value):
    """'2026-09-22T09:00:00' -> '2026-09-22'; None si no es una fecha ISO reconocible."""
    if not isinstance(value, str):
        return None
    match = _DATE_RE.match(value.strip())
    return match.group(1) if match else None


def detail_fechas(licitacion: dict) -> dict:
    """Objeto `Fechas` del detalle guardado en raw_json ({} si no existe)."""
    if not licitacion.get("detalle_descargado") or not licitacion.get("raw_json"):
        return {}
    try:
        raw = json.loads(licitacion["raw_json"])
    except ValueError:
        return {}
    fechas = raw.get("Fechas") if isinstance(raw, dict) else None
    return fechas if isinstance(fechas, dict) else {}


@dataclass
class DateRow:
    codigo_externo: str
    query_date: object
    fecha_publicacion: object
    fecha_creacion: object
    fecha_cierre: object
    estado: object


@dataclass
class Comparison:
    """Cuántas fechas son anteriores, iguales o posteriores a la fecha consultada."""

    igual: int = 0
    anterior: int = 0
    posterior: int = 0
    sin_dato: int = 0
    minima: object = None
    maxima: object = None


def compare_dates(values, reference: str) -> Comparison:
    result = Comparison()
    known = []
    for value in values:
        day = date_part(value)
        if day is None:
            result.sin_dato += 1
        elif day == reference:
            result.igual += 1
        elif day < reference:
            result.anterior += 1
        else:
            result.posterior += 1
        if day is not None:
            known.append(day)
    if known:
        result.minima, result.maxima = min(known), max(known)
    return result


@dataclass
class DateDiagnosis:
    query_date: str
    rows: list = field(default_factory=list)
    publicacion: Comparison = field(default_factory=Comparison)
    creacion: Comparison = field(default_factory=Comparison)
    cierre: Comparison = field(default_factory=Comparison)

    @property
    def hay_discrepancia(self) -> bool:
        return (self.publicacion.anterior + self.publicacion.posterior) > 0

    def conclusion(self) -> str:
        if not self.rows:
            return "No hay registros con detalle para diagnosticar."
        if self.hay_discrepancia:
            return MENSAJE_DISCREPANCIA.format(fecha=self.query_date)
        if self.publicacion.igual == 0:
            return "Ningún registro trae FechaPublicacion; no es posible comparar."
        return (
            f"Todos los registros con FechaPublicacion coinciden con {self.query_date} en esta "
            "muestra. La semántica del parámetro sigue requiriendo validación con más datos."
        )


def diagnose(licitaciones, query_date: str) -> DateDiagnosis:
    """Compara query_date con las fechas del detalle de cada licitación."""
    rows = []
    for licitacion in licitaciones:
        fechas = detail_fechas(licitacion)
        rows.append(DateRow(
            codigo_externo=licitacion["codigo_externo"],
            query_date=licitacion.get("query_date"),
            fecha_publicacion=licitacion.get("fecha_publicacion") or fechas.get("FechaPublicacion"),
            fecha_creacion=fechas.get("FechaCreacion"),
            fecha_cierre=licitacion.get("fecha_cierre") or fechas.get("FechaCierre"),
            estado=licitacion.get("estado"),
        ))
    return DateDiagnosis(
        query_date=query_date,
        rows=rows,
        publicacion=compare_dates((r.fecha_publicacion for r in rows), query_date),
        creacion=compare_dates((r.fecha_creacion for r in rows), query_date),
        cierre=compare_dates((r.fecha_cierre for r in rows), query_date),
    )
