"""Prueba de integración real con la API de Mercado Público.

Uso (desde la raíz del proyecto):
    python scripts/test_mercado_publico_api.py

Consumo máximo de la API: hasta 8 consultas de listado (hoy + 7 días hacia
atrás, solo si los días anteriores no traen resultados) y 1 consulta de detalle.

No imprime el ticket, la URL completa ni el JSON completo: solo estructura.
"""

import re
import sys
from datetime import date, timedelta
from pathlib import Path

# Permite ejecutar el script directamente desde cualquier directorio y sistema
# operativo: agrega la raíz del proyecto (carpeta padre de scripts/) al path.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import config  # noqa: E402
from src.sources.mercado_publico import (  # noqa: E402
    MercadoPublicoClient,
    MercadoPublicoError,
    MercadoPublicoHTTPError,
    MercadoPublicoJSONError,
)

MAX_DIAS_ATRAS = 7
SEPARADOR = "=" * 40

# Forma observada de los códigos de licitación (ej. "1509-5-L114", "2732-25-LE26").
# Se usa solo para reconocer el campo del código entre las claves reales.
CODIGO_LICITACION_RE = re.compile(r"^\d+-\d+-[A-Z0-9]+$")


def fmt(d: date) -> str:
    return d.strftime("%d-%m-%Y")


def find_list(data: dict):
    """Devuelve (clave, lista) de la primera clave de nivel superior cuyo valor es lista."""
    for key, value in data.items():
        if isinstance(value, list):
            return key, value
    return None, []


def find_paths(obj, fragments, prefix="", depth=2):
    """Busca claves cuyo nombre contenga alguno de los fragmentos (sin distinguir
    mayúsculas), recorriendo diccionarios anidados hasta `depth` niveles."""
    found = []
    if not isinstance(obj, dict) or depth < 0:
        return found
    for key, value in obj.items():
        path = f"{prefix}{key}"
        if any(f in key.lower() for f in fragments):
            found.append((path, value))
        if isinstance(value, dict):
            found.extend(find_paths(value, fragments, f"{path}.", depth - 1))
    return found


def find_codigo(record: dict):
    """Identifica el campo real que contiene el código de licitación."""
    candidatos = [k for k in record if "codigo" in k.lower()] + list(record)
    for key in candidatos:
        value = record.get(key)
        if isinstance(value, str) and CODIGO_LICITACION_RE.match(value.strip()):
            return key, value.strip()
    return None, None


def short(value, limit=120) -> str:
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "…"


def show_fields(title, paths, show_values=True):
    if not paths:
        print(f"  {title}: no se encontró un campo reconocible")
        return
    print(f"  {title}:")
    for path, value in paths:
        if isinstance(value, (dict, list)):
            print(f"    - {path} ({type(value).__name__})")
        elif show_values:
            print(f"    - {path} = {short(value)}")
        else:
            print(f"    - {path}")


def is_number(value) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value.replace(",", "."))
            return True
        except ValueError:
            return False
    return False


def save_diagnostic(error: MercadoPublicoJSONError) -> Path:
    """Guarda un diagnóstico seguro (sin ticket ni URL) en data/."""
    path = config.DATA_DIR / "diagnostico_mercado_publico.txt"
    path.write_text(
        f"Error: {error}\n"
        f"Content-Type: {error.content_type}\n"
        f"Inicio de la respuesta (sanitizado):\n{error.body_snippet}\n",
        encoding="utf-8",
    )
    return path


def fail(error: Exception) -> int:
    print(f"\n✗ {error}")
    if isinstance(error, MercadoPublicoHTTPError) and error.body_snippet:
        print(f"  Respuesta (sanitizada): {short(error.body_snippet, 300)}")
    if isinstance(error, MercadoPublicoJSONError):
        print(f"  Diagnóstico guardado en: {save_diagnostic(error)}")
    print("\nINTEGRACIÓN MERCADO PÚBLICO: NO PROBADA")
    return 1


