"""Tests del reporte de evaluación (solo SQLite local, sin API)."""

import csv
import importlib.util
import json
from pathlib import Path

import pytest
import requests

from src import config
from src.repositories import licitaciones_repository as repo
from src.services.candidate_filter import filter_candidates
from src.services.evaluation import (
    CSV_COLUMNS,
    build_rows,
    candidates_without_detail,
    extract_items,
    format_monto,
    format_table,
    query_slug,
    summarize_items,
    write_csv,
)
from src.services.normalizer import normalize_detail, normalize_list_item
from src.services.query_terms import terms_for_query
from tests.fixtures import DETAIL_RECORD, detail_record

TERMS = terms_for_query("seguridad municipal")


# Items

def test_extract_items_estructura_real():
    items = extract_items(json.dumps(DETAIL_RECORD["Items"]))
    assert [i["Correlativo"] for i in items] == [1, 2]


@pytest.mark.parametrize(
    "items_json",
    [None, "", "no es json", "[]", "{}", '{"Cantidad": 0, "Listado": null}', '{"Listado": "x"}'],
)
def test_extract_items_tolera_valores_invalidos(items_json):
    assert extract_items(items_json) == []


def test_extract_items_descarta_elementos_que_no_son_objetos():
    assert extract_items('{"Listado": [{"NombreProducto": "A"}, "x", null]}') == [{"NombreProducto": "A"}]


def test_summarize_items():
    assert summarize_items(json.dumps(DETAIL_RECORD["Items"])) == {
        "items_nombres": "Cámaras de seguridad | Grabador de video en red",
        "items_descripciones": "Cámara IP domo 4K | NVR 32 canales",
        # Categoría repetida: aparece una sola vez
        "categorias": "Equipos de seguridad y control / Cámaras de vigilancia",
    }


def test_summarize_items_omite_vacios_y_conserva_orden_de_categorias():
    items = {"Listado": [
        {"NombreProducto": "A", "Descripcion": None, "Categoria": "C2"},
        {"NombreProducto": "  ", "Descripcion": "d", "Categoria": "C1"},
        {"NombreProducto": "B", "Categoria": "C2"},
    ]}
    assert summarize_items(json.dumps(items)) == {
        "items_nombres": "A | B",
        "items_descripciones": "d",
        "categorias": "C2 | C1",
    }


def test_summarize_items_sin_items():
    assert summarize_items(None) == {"items_nombres": "", "items_descripciones": "", "categorias": ""}


# Filas del reporte

def stored(record):
    """Licitación tal como la devuelve SQLite después de guardar el detalle."""
    return {**normalize_detail(record), "fecha_captura": "x", "fecha_actualizacion": "x"}


def test_build_rows():
    rows = build_rows([stored(DETAIL_RECORD)], TERMS)
    assert len(rows) == 1
    row = rows[0]
    assert list(row) == list(CSV_COLUMNS)
    assert row["codigo_externo"] == "1019-102-LE26"
    assert row["nombre_organismo"] == "I MUNICIPALIDAD DE EJEMPLO"
    assert row["estado"] == "Publicada"
    assert row["fecha_publicacion"] == "2026-09-22T09:00:00"
    assert row["monto_estimado"] == "15000000"
    assert row["direccion_entrega"] == "Plaza de Armas 1"
    assert row["items_nombres"] == "Cámaras de seguridad | Grabador de video en red"
    assert row["terminos_coincidentes"] == "camara | camaras | televigilancia"
    assert row["relevante_manual"] == ""
    assert row["observacion_manual"] == ""


def test_build_rows_nulos_como_vacio():
    rows = build_rows([stored(detail_record(MontoEstimado=None, Comprador=None, Items=None))], TERMS)
    assert rows[0]["monto_estimado"] == ""
    assert rows[0]["nombre_organismo"] == ""
    assert rows[0]["items_nombres"] == ""


def test_build_rows_excluye_sin_detalle_y_no_candidatas():
    licitaciones = [
        stored(DETAIL_RECORD),
        stored(detail_record(CodigoExterno="2-2-L1", Nombre="Compra de papel")),
        normalize_list_item({"CodigoExterno": "3-3-L1", "Nombre": "Cámaras sin detalle"}),
    ]
    assert [r["codigo_externo"] for r in build_rows(licitaciones, TERMS)] == ["1019-102-LE26"]
    assert candidates_without_detail(licitaciones, TERMS) == ["3-3-L1"]


