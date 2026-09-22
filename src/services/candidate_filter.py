"""Filtro inicial de licitaciones candidatas por palabras clave en el Nombre.

Primera versión deliberadamente sencilla: sin IA, embeddings ni fuzzy matching.
Nombre y términos se normalizan (minúsculas, sin tildes, espacios compactados)
y un término coincide cuando aparece al inicio de una palabra del nombre, de
modo que "camara" coincide con "CÁMARAS", pero "cctv" no coincide dentro de
otra palabra.
"""

import re
from dataclasses import dataclass, field

from src.services.normalizer import normalize_text


@dataclass
class FilterResult:
    candidatas: list = field(default_factory=list)
    total_revisadas: int = 0
    # codigo_externo -> términos (normalizados) que coincidieron
    coincidencias: dict = field(default_factory=dict)

    @property
    def total_candidatas(self) -> int:
        return len(self.candidatas)


def _nombre(licitacion) -> str:
    """Acepta registros normalizados ("nombre") o crudos de la API ("Nombre")."""
    if not isinstance(licitacion, dict):
        return ""
    return licitacion.get("nombre") or licitacion.get("Nombre") or ""


def _codigo(licitacion):
    return licitacion.get("codigo_externo") or licitacion.get("CodigoExterno")


def compile_terms(terms) -> list:
    """Normaliza, deduplica y compila los términos como patrones de inicio de palabra."""
    normalized = []
    for term in terms:
        value = normalize_text(term)
        if value and value not in normalized:
            normalized.append(value)
    return [(value, re.compile(r"(?<!\w)" + re.escape(value))) for value in normalized]


def filter_candidates(listado, terms) -> FilterResult:
    """Devuelve las licitaciones cuyo Nombre contiene alguno de los términos."""
    patterns = compile_terms(terms)
    result = FilterResult()
    for licitacion in listado:
        result.total_revisadas += 1
        nombre = normalize_text(_nombre(licitacion))
        if not nombre:
            continue
        matched = [term for term, pattern in patterns if pattern.search(nombre)]
        if matched:
            result.candidatas.append(licitacion)
            result.coincidencias[_codigo(licitacion)] = matched
    return result
