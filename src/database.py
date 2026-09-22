"""Conexión y esquema de la base SQLite local."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from src import config
from src.services.normalizer import normalize_text

LICITACIONES_COLUMNS = (
    "codigo_externo",
    "nombre",
    "codigo_estado",
    "estado",
    "descripcion",
    "fecha_cierre",
    "fecha_publicacion",
    "codigo_organismo",
    "nombre_organismo",
    "tipo",
    "moneda",
    "monto_estimado",
    "direccion_entrega",
    "direccion_visita",
    "items_json",
    "adjudicacion_json",
    "raw_json",
    "detalle_descargado",
    "fecha_captura",
    "fecha_actualizacion",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS licitaciones (
    codigo_externo      TEXT PRIMARY KEY,
    nombre              TEXT,
    codigo_estado       INTEGER,
    estado              TEXT,
    descripcion         TEXT,
    fecha_cierre        TEXT,
    fecha_publicacion   TEXT,
    codigo_organismo    TEXT,
    nombre_organismo    TEXT,
    tipo                TEXT,
    moneda              TEXT,
    monto_estimado      REAL NULL,
    direccion_entrega   TEXT NULL,
    direccion_visita    TEXT NULL,
    items_json          TEXT NULL,
    adjudicacion_json   TEXT NULL,
    raw_json            TEXT,
    detalle_descargado  INTEGER DEFAULT 0,
    fecha_captura       TEXT,
    fecha_actualizacion TEXT
);
"""


def _normalize_sql(value):
    return normalize_text(value) if isinstance(value, str) else ""


@contextmanager
def connect(db_path=None):
    """Abre una conexión, confirma la transacción al salir y siempre la cierra.

    Registra la función SQL `normalize_text(texto)` (minúsculas, sin tildes y
    con espacios compactados) para búsquedas insensibles a tildes.
    """
    path = Path(db_path) if db_path is not None else config.DATABASE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.create_function("normalize_text", 1, _normalize_sql, deterministic=True)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
