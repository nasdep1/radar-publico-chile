"""Tests del ground truth, las métricas y el script de evaluación (sin API)."""

import importlib.util
import json
from pathlib import Path

import pytest
import requests

from src import config
from src.repositories import licitaciones_repository as repo
from src.services.contextual_relevance import SEGURIDAD_MUNICIPAL
from src.services.normalizer import normalize_detail
from src.services.relevance_evaluation import (
    GROUND_TRUTH_FILES,
    ConfusionMatrix,
    GroundTruthError,
    confusion_matrix,
    evaluate,
    format_ratio,
    load_ground_truth,
    outcome,
)
from tests.fixtures import detail_record

GT_PATH = GROUND_TRUTH_FILES["seguridad municipal"]


# Ground truth

def test_ground_truth_22_registros_5_positivos_17_negativos():
    labels = load_ground_truth(GT_PATH)
    assert len(labels) == 22
    assert sum(l.relevante for l in labels.values()) == 5
    assert sum(not l.relevante for l in labels.values()) == 17
    assert all(l.motivo for l in labels.values())


def test_ground_truth_positivos():
    labels = load_ground_truth(GT_PATH)
    assert sorted(c for c, l in labels.items() if l.relevante) == [
        "1134883-5-LE26", "3499-23-LE26", "4063-13-LP26", "4063-9-LP26", "771555-14-LE26",
    ]


def test_ground_truth_baseline_precision_22_7():
    labels = load_ground_truth(GT_PATH)
    baseline = confusion_matrix((True, l.relevante) for l in labels.values())
    assert (baseline.tp, baseline.fp) == (5, 17)
    assert format_ratio(baseline.precision) == "22.7 %"


@pytest.mark.parametrize("contenido, error", [
    ("codigo_externo,relevante\n1,SI\n", "Faltan columnas"),
    ("codigo_externo,relevante,motivo\n1,QUIZAS,x\n", "SI o NO"),
    ("codigo_externo,relevante,motivo\n,SI,x\n", "vacío"),
    ("codigo_externo,relevante,motivo\n1,SI,x\n1,NO,y\n", "duplicado"),
])
def test_ground_truth_invalido(tmp_path, contenido, error):
    path = tmp_path / "gt.csv"
    path.write_text(contenido, encoding="utf-8")
    with pytest.raises(GroundTruthError, match=error):
        load_ground_truth(path)


def test_ground_truth_acepta_si_con_tilde_y_minusculas(tmp_path):
    path = tmp_path / "gt.csv"
    path.write_text("codigo_externo,relevante,motivo\n1,sí,x\n2,no,y\n", encoding="utf-8")
    labels = load_ground_truth(path)
    assert labels["1"].relevante is True and labels["2"].relevante is False


# Métricas

def test_confusion_matrix():
    pairs = [(True, True)] * 4 + [(True, False)] + [(False, False)] * 16 + [(False, True)]
    m = confusion_matrix(pairs)
    assert (m.tp, m.fp, m.tn, m.fn, m.total) == (4, 1, 16, 1, 22)


def test_precision_recall_f1():
    m = ConfusionMatrix(tp=4, fp=1, tn=16, fn=1)
    assert m.precision == pytest.approx(0.8)
    assert m.recall == pytest.approx(0.8)
    assert m.f1 == pytest.approx(0.8)


def test_metricas_indefinidas():
    assert ConfusionMatrix(tn=3, fn=2).precision is None
    assert ConfusionMatrix(tn=3, fp=1).recall is None
    assert ConfusionMatrix(tn=3).f1 is None
    assert ConfusionMatrix(fp=2, fn=1).f1 is None  # precision = recall = 0
    assert format_ratio(None) == "n/d"


@pytest.mark.parametrize("predicho, real, esperado", [
    (True, True, "TP"), (True, False, "FP"), (False, False, "TN"), (False, True, "FN"),
])
def test_outcome(predicho, real, esperado):
    assert outcome(predicho, real) == esperado


# Evaluación con licitaciones sintéticas

def stored(codigo, nombre, organismo, descripcion=""):
    record = detail_record(CodigoExterno=codigo, Nombre=nombre, Descripcion=descripcion,
                           Comprador={"NombreOrganismo": organismo}, Items=None)
    return normalize_detail(record)