def main() -> int:
    print(SEPARADOR)
    print("RADAR PÚBLICO — TEST MERCADO PÚBLICO")
    print(SEPARADOR)

    # PASO A: configuración
    try:
        client = MercadoPublicoClient()
    except config.ConfigError as error:
        print(f"✗ {error}")
        return 1
    print("✓ Configuración cargada")

    # PASO B/C: listado por fecha, retrocediendo si no hay resultados
    fecha = date.today()
    listado, registros, clave_listado = None, [], None
    try:
        for dias_atras in range(MAX_DIAS_ATRAS + 1):
            fecha = date.today() - timedelta(days=dias_atras)
            print(f"\nConsultando Mercado Público para {fmt(fecha)}...")
            listado = client.get_licitaciones_by_date(fecha)
            print("✓ Respuesta recibida")

            clave_listado, registros = find_list(listado)
            print(f"  Claves de nivel superior: {list(listado)}")
            if "Cantidad" in listado:
                print(f"  Cantidad reportada (Cantidad): {listado['Cantidad']}")
            else:
                print("  Cantidad reportada: la respuesta no trae clave 'Cantidad'")
            if clave_listado is None:
                print("  No se encontró ninguna lista en el nivel superior.")
            print(f"  Elementos reales en '{clave_listado}': {len(registros)}")

            if registros:
                break
            if dias_atras < MAX_DIAS_ATRAS:
                print(f"No se encontraron licitaciones el {fmt(fecha)}. Probando día anterior...")
        else:
            print(f"\n✗ No se encontraron licitaciones en los últimos {MAX_DIAS_ATRAS + 1} días.")
            print("\nINTEGRACIÓN MERCADO PÚBLICO: NO PROBADA")
            return 1
    except MercadoPublicoError as error:
        return fail(error)

    primero = registros[0]
    if not isinstance(primero, dict):
        print(f"\n✗ El primer registro no es un objeto JSON ({type(primero).__name__}).")
        print("\nINTEGRACIÓN MERCADO PÚBLICO: NO PROBADA")
        return 1
    print(f"  Claves del primer registro: {list(primero)}")

    # PASO 13: identificar el código de la licitación
    campo_codigo, codigo = find_codigo(primero)
    if not codigo:
        print("\n✗ No se pudo identificar el código de licitación en el primer registro.")
        print("\nINTEGRACIÓN MERCADO PÚBLICO: NO PROBADA")
        return 1
    print(f"\n✓ Licitación de prueba encontrada: {codigo} (campo '{campo_codigo}')")

    # PASO 14: detalle de UNA licitación
    print("\nConsultando detalle...")
    try:
        detalle = client.get_licitacion_by_code(codigo)
    except MercadoPublicoError as error:
        return fail(error)
    print("✓ Detalle recibido")

    print(f"  Claves de nivel superior: {list(detalle)}")
    clave_detalle, registros_detalle = find_list(detalle)
    if not registros_detalle or not isinstance(registros_detalle[0], dict):
        print("\n✗ El detalle no contiene registros interpretables.")
        print("\nINTEGRACIÓN MERCADO PÚBLICO: NO PROBADA")
        return 1
    item = registros_detalle[0]
    print(f"  Claves del primer elemento en '{clave_detalle}': {list(item)}")

    show_fields("Título / nombre", [(p, v) for p, v in find_paths(item, ["nombre", "titulo"], depth=0)])
    show_fields("Organismo / comprador", find_paths(item, ["comprador", "organismo"]))
    show_fields("Estado", find_paths(item, ["estado"], depth=0))
    show_fields("Fechas", find_paths(item, ["fecha"]), show_values=False)
    montos = find_paths(item, ["monto"])
    if montos:
        print("  Monto:")
        for path, value in montos:
            valor = value if is_number(value) else "(valor no interpretable como número)"
            print(f"    - {path} existe → {valor}")
    else:
        print("  Monto: no se encontró un campo reconocible")

    solo_detalle = sorted(set(item) - set(primero))
    print(f"  Claves presentes solo en el detalle: {solo_detalle}")

    # PASO 15: resumen
    print(f"\n{SEPARADOR}")
    print("RADAR PÚBLICO — TEST MERCADO PÚBLICO")
    print(SEPARADOR)
    print("✓ Configuración cargada")
    print("✓ API accesible")
    print("✓ Listado de licitaciones recibido")
    print("✓ Licitación de prueba identificada")
    print("✓ Consulta de detalle exitosa")
    print(f"\nFecha consultada: {fmt(fecha)}")
    print(f"Cantidad de licitaciones: {len(registros)}")
    print(f"Código de prueba: {codigo}")
    print("\nINTEGRACIÓN MERCADO PÚBLICO: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