def test_seleccion_igual_al_filtro_de_la_ingesta():
    nombres = [
        "ADQUISICIÓN DE CÁMARAS DE TELEVIGILANCIA",
        "Servicio de patrullaje preventivo",
        "Plan comunal de PREVENCIÓN DEL DELITO",
        "Compra de papel",
        "Inseguridad alimentaria",  # "seguridad" no está al inicio de palabra
        "Sistema de alarmas comunitarias",
        "Mantención de áreas verdes",
    ]
    listado = [normalize_list_item({"CodigoExterno": f"1-{i}-L1", "Nombre": n}) for i, n in enumerate(nombres)]
    esperados = [c["codigo_externo"] for c in filter_candidates(listado, TERMS).candidatas]

    detalles = [stored(detail_record(CodigoExterno=l["codigo_externo"], Nombre=l["nombre"])) for l in listado]
    assert [r["codigo_externo"] for r in build_rows(detalles, TERMS)] == esperados
    assert esperados == ["1-0-L1", "1-1-L1", "1-2-L1", "1-5-L1"]


@pytest.mark.parametrize("valor, esperado", [(None, ""), (15000000.0, "15000000"), (1500.5, "1500.5")])
def test_format_monto(valor, esperado):
    assert format_monto(valor) == esperado


@pytest.mark.parametrize(
    "query, esperado",
    [("seguridad municipal", "seguridad_municipal"), ("  Prevención del Delito ", "prevencion_del_delito"), ("¿?", "consulta")],
)
def test_query_slug(query, esperado):
    assert query_slug(query) == esperado


def test_terms_for_query_normaliza_la_consulta():
    assert terms_for_query("  Seguridad   MUNICIPAL ") == TERMS
    assert terms_for_query("aseo") == ["aseo"]


# CSV y tabla

def test_write_csv_roundtrip(tmp_path):
    row = {column: "" for column in CSV_COLUMNS}
    row.update(codigo_externo="1-1-L1", nombre='Cámaras, "CCTV"', descripcion="línea 1\nlínea 2")
    path = tmp_path / "out.csv"
    write_csv([row], path)
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")  # BOM UTF-8
    with open(path, newline="", encoding="utf-8-sig") as handle:
        leidas = list(csv.DictReader(handle))
    assert leidas == [row]


def test_write_csv_sin_filas_escribe_encabezado(tmp_path):
    path = tmp_path / "out.csv"
    write_csv([], path)
    assert path.read_text(encoding="utf-8-sig").strip() == ",".join(CSV_COLUMNS)


def test_format_table():
    table = format_table(build_rows([stored(DETAIL_RECORD)], TERMS))
    lines = table.splitlines()
    assert lines[0].split(" | ")[0].strip() == "CODIGO"
    assert "TERMINOS COINCIDENTES" in lines[0]
    assert lines[2].startswith("1019-102-LE26")
    assert lines[2].endswith("camara | camaras | televigilancia")


# Script completo

def load_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_candidates.py"
    spec = importlib.util.spec_from_file_location("evaluate_candidates", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def local_data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "radar.db")

    def no_api(*args, **kwargs):
        raise AssertionError("evaluate_candidates no debe hacer solicitudes HTTP")

    monkeypatch.setattr(requests.sessions.Session, "request", no_api)
    return tmp_path


def test_script_genera_csv_sin_llamar_a_la_api(local_data, capsys):
    repo.initialize_database()
    repo.upsert_licitaciones([
        normalize_detail(DETAIL_RECORD),
        normalize_list_item({"CodigoExterno": "2-2-L1", "Nombre": "Compra de papel"}),
        normalize_list_item({"CodigoExterno": "3-3-L1", "Nombre": "Alarmas sin detalle"}),
    ])
    assert load_script().main(["--query", "seguridad municipal"]) == 0

    out = capsys.readouterr().out
    assert "CODIGO" in out and "TERMINOS COINCIDENTES" in out
    assert "1019-102-LE26" in out
    assert "Candidatas con detalle: 1" in out
    assert "Candidatas sin detalle (no incluidas en el CSV): 1" in out

    with open(local_data / "evaluacion_seguridad_municipal.csv", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert [r["codigo_externo"] for r in rows] == ["1019-102-LE26"]
    assert rows[0]["categorias"] == "Equipos de seguridad y control / Cámaras de vigilancia"


def test_script_no_sobrescribe_evaluacion_existente(local_data, capsys):
    repo.initialize_database()
    csv_path = local_data / "evaluacion_seguridad_municipal.csv"
    csv_path.write_text("evaluación manual", encoding="utf-8")
    script = load_script()

    assert script.main(["--query", "seguridad municipal"]) == 1
    assert csv_path.read_text(encoding="utf-8") == "evaluación manual"
    assert "--sobrescribir" in capsys.readouterr().out

    assert script.main(["--query", "seguridad municipal", "--sobrescribir"]) == 0
    assert csv_path.read_text(encoding="utf-8-sig").startswith("codigo_externo,")


def test_script_sin_base(local_data, capsys):
    assert load_script().main(["--query", "seguridad municipal"]) == 1
    assert "Ejecuta primero la ingesta" in capsys.readouterr().out
    assert not (local_data / "radar.db").exists()
