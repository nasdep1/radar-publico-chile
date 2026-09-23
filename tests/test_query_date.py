"""Tests de query_date: migración, ingesta, filtros por fecha y diagnóstico temporal."""

import importlib.util
import json
import sqlite3
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import pytest

from src import config
from src.database import connect, table_columns
from src.repositories import licitaciones_repository as repo
from src.services.date_diagnostics import MENSAJE_DISCREPANCIA, compare_dates, date_part, diagnose
from src.services.ingestion import download_details, fetch_listado
from src.services.normalizer import normalize_detail, normalize_list_item
from tests.fixtures import detail_record, detail_response, list_response

# Esquema de la Etapa 2, antes de existir query_date.
OLD_SCHEMA = """
CREATE TABLE licitaciones (
    codigo_externo TEXT PRIMARY KEY, nombre TEXT, codigo_estado INTEGER, estado TEXT,
    descripcion TEXT, fecha_cierre TEXT, fecha_publicacion TEXT, codigo_organismo TEXT,
    nombre_organismo TEXT, tipo TEXT, moneda TEXT, monto_estimado REAL NULL,
    direccion_entrega TEXT NULL, direccion_visita TEXT NULL, items_json TEXT NULL,
    adjudicacion_json TEXT NULL, raw_json TEXT, detalle_descargado INTEGER DEFAULT 0,
    fecha_captura TEXT, fecha_actualizacion TEXT
);
"""

LISTADO = [
    {"CodigoExterno": "1-1-LE26", "Nombre": "Cámaras de televigilancia", "CodigoEstado": 5,
     "FechaCierre": "2026-10-01T15:00:00"},
    {"CodigoExterno": "1-2-LE26", "Nombre": "Compra de papel", "CodigoEstado": 5,
     "FechaCierre": "2026-09-20T15:00:00"},
]


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.db"
    repo.initialize_database(db_path=path)
    return path


def make_client():
    client = Mock()
    client.get_licitaciones_by_date.return_value = list_response(LISTADO)
    client.get_licitacion_by_code.side_effect = lambda codigo: detail_response(detail_record(CodigoExterno=codigo))
    return client


# Migración

def test_base_nueva_tiene_query_date(db):
    with connect(db) as conn:
        assert "query_date" in table_columns(conn)