SINTETICAS = [
    stored("A", "Sistema de televigilancia comunal", "MUNICIPALIDAD DE EJEMPLO"),
    stored("B", "Cámara para laparoscopía", "HOSPITAL DE EJEMPLO"),
    stored("C", "Servicio de seguridad del parque", "MUNICIPALIDAD DE EJEMPLO"),
    stored("D", "Guardias de seguridad", "INSTITUTO DE PREVISION SOCIAL"),
]


def gt(tmp_path, filas):
    path = tmp_path / "gt.csv"
    path.write_text("codigo_externo,relevante,motivo\n" + "".join(f"{c},{r},m\n" for c, r in filas),
                    encoding="utf-8")
    return load_ground_truth(path)


def test_evaluate(tmp_path):
    labels = gt(tmp_path, [("A", "SI"), ("B", "NO"), ("C", "SI"), ("D", "NO"), ("Z", "SI")])
    report = evaluate(SINTETICAS + [{"codigo_externo": "sin-detalle", "detalle_descargado": 0}],
                      labels, SEGURIDAD_MUNICIPAL)
    assert {c.codigo_externo: c.outcome for c in report.cases} == {"A": "TP", "B": "TN", "C": "FN", "D": "TN"}
    assert (report.matrix.tp, report.matrix.fp, report.matrix.tn, report.matrix.fn) == (1, 0, 2, 1)
    assert (report.baseline.tp, report.baseline.fp) == (2, 2)
    assert report.missing_in_db == ["Z"]
    assert report.unlabeled == []


def test_evaluate_con_threshold_alternativo(tmp_path):
    labels = gt(tmp_path, [("A", "SI"), ("C", "SI")])
    report = evaluate(SINTETICAS, labels, SEGURIDAD_MUNICIPAL, threshold=0)
    assert report.matrix.tp == 2
    assert report.unlabeled == ["B", "D"]


# Script completo

def load_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_relevance.py"
    spec = importlib.util.spec_from_file_location("evaluate_relevance", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def local_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "radar.db")

    def no_api(*args, **kwargs):
        raise AssertionError("evaluate_relevance no debe hacer solicitudes HTTP")

    monkeypatch.setattr(requests.sessions.Session, "request", no_api)
    repo.initialize_database()
    repo.upsert_licitaciones(SINTETICAS)
    return tmp_path


def test_script_muestra_matriz_metricas_y_errores(local_db, capsys):
    path = local_db / "gt.csv"
    path.write_text("codigo_externo,relevante,motivo\nA,SI,ok\nB,NO,médico\nC,SI,parque\nD,NO,ips\n",
                    encoding="utf-8")
    assert load_script().main(["--query", "seguridad municipal", "--ground-truth", str(path)]) == 0
    out = capsys.readouterr().out
    for texto in ("True Positive  (TP): 1", "False Positive (FP): 0", "True Negative  (TN): 2",
                  "False Negative (FN): 1", "Precision", "Recall", "F1", "BASELINE",
                  "FN | CODIGO | SCORE | TITULO", "FN | C |", "FP: ninguno",
                  "pueden representar relicitaciones del mismo proyecto"):
        assert texto in out


def test_script_ground_truth_versionado_sin_datos(local_db, capsys):
    # Las licitaciones sintéticas no están en el ground truth real: nada que evaluar.
    assert load_script().main(["--query", "seguridad municipal"]) == 1
    out = capsys.readouterr().out
    assert "22 etiquetas: 5 relevantes, 17 no relevantes" in out
    assert "Etiquetadas sin detalle en SQLite" in out


def test_script_consulta_sin_perfil(local_db, capsys):
    assert load_script().main(["--query", "aseo"]) == 1
    assert "No existe un perfil" in capsys.readouterr().out


def test_script_sin_base(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "no-existe.db")
    assert load_script().main(["--query", "seguridad municipal"]) == 1
    assert "Ejecuta primero la ingesta" in capsys.readouterr().out
    assert not (tmp_path / "no-existe.db").exists()


def test_resultado_desde_sqlite_es_serializable(local_db):
    report = evaluate(repo.list_licitaciones(solo_con_detalle=True), gt(local_db, [("A", "SI")]),
                      SEGURIDAD_MUNICIPAL)
    data = json.loads(json.dumps(report.cases[0].result.to_dict()))
    assert data["relevant"] is True
