import json

import pytest

from src.repositories import licitaciones_repository as repo
from src.services.normalizer import normalize_detail, normalize_list_item
from tests.fixtures import DETAIL_RECORD, LIST_ITEM, detail_record


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.db"
    repo.initialize_database(db_path=path)
    return path


def test_initialize_database_es_idempotente(db):
    repo.initialize_database(db_path=db)
    assert repo.count_licitaciones(db_path=db) == 0


def test_upsert_basico_y_get(db):
    repo.upsert_licitacion(normalize_list_item(LIST_ITEM), db_path=db)
    row = repo.get_licitacion("1019-102-LE26", db_path=db)
    assert row["nombre"] == LIST_ITEM["Nombre"]
    assert row["codigo_estado"] == 5
    assert row["detalle_descargado"] == 0
    assert row["descripcion"] is None
    assert row["fecha_captura"] and row["fecha_actualizacion"]
    assert json.loads(row["raw_json"]) == LIST_ITEM


def test_get_licitacion_inexistente(db):
    assert repo.get_licitacion("no-existe", db_path=db) is None


def test_upsert_actualiza_sin_duplicar(db):
    repo.upsert_licitacion(normalize_list_item(LIST_ITEM), db_path=db)
    repo.upsert_licitacion(normalize_list_item({**LIST_ITEM, "CodigoEstado": 6}), db_path=db)
    assert repo.count_licitaciones(db_path=db) == 1
    assert repo.get_licitacion("1019-102-LE26", db_path=db)["codigo_estado"] == 6


def test_upsert_detalle_reemplaza_basico(db):
    repo.upsert_licitacion(normalize_list_item(LIST_ITEM), db_path=db)
    captura = repo.get_licitacion("1019-102-LE26", db_path=db)["fecha_captura"]
    repo.upsert_licitacion(normalize_detail(DETAIL_RECORD), db_path=db)
    row = repo.get_licitacion("1019-102-LE26", db_path=db)
    assert row["detalle_descargado"] == 1
    assert row["nombre_organismo"] == "I MUNICIPALIDAD DE EJEMPLO"
    assert row["monto_estimado"] == 15000000.0
    assert json.loads(row["raw_json"]) == DETAIL_RECORD
    assert row["fecha_captura"] == captura  # se conserva la primera captura


def test_upsert_basico_no_pisa_detalle(db):
    repo.upsert_licitacion(normalize_detail(DETAIL_RECORD), db_path=db)
    repo.upsert_licitacion(normalize_list_item({**LIST_ITEM, "Nombre": "otro"}), db_path=db)
    row = repo.get_licitacion("1019-102-LE26", db_path=db)
    assert row["detalle_descargado"] == 1
    assert row["nombre"] == DETAIL_RECORD["Nombre"]
    assert json.loads(row["raw_json"]) == DETAIL_RECORD


def test_monto_null_se_guarda_como_null(db):
    repo.upsert_licitacion(normalize_detail(detail_record(MontoEstimado="no informado")), db_path=db)
    assert repo.get_licitacion("1019-102-LE26", db_path=db)["monto_estimado"] is None


def test_licitacion_has_detail(db):
    assert repo.licitacion_has_detail("1019-102-LE26", db_path=db) is False
    repo.upsert_licitacion(normalize_list_item(LIST_ITEM), db_path=db)
    assert repo.licitacion_has_detail("1019-102-LE26", db_path=db) is False
    repo.upsert_licitacion(normalize_detail(DETAIL_RECORD), db_path=db)
    assert repo.licitacion_has_detail("1019-102-LE26", db_path=db) is True


def test_upsert_sin_codigo_falla(db):
    with pytest.raises(ValueError):
        repo.upsert_licitacion({"nombre": "sin código"}, db_path=db)


def test_upsert_licitaciones_lote(db):
    rows = [normalize_list_item({"CodigoExterno": f"1-{i}-L1", "Nombre": f"N{i}"}) for i in range(5)]
    assert repo.upsert_licitaciones(rows, db_path=db) == 5
    assert repo.count_licitaciones(db_path=db) == 5
    assert repo.count_licitaciones(db_path=db, solo_con_detalle=True) == 0


def test_search_by_text_sin_tildes_ni_mayusculas(db):
    repo.upsert_licitacion(normalize_detail(DETAIL_RECORD), db_path=db)
    repo.upsert_licitacion(normalize_list_item({"CodigoExterno": "2-2-L1", "Nombre": "Compra de papel"}), db_path=db)
    assert [r["codigo_externo"] for r in repo.search_by_text("camaras", db_path=db)] == ["1019-102-LE26"]
    # Coincidencia en la descripción
    assert len(repo.search_by_text("PREVENCION DEL DELITO", db_path=db)) == 1
    assert repo.search_by_text("inexistente", db_path=db) == []
    assert repo.search_by_text("   ", db_path=db) == []


def test_search_by_text_es_parametrizado(db):
    repo.upsert_licitacion(normalize_list_item({"CodigoExterno": "1-1-L1", "Nombre": "100% seguro"}), db_path=db)
    repo.upsert_licitacion(normalize_list_item({"CodigoExterno": "1-2-L1", "Nombre": "otro"}), db_path=db)
    assert len(repo.search_by_text("%", db_path=db)) == 1
    assert repo.search_by_text("'; DROP TABLE licitaciones; --", db_path=db) == []
    assert repo.count_licitaciones(db_path=db) == 2


def test_list_licitaciones(db):
    repo.upsert_licitaciones(
        [
            normalize_list_item({"CodigoExterno": "2-2-L1", "Nombre": "B"}),
            normalize_detail(DETAIL_RECORD),
        ],
        db_path=db,
    )
    assert [r["codigo_externo"] for r in repo.list_licitaciones(db_path=db)] == ["1019-102-LE26", "2-2-L1"]
    assert [r["codigo_externo"] for r in repo.list_licitaciones(db_path=db, solo_con_detalle=True)] == ["1019-102-LE26"]