def test_migracion_de_base_existente_conserva_datos(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    conn.execute(
        "INSERT INTO licitaciones (codigo_externo, nombre, detalle_descargado, fecha_publicacion) "
        "VALUES ('1-1-LE26', 'Antigua', 1, '2026-08-13T10:00:00')"
    )
    conn.commit()
    conn.close()

    repo.initialize_database(db_path=path)
    repo.initialize_database(db_path=path)  # idempotente

    with connect(path) as conn:
        assert table_columns(conn).count("query_date") == 1
    row = repo.get_licitacion("1-1-LE26", db_path=path)
    assert row["nombre"] == "Antigua"
    assert row["detalle_descargado"] == 1
    assert row["query_date"] is None  # la migración no inventa el valor
    assert row["fecha_publicacion"] == "2026-08-13T10:00:00"


# Ingesta

def test_fetch_listado_asigna_query_date():
    listado = fetch_listado(make_client(), date(2026, 9, 22))
    assert {l["query_date"] for l in listado.licitaciones} == {"2026-09-22"}


def test_query_date_se_guarda_y_no_reemplaza_fecha_publicacion(db):
    client = make_client()
    listado = fetch_listado(client, date(2026, 9, 22))
    repo.upsert_licitaciones(listado.licitaciones, db_path=db)
    download_details(client, listado.licitaciones[:1], db_path=db, sleep=Mock())

    row = repo.get_licitacion("1-1-LE26", db_path=db)
    assert row["detalle_descargado"] == 1
    assert row["query_date"] == "2026-09-22"  # el detalle no la borra
    assert row["fecha_publicacion"] == "2026-09-22T09:00:00"  # viene de Fechas.FechaPublicacion
    assert repo.get_licitacion("1-2-LE26", db_path=db)["query_date"] == "2026-09-22"


def test_reingesta_asigna_query_date_a_detalles_previos_sin_descargarlos(tmp_path):
    """Base previa a la migración: detalle guardado sin query_date."""
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    conn.close()
    repo.initialize_database(db_path=path)
    repo.upsert_licitacion(normalize_detail(detail_record(CodigoExterno="1-1-LE26", Nombre="Detalle")), db_path=path)
    assert repo.get_licitacion("1-1-LE26", db_path=path)["query_date"] is None

    client = make_client()
    listado = fetch_listado(client, date(2026, 9, 22))
    repo.upsert_licitaciones(listado.licitaciones, db_path=path)
    result = download_details(client, listado.licitaciones[:1], db_path=path, sleep=Mock())

    row = repo.get_licitacion("1-1-LE26", db_path=path)
    assert row["query_date"] == "2026-09-22"
    assert row["nombre"] == "Detalle"  # el listado no pisa el detalle
    assert result.desde_cache == ["1-1-LE26"]
    client.get_licitacion_by_code.assert_not_called()


def test_upsert_sin_query_date_conserva_la_existente(db):
    repo.upsert_licitacion({**normalize_list_item(LISTADO[1]), "query_date": "2026-09-22"}, db_path=db)
    repo.upsert_licitacion(normalize_list_item(LISTADO[1]), db_path=db)
    assert repo.get_licitacion("1-2-LE26", db_path=db)["query_date"] == "2026-09-22"


def test_list_licitaciones_por_query_date_excluye_null(db):
    repo.upsert_licitaciones([
        {**normalize_list_item(LISTADO[0]), "query_date": "2026-09-22"},
        {**normalize_list_item(LISTADO[1]), "query_date": "2026-09-21"},
        normalize_list_item({"CodigoExterno": "9-9-L1", "Nombre": "sin fecha"}),
    ], db_path=db)
    assert [r["codigo_externo"] for r in repo.list_licitaciones(db_path=db, query_date="2026-09-22")] == ["1-1-LE26"]
    assert len(repo.list_licitaciones(db_path=db)) == 3


# evaluate_candidates --date

def load_script(name):
    path = Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def local_data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "radar.db")
    repo.initialize_database()
    return tmp_path


def detalle(codigo, nombre, query_date, publicacion="2026-08-13T10:00:00"):
    record = detail_record(CodigoExterno=codigo, Nombre=nombre)
    record["Fechas"] = {**record["Fechas"], "FechaPublicacion": publicacion}
    return {**normalize_detail(record), "query_date": query_date}


def test_evaluate_candidates_filtra_por_query_date(local_data, capsys):
    repo.upsert_licitaciones([
        detalle("1-1-LE26", "Cámaras de televigilancia", "2026-09-22"),
        detalle("1-2-LE26", "Cámaras de seguridad", "2026-09-21"),
        detalle("1-3-LE26", "Alarmas comunitarias", None),
    ])
    script = load_script("evaluate_candidates")
    assert script.main(["--query", "seguridad municipal", "--date", "2026-09-22"]) == 0
    out = capsys.readouterr().out
    assert "1-1-LE26" in out and "1-2-LE26" not in out and "1-3-LE26" not in out
    assert "1 licitaciones con detalle no tienen query_date" in out
    csv_path = local_data / "evaluacion_seguridad_municipal_2026-09-22.csv"
    assert "1-1-LE26" in csv_path.read_text(encoding="utf-8-sig")

    # Sin --date: todas las fechas, con advertencia de mezcla.
    assert script.main(["--query", "seguridad municipal"]) == 0
    out = capsys.readouterr().out
    assert "mezcla varias fechas consultadas" in out
    assert all(c in out for c in ("1-1-LE26", "1-2-LE26", "1-3-LE26"))


def test_evaluate_candidates_fecha_invalida(local_data):
    with pytest.raises(SystemExit):
        load_script("evaluate_candidates").main(["--query", "x", "--date", "22-09-2026"])


# Diagnóstico temporal

@pytest.mark.parametrize("valor, esperado", [
    ("2026-09-22T09:00:00", "2026-09-22"), ("2026-09-22", "2026-09-22"), ("22-09-2026", None),
    ("", None), (None, None), (20260922, None),
])
def test_date_part(valor, esperado):
    assert date_part(valor) == esperado


