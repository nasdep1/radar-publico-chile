"""Términos de búsqueda por consulta.

Expansión manual SOLO para el caso de prueba "seguridad municipal". No es un
sistema general de expansión semántica: cualquier otra consulta se usa tal
cual, como único término. La comparten la ingesta y la evaluación para que
ambas seleccionen exactamente las mismas candidatas.
"""

from src.services.normalizer import normalize_text

EXPANSIONES_DE_PRUEBA = {
    "seguridad municipal": [
        "seguridad",
        "seguridad municipal",
        "seguridad comunal",
        "prevencion del delito",
        "prevención del delito",
        "camara",
        "cámara",
        "camaras",
        "cámaras",
        "televigilancia",
        "cctv",
        "patrullaje",
        "alarma",
        "alarmas",
    ],
}


def terms_for_query(query: str) -> list:
    return EXPANSIONES_DE_PRUEBA.get(normalize_text(query), [query])
