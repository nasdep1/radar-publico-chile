"""Reporte CSV para evaluar manualmente las candidatas de una consulta.

Uso (desde la raíz del proyecto):
    python scripts/evaluate_candidates.py --query "seguridad municipal"

Lee EXCLUSIVAMENTE la base SQLite local (data/radar_publico.db). No realiza
ninguna llamada a Mercado Público. Selecciona las candidatas con el mismo
filtro por Nombre y los mismos términos que usa la ingesta.
"""

import argparse
import sys
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Reporte de evaluación manual de candidatas.")
    parser.add_argument("--query", required=True, help='Consulta, por ejemplo "seguridad municipal".')
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

    output = config.DATA_DIR / f"evaluacion_{query_slug(args.query)}.csv"
    if output.exists() and not args.sobrescribir:
        print(f"✗ {relative(output)} ya existe y podría tener evaluaciones manuales.")
        print("  Renómbralo o vuelve a ejecutar con --sobrescribir.")
        return 1

    licitaciones = repo.list_licitaciones(db_path=db_path)
    terms = terms_for_query(args.query)
    rows = build_rows(licitaciones, terms)
    write_csv(rows, output)

    print(format_table(rows))
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
