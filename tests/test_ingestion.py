"""Tests de la ingesta y del caché, con cliente simulado (sin API real)."""

import importlib.util
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import pytest

from src import config
from src.repositories import licitaciones_repository as repo
from src.services.candidate_filter import filter_candidates
from src.services.ingestion import download_details, fetch_listado
from src.sources.mercado_publico import MercadoPublicoHTTPError
from tests.fixtures import detail_record, detail_response, list_response

LISTADO = [
    {"CodigoExterno": "1-1-LE26", "Nombre": "ADQUISICIÓN DE CÁMARAS DE TELEVIGILANCIA", "CodigoEstado": 5, "FechaCierre": None},
    {"CodigoExterno": "1-2-LE26", "Nombre": "Compra de papel", "CodigoEstado": 5, "FechaCierre": None},
    {"CodigoExterno": "1-3-LE26", "Nombre": "Servicio de patrullaje", "CodigoEstado": 5, "FechaCierre": None},
    {"Nombre": "sin código"},
]
TERMS = ["camaras", "patrullaje"]


def make_client():
    client = Mock()
    client.get_licitaciones_by_date.return_value = list_response(LISTADO)
    client.get_licitacion_by_code.side_effect = (
        lambda codigo: detail_response(detail_record(CodigoExterno=codigo, Nombre=f"Detalle {codigo}"))
    )
    return client


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.db"
    repo.initialize_database(db_path=path)
    return path


def run_ingest(client, db, sleep):
    listado = fetch_listado(client, date(2026, 9, 22))
    candidatas = filter_candidates(listado.licitaciones, TERMS).candidatas
    repo.upsert_licitaciones(listado.licitaciones, db_path=db)
    return listado, download_details(client, candidatas, db_path=db, pause_seconds=3, sleep=sleep)


def test_fetch_listado_normaliza_y_omite_invalidos():
    client = make_client()
    result = fetch_listado(client, date(2026, 9, 22))
    client.get_licitaciones_by_date.assert_called_once_with(date(2026, 9, 22))
    assert result.total_recibidas == 4
    assert result.cantidad_reportada == 4
    assert result.omitidas == 1
    assert [l["codigo_externo"] for l in result.licitaciones] == ["1-1-LE26", "1-2-LE26", "1-3-LE26"]


def test_solo_se_descarga_el_detalle_de_candidatas(db):
    client, sleep = make_client(), Mock()
    _, result = run_ingest(client, db, sleep)
    assert result.desde_api == ["1-1-LE26", "1-3-LE26"]
    assert result.desde_cache == []
    assert [c.args[0] for c in client.get_licitacion_by_code.call_args_list] == ["1-1-LE26", "1-3-LE26"]
    assert [c.args[0] for c in sleep.call_args_list] == [3, 3]  # pausa antes de cada consulta
    assert repo.count_licitaciones(db_path=db) == 3
    assert repo.count_licitaciones(db_path=db, solo_con_detalle=True) == 2
    assert repo.get_licitacion("1-2-LE26", db_path=db)["detalle_descargado"] == 0


def test_cache_segunda_ejecucion_no_llama_a_la_api(db):
    run_ingest(make_client(), db, Mock())

    client, sleep = make_client(), Mock()
    _, result = run_ingest(client, db, sleep)
    client.get_licitacion_by_code.assert_not_called()
    sleep.assert_not_called()
    assert result.desde_api == []
    assert result.desde_cache == ["1-1-LE26", "1-3-LE26"]
    # Reingestar el listado no borra el detalle guardado
    assert repo.get_licitacion("1-1-LE26", db_path=db)["nombre"] == "Detalle 1-1-LE26"
    assert repo.count_licitaciones(db_path=db, solo_con_detalle=True) == 2


def test_log_cache_y_api(db):
    repo.upsert_licitacion(
        {"codigo_externo": "1-1-LE26", "detalle_descargado": 1, "nombre": "ya descargada"}, db_path=db
    )
    log = []
    candidatas = [{"codigo_externo": "1-1-LE26"}, {"codigo_externo": "1-3-LE26"}]
    download_details(make_client(), candidatas, db_path=db, sleep=Mock(), log=log.append)
    assert log == ["[cache] 1-1-LE26", "[API] 1-3-LE26"]


def test_error_en_una_candidata_no_detiene_el_resto(db):
    client = make_client()
    ok = client.get_licitacion_by_code.side_effect
    client.get_licitacion_by_code.side_effect = [
        MercadoPublicoHTTPError("Mercado Público respondió HTTP 500.", status_code=500),
        ok("1-3-LE26"),
    ]
    candidatas = [{"codigo_externo": "1-1-LE26"}, {"codigo_externo": "1-3-LE26"}]
    result = download_details(client, candidatas, db_path=db, sleep=Mock())
    assert result.errores == [("1-1-LE26", "Mercado Público respondió HTTP 500.")]
    assert result.desde_api == ["1-3-LE26"]
    assert repo.licitacion_has_detail("1-1-LE26", db_path=db) is False


def test_detalle_vacio_o_de_otro_codigo_es_error(db):
    client = Mock()
    client.get_licitacion_by_code.side_effect = [
        {"Cantidad": 0, "Listado": []},
        detail_response(detail_record(CodigoExterno="otro")),
    ]
    candidatas = [{"codigo_externo": "1-1-LE26"}, {"codigo_externo": "1-3-LE26"}]
    result = download_details(client, candidatas, db_path=db, sleep=Mock())
    assert [codigo for codigo, _ in result.errores] == ["1-1-LE26", "1-3-LE26"]
    assert repo.count_licitaciones(db_path=db, solo_con_detalle=True) == 0


# Script completo, con cliente simulado y base temporal

def load_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "ingest_mercado_publico.py"
    spec = importlib.util.spec_from_file_location("ingest_mercado_publico", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_script_dos_ejecuciones_usa_cache(tmp_path, monkeypatch, capsys):
    script = load_script()
    client = make_client()
    monkeypatch.setattr(script, "MercadoPublicoClient", lambda: client)
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "radar.db")
    monkeypatch.setattr(config, "DETAIL_REQUEST_PAUSE", 0)
    args = ["--date", "2026-09-22", "--query", "seguridad municipal"]

    assert script.main(args) == 0
    primera = capsys.readouterr().out
    assert "Licitaciones del día: 3" in primera
    assert "Candidatas por título: 2" in primera
    assert "[API] 1-1-LE26" in primera
    assert "Diagnóstico de Items (1-1-LE26)" in primera
    assert "Detalles desde API: 2" in primera

    assert script.main(args) == 0
    segunda = capsys.readouterr().out
    assert "[cache] 1-1-LE26" in segunda
    assert "Detalles desde API: 0" in segunda
    assert "Detalles desde caché: 2" in segunda
    client.get_licitaciones_by_date.assert_called_with(date(2026, 9, 22))
    assert client.get_licitacion_by_code.call_count == 2


def test_script_expansion_solo_para_caso_de_prueba():
    script = load_script()
    assert "cctv" in script.terms_for_query("Seguridad Municipal")
    assert script.terms_for_query("aseo") == ["aseo"]
