"""Reporte CSV para evaluar manualmente las candidatas de una consulta.

Uso (desde la raíz del proyecto):
    python scripts/evaluate_candidates.py --query "seguridad municipal" --date 2026-09-22

`--date` filtra por `query_date`: la fecha enviada a Mercado Público en la
consulta que devolvió cada registro (no su FechaPublicacion). Sin `--date`
se incluyen todas las fechas de la base.

Lee EXCLUSIVAMENTE la base SQLite local (data/radar_publico.db). No realiza
ninguna llamada a Mercado Público. Selecciona las candidatas con el mismo
filtro por Nombre y los mismos términos que usa la ingesta.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Permite ejecutar el script directamente desde cualquier directorio y sistema
# operativo: agrega la raíz del proyecto (carpeta padre de scripts/) al path.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import config  # noqa: E402
from src.repositories import licitaciones_repository as repo  # noqa: E402
from src.services.evaluation import (  # noqa: E402
    build_rows,
    candidates_without_detail,
    format_table,
    query_slug,
    write_csv,
)
from src.services.query_terms import terms_for_query  # noqa: E402


def relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def parse_date(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError(f"Fecha inválida: {value!r}. Usa YYYY-MM-DD.") from None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Reporte de evaluación manual de candidatas.")
    parser.add_argument("--query", required=True, help='Consulta, por ejemplo "seguridad municipal".')
    parser.add_argument(
        "--date",
        type=parse_date,
        help="Fecha consultada YYYY-MM-DD (query_date). Por defecto, todas las fechas.",
    )
    parser.add_argument(
        "--sobrescribir",
        action="store_true",
        help="Reemplaza el CSV si ya existe (se pierden las columnas manuales ya completadas).",
    )
    args = parser.parse_args(argv)

    db_path = config.DATABASE_PATH
    if not db_path.exists():
        print(f"✗ No existe la base local {relative(db_path)}. Ejecuta primero la ingesta.")
        return 1

    suffix = f"_{args.date}" if args.date else ""
    output = config.DATA_DIR / f"evaluacion_{query_slug(args.query)}{suffix}.csv"
    if output.exists() and not args.sobrescribir:
        print(f"✗ {relative(output)} ya existe y podría tener evaluaciones manuales.")
        print("  Renómbralo o vuelve a ejecutar con --sobrescribir.")
        return 1

    repo.initialize_database(db_path=db_path)  # aplica migraciones pendientes
    todas = repo.list_licitaciones(db_path=db_path)
    sin_query_date = sum(1 for l in todas if l.get("detalle_descargado") and l.get("query_date") is None)
    if args.date:
        licitaciones = [l for l in todas if l.get("query_date") == args.date]
    else:
        licitaciones = todas
        fechas = sorted({l["query_date"] for l in todas if l.get("query_date")})
        if len(fechas) > 1:
            print(f"⚠ La base mezcla varias fechas consultadas ({', '.join(fechas)}). Usa --date.")
    terms = terms_for_query(args.query)
    rows = build_rows(licitaciones, terms)
    write_csv(rows, output)

    print(format_table(rows))
    if args.date:
        print(f"\nFecha consultada (query_date): {args.date}")
        print(f"Licitaciones de esa consulta: {len(licitaciones)}")
        if sin_query_date:
            print(f"⚠ {sin_query_date} licitaciones con detalle no tienen query_date (guardadas antes de "
                  "la migración) y no se incluyen. Vuelve a ejecutar la ingesta de esa fecha.")
    else:
        print(f"\nLicitaciones en la base: {len(licitaciones)}")
    print(f"Candidatas con detalle: {len(rows)}")
    sin_detalle = candidates_without_detail(licitaciones, terms)
    if sin_detalle:
        print(f"Candidatas sin detalle (no incluidas en el CSV): {len(sin_detalle)}")
    print(f"\nCSV generado: {relative(output)}")
    print("Completa las columnas relevante_manual y observacion_manual.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
