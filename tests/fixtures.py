"""Datos de prueba con las claves REALES observadas en la API (valores ficticios)."""

import copy

LIST_ITEM = {
    "CodigoExterno": "1019-102-LE26",
    "Nombre": "ADQUISICIÓN DE CÁMARAS DE TELEVIGILANCIA",
    "CodigoEstado": 5,
    "FechaCierre": "2026-10-05T15:00:00",
}

DETAIL_RECORD = {
    "CodigoExterno": "1019-102-LE26",
    "Nombre": "ADQUISICIÓN DE CÁMARAS DE TELEVIGILANCIA",
    "CodigoEstado": 5,
    "Descripcion": "Suministro e instalación de cámaras para prevención del delito.",
    "FechaCierre": "2026-10-05T15:00:00",
    "Estado": "Publicada",
    "Comprador": {"CodigoOrganismo": "7248", "NombreOrganismo": "I MUNICIPALIDAD DE EJEMPLO"},
    "Tipo": "LE",
    "Moneda": "CLP",
    "Fechas": {
        "FechaCreacion": "2026-09-20T10:00:00",
        "FechaCierre": "2026-10-05T15:00:00",
        "FechaInicio": "2026-09-22T09:00:00",
        "FechaPublicacion": "2026-09-22T09:00:00",
        "FechaAdjudicacion": None,
        "FechaEstimadaAdjudicacion": "2026-10-20T00:00:00",
    },
    "DireccionVisita": "",
    "DireccionEntrega": "Plaza de Armas 1",
    "MontoEstimado": 15000000,
    "Adjudicacion": None,
    "Items": {"Cantidad": 1, "Listado": [{"Correlativo": 1, "NombreProducto": "Cámara"}]},
}


def detail_record(**overrides):
    record = copy.deepcopy(DETAIL_RECORD)
    record.update(overrides)
    return record


def detail_response(record=None):
    return {"Cantidad": 1, "FechaCreacion": "2026-09-22T12:00:00", "Version": "v1",
            "Listado": [record if record is not None else detail_record()]}


def list_response(items):
    return {"Cantidad": len(items), "FechaCreacion": "2026-09-22T12:00:00", "Version": "v1",
            "Listado": items}
