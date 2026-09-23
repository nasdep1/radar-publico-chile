"""Diagnóstico temporal: ¿qué significa la fecha enviada al listado de Mercado Público?

Uso (desde la raíz del proyecto):
    python scripts/diagnose_date_semantics.py --query-date 2026-09-22

No hace llamadas a la API: trabaja sobre los registros ya guardados en SQLite.
Compara `query_date` (fecha enviada al endpoint) con FechaPublicacion,
FechaCreacion y FechaCierre de cada proceso. No asume la semántica del parámetro.
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
from src.services.date_diagnostics import compare_dates, diagnose  # noqa: E402

SEPARADOR = "=" * 60


def parse_date(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError(f"Fecha inválida: {value!r}. Usa YYYY-MM-DD.") from None


def relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def cell(value, width: int) -> str:
    text = "-" if value in (None, "") else str(value)
    return (text if len(text) <= width else text[: width - 1] + "…").ljust(width)


def print_comparison(title: str, comparison, query_date: str) -> None:
    print(f"\n{title}:")
    print(f"  igual a {query_date}: {comparison.igual}")
    print(f"  anterior:          {comparison.anterior}")
    print(f"  posterior:         {comparison.posterior}")
    print(f"  sin dato:          {comparison.sin_dato}")
    print(f"  mínima:            {comparison.minima or '-'}")
    print(f"  máxima:            {comparison.maxima or '-'}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Diagnóstico de la fecha usada en el listado.")
    parser.add_argument("--query-date", type=parse_date, required=True, help="Fecha consultada YYYY-MM-DD.")
    parser.add_argument(
        "--incluir-sin-query-date",
        action="store_true",
        help="Incluye registros con detalle guardados antes de existir query_date (fecha consultada desconocida).",
    )
    args = parser.parse_args(argv)
    query_date = args.query_date

    if not config.DATABASE_PATH.exists():
        print(f"✗ No existe la base local {relative(config.DATABASE_PATH)}. Ejecuta primero la ingesta.")
        return 1
    repo.initialize_database()  # aplica migraciones pendientes

    con_detalle = repo.list_licitaciones(solo_con_detalle=True)
    muestra = [l for l in con_detalle if l.get("query_date") == query_date]
    sin_query_date = [l for l in con_detalle if l.get("query_date") is None]
    if args.incluir_sin_query_date:
        muestra += sin_query_date

    print(SEPARADOR)
    print("RADAR PÚBLICO — DIAGNÓSTICO TEMPORAL")
    print(SEPARADOR)
    print(f"Fecha consultada (query_date): {query_date}")
    print(f"Registros con detalle analizados: {len(muestra)}")
    if sin_query_date and not args.incluir_sin_query_date:
        print(f"⚠ {len(sin_query_date)} registros con detalle no tienen query_date (guardados antes de "
              "la migración). Vuelve a ejecutar la ingesta de esa fecha o usa --incluir-sin-query-date.")
    if not muestra:
        print("\n✗ No hay registros con detalle para esa fecha consultada.")
        return 1

    diagnosis = diagnose(muestra, query_date)
    widths = (18, 16, 19, 19, 19, 12)
    headers = ("CODIGO", "FECHA CONSULTADA", "FECHA PUBLICACION", "FECHA CREACION", "FECHA CIERRE", "ESTADO")
    print("\n" + " | ".join(cell(h, w) for h, w in zip(headers, widths)))
    print("-" * (sum(widths) + 3 * (len(widths) - 1)))
    for row in sorted(diagnosis.rows, key=lambda r: (r.fecha_publicacion or "", r.codigo_externo)):
        values = (
            row.codigo_externo,
            row.query_date or "(desconocida)",
            row.fecha_publicacion,
            row.fecha_creacion,
            row.fecha_cierre,
            row.estado,
        )
        print(" | ".join(cell(v, w) for v, w in zip(values, widths)))

    print_comparison("FechaPublicacion vs fecha consultada", diagnosis.publicacion, query_date)
    print_comparison("FechaCreacion vs fecha consultada", diagnosis.creacion, query_date)
    print_comparison("FechaCierre vs fecha consultada", diagnosis.cierre, query_date)

    # Listado completo de esa consulta: solo trae FechaCierre (sin FechaPublicacion).
    listado = repo.list_licitaciones(query_date=query_date)
    if listado:
        cierre = compare_dates((l.get("fecha_cierre") for l in listado), query_date)
        print_comparison(
            f"Listado completo con query_date {query_date} ({len(listado)} registros; "
            "solo FechaCierre disponible sin detalle)", cierre, query_date,
        )

    print("\nNota: la muestra con detalle son solo las candidatas del filtro por título; "
          "no representa todo el listado.")
    print(f"\nCONCLUSIÓN: {diagnosis.conclusion()}")
    print(SEPARADOR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
