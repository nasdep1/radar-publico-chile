"""Repositorio SQLite de licitaciones (sqlite3 directo, queries parametrizadas).

Todas las funciones aceptan `db_path` opcional; por defecto usan
`data/radar_publico.db`.

Regla de actualización:
- Un registro con detalle (detalle_descargado = 1) reemplaza todas las columnas,
  salvo `query_date`, que se conserva si el detalle no trae una.
- Un registro básico del listado (detalle_descargado = 0) inserta la licitación
  si no existe, o actualiza sus campos básicos solo si todavía no tiene
  detalle: nunca pisa un detalle ya descargado. Sí actualiza `query_date`
  (fecha enviada a la API en la consulta que devolvió el registro), también
  en licitaciones con detalle, sin volver a descargarlo.
"""

from datetime import datetime

from src.database import LICITACIONES_COLUMNS, connect, create_schema
from src.services.normalizer import normalize_text

# Campos del listado que solo se actualizan mientras la licitación no tiene detalle.
_BASIC_FIELDS = ("nombre", "codigo_estado", "fecha_cierre", "raw_json")
_DETAIL_UPDATE_COLUMNS = tuple(
    c for c in LICITACIONES_COLUMNS if c not in ("codigo_externo", "fecha_captura", "query_date")
)
_KEEP_QUERY_DATE = "query_date = COALESCE(excluded.query_date, licitaciones.query_date)"

_INSERT = (
    f"INSERT INTO licitaciones ({', '.join(LICITACIONES_COLUMNS)}) "
    f"VALUES ({', '.join('?' for _ in LICITACIONES_COLUMNS)}) "
    "ON CONFLICT(codigo_externo) DO UPDATE SET "
)
_UPSERT_DETAIL = (
    _INSERT
    + ", ".join(f"{c} = excluded.{c}" for c in _DETAIL_UPDATE_COLUMNS)
    + f", {_KEEP_QUERY_DATE}"
)
_UPSERT_BASIC = (
    _INSERT
    + ", ".join(
        f"{c} = CASE WHEN licitaciones.detalle_descargado = 0 THEN excluded.{c} ELSE licitaciones.{c} END"
        for c in _BASIC_FIELDS
    )
    + f", {_KEEP_QUERY_DATE}, fecha_actualizacion = excluded.fecha_actualizacion"
)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _row_values(data: dict, timestamp: str) -> tuple:
    if not data.get("codigo_externo"):
        raise ValueError("La licitación no tiene codigo_externo.")
    row = {column: data.get(column) for column in LICITACIONES_COLUMNS}
    row["detalle_descargado"] = 1 if data.get("detalle_descargado") else 0
    row["fecha_captura"] = timestamp
    row["fecha_actualizacion"] = timestamp
    return tuple(row[column] for column in LICITACIONES_COLUMNS)


def initialize_database(db_path=None) -> None:
    with connect(db_path) as conn:
        create_schema(conn)


def upsert_licitaciones(rows, db_path=None) -> int:
    """Inserta o actualiza varias licitaciones en una sola transacción."""
    timestamp = _now()
    count = 0
    with connect(db_path) as conn:
        for data in rows:
            sql = _UPSERT_DETAIL if data.get("detalle_descargado") else _UPSERT_BASIC
            conn.execute(sql, _row_values(data, timestamp))
            count += 1
    return count


def upsert_licitacion(data: dict, db_path=None) -> None:
    upsert_licitaciones([data], db_path=db_path)


def get_licitacion(codigo: str, db_path=None):
    """Devuelve la licitación como diccionario, o None si no existe."""
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM licitaciones WHERE codigo_externo = ?", (codigo,)
        ).fetchone()
    return dict(row) if row else None


def licitacion_has_detail(codigo: str, db_path=None) -> bool:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM licitaciones WHERE codigo_externo = ? AND detalle_descargado = 1",
            (codigo,),
        ).fetchone()
    return row is not None


def list_licitaciones(db_path=None, solo_con_detalle: bool = False, query_date=None) -> list:
    """Licitaciones guardadas, ordenadas por código.

    `query_date` (YYYY-MM-DD) filtra por la fecha enviada a la API en la
    consulta que devolvió el registro; los registros con query_date NULL no
    coinciden con ninguna fecha.
    """
    conditions, params = [], []
    if solo_con_detalle:
        conditions.append("detalle_descargado = 1")
    if query_date is not None:
        conditions.append("query_date = ?")
        params.append(str(query_date))
    sql = "SELECT * FROM licitaciones"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY codigo_externo"
    with connect(db_path) as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_by_text(text: str, db_path=None) -> list:
    """Busca el texto (sin distinguir mayúsculas ni tildes) en nombre y descripción."""
    needle = normalize_text(text)
    if not needle:
        return []
    pattern = f"%{_escape_like(needle)}%"
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM licitaciones "
            "WHERE normalize_text(nombre) LIKE ? ESCAPE '\\' "
            "OR normalize_text(descripcion) LIKE ? ESCAPE '\\' "
            "ORDER BY codigo_externo",
            (pattern, pattern),
        ).fetchall()
    return [dict(row) for row in rows]


def count_licitaciones(db_path=None, solo_con_detalle: bool = False) -> int:
    sql = "SELECT COUNT(*) FROM licitaciones"
    if solo_con_detalle:
        sql += " WHERE detalle_descargado = 1"
    with connect(db_path) as conn:
        return conn.execute(sql).fetchone()[0]
