import json

import pytest

from src.services.normalizer import (
    describe_items,
    extract_detail_record,
    normalize_detail,
    normalize_list_item,
    normalize_text,
    parse_monto,
)
from tests.fixtures import DETAIL_RECORD, LIST_ITEM, detail_record, detail_response


# Texto

@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("CÁMARAS DE SEGURIDAD", "camaras de seguridad"),
        ("Prevención   del\tDelito ", "prevencion del delito"),
        ("PINGÜINO Ñandú", "pinguino nandu"),
        ("", ""),
        (None, ""),
        (123, ""),
    ],
)
def test_normalize_text(texto, esperado):
    assert normalize_text(texto) == esperado


# MontoEstimado

@pytest.mark.parametrize(
    "valor, esperado",
    [
        (15000000, 15000000.0),
        (1500.5, 1500.5),
        ("15000000", 15000000.0),
        ("15000000.5", 15000000.5),
        (" 1.500.000 ", 1500000.0),
        ("1.500.000,50", 1500000.5),
        ("$ 2.000", 2000.0),  # punto de miles
        ("2.5", 2.5),  # punto decimal
        ("1500,5", 1500.5),
        ("1.2.3", None),
        (None, None),
        ("", None),
        ("no informado", None),
        ("12abc", None),
        (True, None),
        (float("nan"), None),
        ({"monto": 1}, None),
        ([1], None),
    ],
)
def test_parse_monto(valor, esperado):
    assert parse_monto(valor) == esperado


# Listado

def test_normalize_list_item():
    assert normalize_list_item(LIST_ITEM) == {
        "codigo_externo": "1019-102-LE26",
        "nombre": "ADQUISICIÓN DE CÁMARAS DE TELEVIGILANCIA",
        "codigo_estado": 5,
        "fecha_cierre": "2026-10-05T15:00:00",
        "raw_json": json.dumps(LIST_ITEM, ensure_ascii=False),
        "detalle_descargado": 0,
    }


def test_normalize_list_item_tolera_nulos_y_tipos():
    item = {"CodigoExterno": " 1-2-L1 ", "Nombre": None, "CodigoEstado": "6", "FechaCierre": {}}
    result = normalize_list_item(item)
    assert result["codigo_externo"] == "1-2-L1"
    assert result["nombre"] is None
    assert result["codigo_estado"] == 6
    assert result["fecha_cierre"] is None


@pytest.mark.parametrize("item", [None, [], "texto", {}, {"CodigoExterno": None}, {"CodigoExterno": ""}])
def test_normalize_list_item_invalido(item):
    assert normalize_list_item(item) is None


def test_normalize_list_item_codigo_estado_invalido():
    assert normalize_list_item({"CodigoExterno": "1-2-L1", "CodigoEstado": "x"})["codigo_estado"] is None


# Detalle

def test_normalize_detail():
    result = normalize_detail(DETAIL_RECORD)
    assert result["codigo_externo"] == "1019-102-LE26"
    assert result["nombre"] == "ADQUISICIÓN DE CÁMARAS DE TELEVIGILANCIA"
    assert result["codigo_estado"] == 5
    assert result["estado"] == "Publicada"
    assert result["descripcion"].startswith("Suministro")
    assert result["fecha_cierre"] == "2026-10-05T15:00:00"
    assert result["fecha_publicacion"] == "2026-09-22T09:00:00"
    assert result["codigo_organismo"] == "7248"
    assert result["nombre_organismo"] == "I MUNICIPALIDAD DE EJEMPLO"
    assert result["tipo"] == "LE"
    assert result["moneda"] == "CLP"
    assert result["monto_estimado"] == 15000000.0
    assert result["direccion_entrega"] == "Plaza de Armas 1"
    assert result["direccion_visita"] is None  # string vacío
    assert json.loads(result["items_json"]) == DETAIL_RECORD["Items"]
    assert result["adjudicacion_json"] is None
    assert json.loads(result["raw_json"]) == DETAIL_RECORD
    assert result["detalle_descargado"] == 1


def test_normalize_detail_acepta_respuesta_completa():
    assert normalize_detail(detail_response()) == normalize_detail(DETAIL_RECORD)


def test_normalize_detail_tolera_nulos_vacios_y_tipos():
    record = detail_record(
        Comprador=None,
        Fechas=[],
        Estado={"x": 1},
        MontoEstimado="no informado",
        Items=[],
        Adjudicacion={},
        FechaCierre=None,
    )
    del record["Tipo"]
    result = normalize_detail(record)
    assert result["codigo_organismo"] is None
    assert result["nombre_organismo"] is None
    assert result["fecha_publicacion"] is None
    assert result["fecha_cierre"] is None
    assert result["estado"] is None
    assert result["tipo"] is None
    assert result["monto_estimado"] is None
    assert result["items_json"] == "[]"
    assert result["adjudicacion_json"] == "{}"


def test_normalize_detail_fecha_cierre_desde_fechas():
    result = normalize_detail(detail_record(FechaCierre=None))
    assert result["fecha_cierre"] == "2026-10-05T15:00:00"


def test_normalize_detail_monto_string_numerico():
    assert normalize_detail(detail_record(MontoEstimado="2500000"))["monto_estimado"] == 2500000.0


@pytest.mark.parametrize(
    "detail", [None, {}, [], {"Cantidad": 0, "Listado": []}, {"Listado": ["x"]}, {"Listado": [{"Nombre": "sin código"}]}]
)
def test_normalize_detail_invalido(detail):
    assert normalize_detail(detail) is None


def test_extract_detail_record():
    assert extract_detail_record(detail_response()) == DETAIL_RECORD
    assert extract_detail_record({"Listado": None}) is None
    assert extract_detail_record("texto") is None


# Diagnóstico de Items

def test_describe_items_dict_con_listado():
    items = {"Cantidad": 2, "Listado": [{"Correlativo": 1, "NombreProducto": "A"}, {"Correlativo": 2}]}
    assert describe_items(items) == {
        "tipo": "dict",
        "claves": ["Cantidad", "Listado"],
        "clave_lista": "Listado",
        "cantidad_elementos": 2,
        "claves_primer_item": ["Correlativo", "NombreProducto"],
    }


def test_describe_items_lista_equivalente():
    info = describe_items({"Productos": [{"Codigo": 1}]})
    assert info["clave_lista"] == "Productos"
    assert info["claves_primer_item"] == ["Codigo"]


def test_describe_items_lista_directa_y_vacia():
    assert describe_items([{"a": 1}])["clave_lista"] == "(lista directa)"
    assert describe_items([])["cantidad_elementos"] == 0
    assert describe_items(None)["tipo"] == "NoneType"
    assert describe_items({})["claves"] == []
