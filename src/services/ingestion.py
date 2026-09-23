"""Pasos de la ingesta de Mercado Público: listado diario y detalle de candidatas.

La lógica vive aquí (y no en el script) para poder probar el caché sin API.
Nunca se consulta el detalle de todo el listado: solo de las candidatas.
"""

import time
from dataclasses import dataclass, field

from src import config
from src.repositories import licitaciones_repository as repo
from src.services.normalizer import extract_listado, normalize_detail, normalize_list_item
from src.sources.mercado_publico import MercadoPublicoError


@dataclass
class ListadoResult:
    licitaciones: list = field(default_factory=list)  # registros normalizados
    total_recibidas: int = 0
    cantidad_reportada: object = None  # valor de "Cantidad" tal como llega
    omitidas: int = 0  # registros sin CodigoExterno o con tipo inesperado


@dataclass
class DetailResult:
    desde_api: list = field(default_factory=list)
    desde_cache: list = field(default_factory=list)
    errores: list = field(default_factory=list)  # (codigo, mensaje sanitizado)


def fetch_listado(client, fecha) -> ListadoResult:
    """Descarga y normaliza el listado diario (1 consulta a la API).

    Cada registro lleva `query_date` = la fecha enviada al endpoint (YYYY-MM-DD),
    que no es necesariamente su fecha de publicación.
    """
    response = client.get_licitaciones_by_date(fecha)
    registros = extract_listado(response)
    result = ListadoResult(total_recibidas=len(registros), cantidad_reportada=response.get("Cantidad"))
    vistos = set()
    for item in registros:
        normalized = normalize_list_item(item)
        if normalized is None:
            result.omitidas += 1
        elif normalized["codigo_externo"] not in vistos:
            vistos.add(normalized["codigo_externo"])
            normalized["query_date"] = fecha.isoformat()
            result.licitaciones.append(normalized)
    return result


def download_details(
    client,
    candidatas,
    db_path=None,
    pause_seconds=None,
    sleep=None,
    log=lambda message: None,
) -> DetailResult:
    """Obtiene el detalle de cada candidata, usando SQLite como caché.

    - Si la licitación ya tiene detalle en SQLite, no se llama a la API.
    - Si no, espera `pause_seconds` (por defecto config.DETAIL_REQUEST_PAUSE),
      consulta el detalle, lo normaliza y lo guarda.
    Las consultas son secuenciales. Un error en una candidata no detiene el resto.
    """
    if pause_seconds is None:
        pause_seconds = config.DETAIL_REQUEST_PAUSE
    if sleep is None:
        sleep = time.sleep
    result = DetailResult()
    for candidata in candidatas:
        codigo = candidata["codigo_externo"]
        if repo.licitacion_has_detail(codigo, db_path=db_path):
            result.desde_cache.append(codigo)
            log(f"[cache] {codigo}")
            continue

        sleep(pause_seconds)
        try:
            response = client.get_licitacion_by_code(codigo)
        except MercadoPublicoError as error:
            result.errores.append((codigo, str(error)))
            log(f"[error] {codigo}: {error}")
            continue

        detalle = normalize_detail(response)
        if detalle is None:
            mensaje = "La respuesta de detalle no contiene un registro interpretable."
            result.errores.append((codigo, mensaje))
            log(f"[error] {codigo}: {mensaje}")
            continue
        if detalle["codigo_externo"] != codigo:
            mensaje = f"El detalle corresponde a otro código ({detalle['codigo_externo']})."
            result.errores.append((codigo, mensaje))
            log(f"[error] {codigo}: {mensaje}")
            continue

        repo.upsert_licitacion(detalle, db_path=db_path)
        result.desde_api.append(codigo)
        log(f"[API] {codigo}")
    return result
