"""Evaluación del scoring contextual contra un ground truth etiquetado a mano.

Positivo = la licitación está verdaderamente relacionada con la consulta
(por ejemplo, seguridad pública municipal).

Las métricas solo describen el conjunto etiquetado (las candidatas que pasaron
el filtro por título). No miden el recall global sobre todo el listado diario.
"""

import csv
from dataclasses import dataclass, field
from pathlib import Path

from src.services.contextual_relevance import score_licitacion

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Ground truth versionado por consulta (normalizada).
GROUND_TRUTH_FILES = {
    "seguridad municipal": PROJECT_ROOT / "tests" / "data" / "ground_truth_seguridad_municipal.csv",
}

_LABELS = {"SI": True, "SÍ": True, "NO": False}


class GroundTruthError(ValueError):
    """Archivo de ground truth con formato inválido."""


@dataclass
class GroundTruthLabel:
    codigo_externo: str
    relevante: bool
    motivo: str = ""


def load_ground_truth(path) -> dict:
    """Lee un CSV con columnas codigo_externo, relevante (SI/NO) y motivo."""
    labels = {}
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = {"codigo_externo", "relevante", "motivo"} - set(reader.fieldnames or ())
        if missing:
            raise GroundTruthError(f"Faltan columnas en el ground truth: {sorted(missing)}")
        for line, row in enumerate(reader, start=2):
            codigo = (row["codigo_externo"] or "").strip()
            etiqueta = (row["relevante"] or "").strip().upper()
            if not codigo:
                raise GroundTruthError(f"Línea {line}: codigo_externo vacío.")
            if etiqueta not in _LABELS:
                raise GroundTruthError(f"Línea {line}: relevante debe ser SI o NO (se leyó {etiqueta!r}).")
            if codigo in labels:
                raise GroundTruthError(f"Línea {line}: código duplicado {codigo}.")
            labels[codigo] = GroundTruthLabel(codigo, _LABELS[etiqueta], (row["motivo"] or "").strip())
    return labels


@dataclass
class ConfusionMatrix:
    tp: int = 0  # predicho relevante, realmente relevante
    fp: int = 0  # predicho relevante, realmente no relevante
    tn: int = 0  # predicho no relevante, realmente no relevante
    fn: int = 0  # predicho no relevante, realmente relevante

    @property
    def total(self) -> int:
        return self.tp + self.fp + self.tn + self.fn

    @property
    def precision(self):
        """TP / (TP + FP); None si no hay predicciones positivas."""
        denominator = self.tp + self.fp
        return self.tp / denominator if denominator else None

    @property
    def recall(self):
        """TP / (TP + FN); None si no hay positivos reales."""
        denominator = self.tp + self.fn
        return self.tp / denominator if denominator else None

    @property
    def f1(self):
        p, r = self.precision, self.recall
        if p is None or r is None or p + r == 0:
            return None
        return 2 * p * r / (p + r)


def confusion_matrix(pairs) -> ConfusionMatrix:
    """`pairs`: iterable de (predicho: bool, real: bool)."""
    matrix = ConfusionMatrix()
    for predicted, actual in pairs:
        if predicted and actual:
            matrix.tp += 1
        elif predicted:
            matrix.fp += 1
        elif actual:
            matrix.fn += 1
        else:
            matrix.tn += 1
    return matrix


def outcome(predicted: bool, actual: bool) -> str:
    if predicted:
        return "TP" if actual else "FP"
    return "FN" if actual else "TN"


@dataclass
class EvaluatedCase:
    codigo_externo: str
    titulo: str
    label: GroundTruthLabel
    result: object  # RelevanceResult
    outcome: str


@dataclass
class EvaluationReport:
    cases: list = field(default_factory=list)
    matrix: ConfusionMatrix = field(default_factory=ConfusionMatrix)
    baseline: ConfusionMatrix = field(default_factory=ConfusionMatrix)
    missing_in_db: list = field(default_factory=list)  # etiquetados sin detalle en SQLite
    unlabeled: list = field(default_factory=list)  # con detalle pero sin etiqueta

    def by_outcome(self, name: str) -> list:
        return [c for c in self.cases if c.outcome == name]


def evaluate(licitaciones, ground_truth: dict, profile, threshold=None) -> EvaluationReport:
    """Aplica el scorer a las licitaciones etiquetadas y compara con las etiquetas.

    El baseline es el filtro por título: considera relevantes a todas las
    candidatas etiquetadas.
    """
    by_code = {l["codigo_externo"]: l for l in licitaciones if l.get("detalle_descargado")}
    report = EvaluationReport()
    for codigo, label in sorted(ground_truth.items()):
        licitacion = by_code.get(codigo)
        if licitacion is None:
            report.missing_in_db.append(codigo)
            continue
        result = score_licitacion(licitacion, profile, threshold=threshold)
        report.cases.append(EvaluatedCase(
            codigo, licitacion.get("nombre") or "", label, result, outcome(result.relevant, label.relevante)
        ))
    report.unlabeled = sorted(set(by_code) - set(ground_truth))
    report.matrix = confusion_matrix((c.result.relevant, c.label.relevante) for c in report.cases)
    report.baseline = confusion_matrix((True, c.label.relevante) for c in report.cases)
    return report


def format_ratio(value) -> str:
    return "n/d" if value is None else f"{value * 100:.1f} %"
