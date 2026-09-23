"""Ingesta de prueba: listado diario → filtro por Nombre → detalle de candidatas → SQLite.

Uso (desde la raíz del proyecto):
    python scripts/ingest_mercado_publico.py --date 2026-09-22 --query "seguridad municipal"

Consumo de API: 1 consulta de listado + 1 consulta de detalle por cada
candidata que aún no tenga detalle en SQLite (más reintentos solo ante HTTP 429).
Nunca se descarga el detalle de todo el listado.
"""

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

# Permite ejecutar el script directamente desde cualquier directorio y sistema
# operativo: agrega la raíz del proyecto (carpeta padre de scripts/) al path.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import config  # noqa: E402
from src.repositories import licitaciones_repository as repo  # noqa: E402
from src.services.candidate_filter import filter_candidates  # noqa: E402
from src.services.ingestion import download_details, fetch_listado  # noqa: E402
from src.services.normalizer import describe_items  # noqa: E402
from src.services.query_terms import terms_for_query  # noqa: E402
from src.sources.mercado_publico import (  # noqa: E402
    MercadoPublicoClient,
    MercadoPublicoError,
    MercadoPublicoHTTPError,
)

SEPARADOR = "=" * 40


def parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"Fecha inválida: {value!r}. Usa YYYY-MM-DD.") from None


def relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def print_items_diagnostic(codigos) -> None:
    """Muestra la estructura de Items de la primera candidata con detalle guardado."""
    for codigo in codigos:
        licitacion = repo.get_licitacion(codigo)
        if not licitacion or not licitacion["detalle_descargado"]:
            continue
        items = json.loads(licitacion["items_json"]) if licitacion["items_json"] else None
        info = describe_items(items)
        print(f"\nDiagnóstico de Items ({codigo}):")
        print(f"  Tipo: {info['tipo']}")
        print(f"  Claves principales: {info['claves']}")
        print(f"  Lista de items en: {info['clave_lista']}")
        print(f"  Cantidad de items: {info['cantidad_elementos']}")
        print(f"  Claves del primer item: {info['claves_primer_item']}")
        return


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Ingesta de prueba de Mercado Público.")
    parser.add_argument("--date", type=parse_date, default=date.today(), help="Fecha YYYY-MM-DD (por defecto, hoy).")
    parser.add_argument("--query", help='Consulta de prueba, por ejemplo "seguridad municipal".')
    args = parser.parse_args(argv)

    fecha_txt = args.date.strftime("%d-%m-%Y")
    try:
        client = MercadoPublicoClient()
    except config.ConfigError as error:
        print(f"✗ {error}")
        return 1
    repo.initialize_database()

    # PASO 1: listado diario
    print(f"Consultando listado de Mercado Público para {fecha_txt}...")
    try:
        listado = fetch_listado(client, args.date)
    except MercadoPublicoError as error:
        print(f"✗ {error}")
        if isinstance(error, MercadoPublicoHTTPError) and error.body_snippet:
            print(f"  Respuesta (sanitizada): {error.body_snippet}")
        return 1
    print(f"Licitaciones del día: {len(listado.licitaciones)}")
    if listado.cantidad_reportada not in (None, listado.total_recibidas):
        print(f"  (Cantidad reportada por la API: {listado.cantidad_reportada})")
    if listado.omitidas:
        print(f"  Registros omitidos por no traer CodigoExterno: {listado.omitidas}")

    # PASO 2: filtro por Nombre
    if args.query:
        terms = terms_for_query(args.query)
        filtro = filter_candidates(listado.licitaciones, terms)
        candidatas = filtro.candidatas
        print(f"Candidatas por título: {filtro.total_candidatas}")
    else:
        candidatas = []
        print("Sin --query: no se buscan candidatas ni se descargan detalles.")

    # PASO 3: guardar todas las licitaciones básicas (no pisa detalles existentes)
    repo.upsert_licitaciones(listado.licitaciones)

    # PASOS 4 y 5: detalle de candidatas, con caché y pausa entre llamadas
    if candidatas:
        print(f"\nDetalle de candidatas (pausa de {config.DETAIL_REQUEST_PAUSE} s entre consultas a la API):")
    detalles = download_details(client, candidatas, log=print)
    print_items_diagnostic(detalles.desde_api + detalles.desde_cache)

    # PASO 6: resumen
    print(f"\n{SEPARADOR}")
    print("RADAR PÚBLICO — INGESTA")
    print(SEPARADOR)
    print(f"Fecha: {fecha_txt} (guardada como query_date = {args.date.isoformat()})")
    if args.query:
        print(f"Consulta: {args.query}")
    print(f"\nLicitaciones encontradas: {len(listado.licitaciones)}")
    print(f"Candidatas: {len(candidatas)}")
    print(f"Detalles desde API: {len(detalles.desde_api)}")
    print(f"Detalles desde caché: {len(detalles.desde_cache)}")
    print(f"Errores: {len(detalles.errores)}")
    print(f"\nBase local:\n{relative(config.DATABASE_PATH)}")
    print(f"Licitaciones en la base: {repo.count_licitaciones()} "
          f"({repo.count_licitaciones(solo_con_detalle=True)} con detalle)")
    print(SEPARADOR)
    return 1 if detalles.errores else 0


if __name__ == "__main__":
    sys.exit(main())