def test_compare_dates():
    c = compare_dates(["2026-09-22T10:00:00", "2026-08-13T00:00:00", "2026-09-30", None, "x"], "2026-09-22")
    assert (c.igual, c.anterior, c.posterior, c.sin_dato) == (1, 1, 1, 2)
    assert (c.minima, c.maxima) == ("2026-08-13", "2026-09-30")


def test_diagnose_detecta_discrepancia():
    rows = [
        detalle("1-1-LE26", "A", "2026-09-22", publicacion="2026-09-22T09:00:00"),
        detalle("1-2-LE26", "B", "2026-09-22", publicacion="2026-08-13T09:00:00"),
        detalle("1-3-LE26", "C", "2026-09-22", publicacion="2026-09-02T09:00:00"),
    ]
    d = diagnose(rows, "2026-09-22")
    assert (d.publicacion.igual, d.publicacion.anterior) == (1, 2)
    assert (d.publicacion.minima, d.publicacion.maxima) == ("2026-08-13", "2026-09-22")
    assert d.creacion.anterior == 3  # FechaCreacion del fixture: 2026-09-20
    assert d.hay_discrepancia
    assert d.conclusion() == MENSAJE_DISCREPANCIA.format(fecha="2026-09-22")
    assert "requiere validación adicional" in d.conclusion()


def test_diagnose_sin_discrepancia_no_afirma_semantica():
    d = diagnose([detalle("1-1-LE26", "A", "2026-09-22", publicacion="2026-09-22T09:00:00")], "2026-09-22")
    assert not d.hay_discrepancia
    assert "requiriendo validación" in d.conclusion()


def test_diagnose_tolera_raw_json_invalido():
    d = diagnose([{"codigo_externo": "x", "detalle_descargado": 1, "raw_json": "{no json"}], "2026-09-22")
    assert d.rows[0].fecha_creacion is None
    assert d.publicacion.sin_dato == 1


def test_script_diagnostico(local_data, capsys):
    repo.upsert_licitaciones([
        detalle("1-1-LE26", "A", "2026-09-22", publicacion="2026-09-22T09:00:00"),
        detalle("1-2-LE26", "B", "2026-09-22", publicacion="2026-08-13T09:00:00"),
        detalle("1-3-LE26", "C", None, publicacion="2026-09-03T09:00:00"),
        {**normalize_list_item({**LISTADO[1], "CodigoExterno": "1-4-LE26"}), "query_date": "2026-09-22"},
    ])
    script = load_script("diagnose_date_semantics")
    assert script.main(["--query-date", "2026-09-22"]) == 0
    out = capsys.readouterr().out
    for texto in ("CODIGO", "FECHA CONSULTADA", "FECHA PUBLICACION", "FECHA CREACION", "FECHA CIERRE",
                  "ESTADO", "Registros con detalle analizados: 2", "1 registros con detalle no tienen query_date",
                  "Listado completo con query_date 2026-09-22 (3 registros",
                  MENSAJE_DISCREPANCIA.format(fecha="2026-09-22")):
        assert texto in out
    assert "1-3-LE26" not in out

    assert script.main(["--query-date", "2026-09-22", "--incluir-sin-query-date"]) == 0
    out = capsys.readouterr().out
    assert "Registros con detalle analizados: 3" in out
    assert "(desconocida)" in out


def test_script_diagnostico_sin_registros(local_data, capsys):
    assert load_script("diagnose_date_semantics").main(["--query-date", "2026-09-22"]) == 1
    assert "No hay registros con detalle" in capsys.readouterr().out


def test_script_diagnostico_no_llama_a_la_api(local_data, monkeypatch):
    import requests

    def no_api(*args, **kwargs):
        raise AssertionError("no debe hacer solicitudes HTTP")

    monkeypatch.setattr(requests.sessions.Session, "request", no_api)
    repo.upsert_licitaciones([detalle("1-1-LE26", "A", "2026-09-22")])
    assert load_script("diagnose_date_semantics").main(["--query-date", "2026-09-22"]) == 0
