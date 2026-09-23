"""Evalúa el scoring contextual contra el ground truth manual.

Uso (desde la raíz del proyecto):
    python scripts/evaluate_relevance.py --query "seguridad municipal"
    python scripts/evaluate_relevance.py --query "seguridad municipal" --threshold 5

Lee SOLO la base SQLite local y el ground truth versionado; no llama a la API.
Positivo = la licitación está verdaderamente relacionada con la consulta.
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
from src.services.contextual_relevance import format_signals, get_profile  # noqa: E402
from src.services.normalizer import normalize_text  # noqa: E402
from src.services.relevance_evaluation import (  # noqa: E402
    GROUND_TRUTH_FILES,
    evaluate,
    format_ratio,
    load_ground_truth,
)

SEPARADOR = "=" * 60
ADVERTENCIA_RELICITACIONES = (
    "El ground truth contiene procesos que pueden representar relicitaciones del mismo proyecto."
)


def relative(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def short(text, width=60) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= width else text[: width - 1] + "…"


def print_matrix(matrix, title: str) -> None:
    print(f"\n{title}")
    print(f"  {'':28}{'Real: relevante':>18}{'Real: no relevante':>22}")
    print(f"  {'Predicho: relevante':28}{'TP = ' + str(matrix.tp):>18}{'FP = ' + str(matrix.fp):>22}")
    print(f"  {'Predicho: no relevante':28}{'FN = ' + str(matrix.fn):>18}{'TN = ' + str(matrix.tn):>22}")
    print(f"\n  True Positive  (TP): {matrix.tp}")
    print(f"  False Positive (FP): {matrix.fp}")
    print(f"  True Negative  (TN): {matrix.tn}")
    print(f"  False Negative (FN): {matrix.fn}")
    print(f"\n  Precision = TP / (TP + FP) = {format_ratio(matrix.precision)}")
    print(f"  Recall    = TP / (TP + FN) = {format_ratio(matrix.recall)}  (solo sobre candidatas etiquetadas)")
    print(f"  F1                         = {format_ratio(matrix.f1)}")


def print_cases(cases, tag: str) -> None:
    if not cases:
        print(f"\n{tag}: ninguno")
        return
    print(f"\n{tag} | CODIGO | SCORE | TITULO | señales positivas | señales negativas")
    for case in sorted(cases, key=lambda c: -c.result.score):
        r = case.result
        print(f"{tag} | {case.codigo_externo} | {r.score:g} | {short(case.titulo)} | "
              f"{format_signals(r.positive_signals)} | {format_signals(r.negative_signals)}")
        print(f"     etiqueta: {'SI' if case.label.relevante else 'NO'} — {case.label.motivo}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Evalúa el scoring contextual contra el ground truth.")
    parser.add_argument("--query", required=True, help='Consulta, por ejemplo "seguridad municipal".')
    parser.add_argument("--threshold", type=float, help="Umbral alternativo (por defecto, el del perfil).")
    parser.add_argument("--ground-truth", type=Path, help="CSV alternativo (codigo_externo, relevante, motivo).")
    parser.add_argument("--mostrar-todo", action="store_true", help="Muestra también TP y TN con sus señales.")
    args = parser.parse_args(argv)

    profile = get_profile(args.query)
    if profile is None:
        print(f"✗ No existe un perfil de scoring contextual para la consulta {args.query!r}.")
        return 1
    gt_path = args.ground_truth or GROUND_TRUTH_FILES.get(normalize_text(args.query))
    if gt_path is None or not Path(gt_path).exists():
        print(f"✗ No se encontró el ground truth para {args.query!r}. Usa --ground-truth.")
        return 1
    if not config.DATABASE_PATH.exists():
        print(f"✗ No existe la base local {relative(config.DATABASE_PATH)}. Ejecuta primero la ingesta.")
        return 1

    repo.initialize_database()  # aplica migraciones pendientes
    ground_truth = load_ground_truth(gt_path)
    threshold = profile.threshold if args.threshold is None else args.threshold
    report = evaluate(repo.list_licitaciones(solo_con_detalle=True), ground_truth, profile, threshold)

    positivos = sum(1 for label in ground_truth.values() if label.relevante)
    print(SEPARADOR)
    print("RADAR PÚBLICO — EVALUACIÓN DE RELEVANCIA CONTEXTUAL")
    print(SEPARADOR)
    print(f"Consulta: {args.query}")
    print(f"Ground truth: {relative(gt_path)} ({len(ground_truth)} etiquetas: "
          f"{positivos} relevantes, {len(ground_truth) - positivos} no relevantes)")
    print(f"Evaluadas (con detalle en SQLite): {len(report.cases)}")
    if report.missing_in_db:
        print(f"⚠ Etiquetadas sin detalle en SQLite (no evaluadas): {', '.join(report.missing_in_db)}")
    if report.unlabeled:
        print(f"Licitaciones con detalle sin etiqueta (no evaluadas): {len(report.unlabeled)}")
    print(f"Umbral: {threshold:g}" + (" (perfil)" if args.threshold is None else " (--threshold)"))
    print("Positivo = verdaderamente relacionada con la consulta.")

    if not report.cases:
        print("\n✗ No hay licitaciones etiquetadas con detalle en la base.")
        return 1

    print_matrix(report.baseline, "BASELINE — filtro por título (todas las candidatas = relevantes)")
    print_matrix(report.matrix, "SCORING CONTEXTUAL")

    print_cases(report.by_outcome("FP"), "FP")
    print_cases(report.by_outcome("FN"), "FN")
    if args.mostrar_todo:
        print_cases(report.by_outcome("TP"), "TP")
        print_cases(report.by_outcome("TN"), "TN")

    print(f"\n⚠ {ADVERTENCIA_RELICITACIONES}")
    print(f"⚠ Solo {len(report.cases)} ejemplos etiquetados: estas métricas no demuestran precisión general.")
    print("⚠ El recall mostrado es sobre las candidatas del filtro por título, no sobre todo el listado diario.")
    print(SEPARADOR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
