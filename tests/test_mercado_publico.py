"""Tests unitarios del cliente de Mercado Público (sin llamadas reales a la API)."""

from datetime import date, datetime
from unittest.mock import Mock

import pytest
import requests

from src import config
from src.sources.mercado_publico import (
    MercadoPublicoClient,
    MercadoPublicoConnectionError,
    MercadoPublicoHTTPError,
    MercadoPublicoJSONError,
    MercadoPublicoTimeoutError,
    format_fecha,
)

TEST_TICKET = "TEST_TICKET"
URL_CON_TICKET = f"{config.MERCADOPUBLICO_LICITACIONES_URL}?ticket={TEST_TICKET}"


def make_response(status_code=200, json_data=None, text="", json_error=False):
    response = Mock()
    response.status_code = status_code
    response.text = text
    response.headers = {"Content-Type": "application/json"}
    if json_error:
        response.json.side_effect = ValueError("Expecting value")
    else:
        response.json.return_value = json_data
    return response


def make_client(response=None, side_effect=None, sleep=None):
    session = Mock()
    if side_effect is not None:
        session.get.side_effect = side_effect
    else:
        session.get.return_value = response
    # `sleep` simulado: los tests nunca esperan realmente.
    client = MercadoPublicoClient(
        ticket=TEST_TICKET, timeout=5, session=session, sleep=sleep or Mock()
    )
    return client, session


def assert_sin_ticket(error):
    assert TEST_TICKET not in str(error)
    assert "ticket=" not in str(error)
    # La excepción original de requests (con la URL) no debe quedar encadenada.
    assert error.__cause__ is None
    assert error.__suppress_context__ is True


# 1. Transformación de fecha a DDMMAAAA

def test_format_fecha_date():
    assert format_fecha(date(2026, 9, 22)) == "22092026"


def test_format_fecha_rellena_con_ceros():
    assert format_fecha(date(2026, 1, 5)) == "05012026"


def test_format_fecha_datetime():
    assert format_fecha(datetime(2026, 9, 22, 15, 30)) == "22092026"


def test_format_fecha_string_ddmmaaaa():
    assert format_fecha("22092026") == "22092026"


@pytest.mark.parametrize("valor", ["2026-09-22", "31022026", "2292026", "abcdefgh"])
def test_format_fecha_string_invalido(valor):
    with pytest.raises(ValueError):
        format_fecha(valor)


def test_format_fecha_tipo_invalido():
    with pytest.raises(TypeError):
        format_fecha(22092026)


def test_get_licitaciones_by_date_envia_fecha_formateada():
    client, session = make_client(make_response(json_data={}))
    client.get_licitaciones_by_date(date(2026, 9, 22))
    assert session.get.call_args.kwargs["params"]["fecha"] == "22092026"


# 2. Inclusión interna del parámetro ticket

def test_request_incluye_ticket_y_timeout():
    client, session = make_client(make_response(json_data={}))
    client.get_licitaciones_by_date(date(2026, 9, 22))

    args, kwargs = session.get.call_args
    assert args[0] == config.MERCADOPUBLICO_LICITACIONES_URL
    assert kwargs["params"] == {"fecha": "22092026", "ticket": TEST_TICKET}
    assert kwargs["timeout"] == 5


def test_get_active_licitaciones_usa_estado_activas():
    client, session = make_client(make_response(json_data={}))
    client.get_active_licitaciones()
    assert session.get.call_args.kwargs["params"] == {"estado": "activas", "ticket": TEST_TICKET}


def test_get_licitacion_by_code_usa_codigo():
    client, session = make_client(make_response(json_data={}))
    client.get_licitacion_by_code(" 1509-5-L114 ")
    assert session.get.call_args.kwargs["params"] == {"codigo": "1509-5-L114", "ticket": TEST_TICKET}


def test_get_licitacion_by_code_vacio_no_consulta():
    client, session = make_client(make_response(json_data={}))
    with pytest.raises(ValueError):
        client.get_licitacion_by_code("  ")
    session.get.assert_not_called()


def test_repr_no_expone_ticket():
    client, _ = make_client(make_response(json_data={}))
    assert TEST_TICKET not in repr(client)


# 3. Manejo de timeout

def test_timeout_genera_error_sanitizado():
    client, _ = make_client(side_effect=requests.exceptions.Timeout(f"Read timed out: {URL_CON_TICKET}"))
    with pytest.raises(MercadoPublicoTimeoutError) as excinfo:
        client.get_active_licitaciones()
    assert str(excinfo.value) == "Timeout consultando Mercado Público."
    assert_sin_ticket(excinfo.value)


def test_error_de_conexion_sanitizado():
    client, _ = make_client(side_effect=requests.exceptions.ConnectionError(f"Max retries: {URL_CON_TICKET}"))
    with pytest.raises(MercadoPublicoConnectionError) as excinfo:
        client.get_active_licitaciones()
    assert_sin_ticket(excinfo.value)


# 4. Manejo de HTTP != 200

def test_http_500():
    body = f'{{"Mensaje": "error interno", "url": "{URL_CON_TICKET}"}}'
    client, _ = make_client(make_response(status_code=500, text=body))
    with pytest.raises(MercadoPublicoHTTPError) as excinfo:
        client.get_active_licitaciones()
    error = excinfo.value
    assert error.status_code == 500
    assert str(error).startswith("Mercado Público respondió HTTP 500.")
    assert TEST_TICKET not in str(error)
    assert TEST_TICKET not in error.body_snippet


@pytest.mark.parametrize("status_code", [401, 403])
def test_http_autorizacion_sugiere_revisar_ticket(status_code):
    client, _ = make_client(make_response(status_code=status_code))
    with pytest.raises(MercadoPublicoHTTPError) as excinfo:
        client.get_active_licitaciones()
    assert "ticket o autorización" in str(excinfo.value)


def test_http_429_sugiere_rate_limit():
    client, _ = make_client(make_response(status_code=429))
    with pytest.raises(MercadoPublicoHTTPError) as excinfo:
        client.get_active_licitaciones()
    assert "límite de solicitudes" in str(excinfo.value)


# Reintentos ante HTTP 429

BODY_429 = '{"Codigo":10500,"Mensaje":"Lo sentimos. Hemos detectado que existen peticiones simultáneas."}'


def test_reintentos_429_por_defecto():
    assert config.RETRY_429_DELAYS == (3, 6, 12)


def test_429_reintenta_y_luego_exito():
    sleep = Mock()
    simulado = {"Cantidad": 1, "Listado": []}
    client, session = make_client(
        side_effect=[
            make_response(status_code=429, text=BODY_429),
            make_response(status_code=429, text=BODY_429),
            make_response(json_data=simulado),
        ],
        sleep=sleep,
    )
    assert client.get_licitacion_by_code("1019-102-LE26") == simulado
    assert session.get.call_count == 3
    assert [c.args[0] for c in sleep.call_args_list] == [3, 6]
    # Cada reintento repite la misma consulta, con el ticket incluido.
    for call in session.get.call_args_list:
        assert call.kwargs["params"] == {"codigo": "1019-102-LE26", "ticket": TEST_TICKET}


def test_429_agota_reintentos():
    sleep = Mock()
    body = BODY_429[:-1] + f', "url": "{URL_CON_TICKET}"}}'
    client, session = make_client(make_response(status_code=429, text=body), sleep=sleep)
    with pytest.raises(MercadoPublicoHTTPError) as excinfo:
        client.get_licitacion_by_code("1019-102-LE26")
    assert session.get.call_count == 4  # 1 intento + 3 reintentos
    assert [c.args[0] for c in sleep.call_args_list] == [3, 6, 12]
    error = excinfo.value
    assert error.status_code == 429
    assert "10500" in error.body_snippet
    assert TEST_TICKET not in str(error)
    assert TEST_TICKET not in error.body_snippet


@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 500, 503])
def test_no_reintenta_otros_codigos(status_code):
    sleep = Mock()
    client, session = make_client(make_response(status_code=status_code), sleep=sleep)
    with pytest.raises(MercadoPublicoHTTPError) as excinfo:
        client.get_active_licitaciones()
    assert excinfo.value.status_code == status_code
    assert session.get.call_count == 1
    sleep.assert_not_called()


def test_timeout_no_se_reintenta():
    sleep = Mock()
    client, session = make_client(side_effect=requests.exceptions.Timeout(URL_CON_TICKET), sleep=sleep)
    with pytest.raises(MercadoPublicoTimeoutError):
        client.get_active_licitaciones()
    assert session.get.call_count == 1
    sleep.assert_not_called()


# 5. Manejo de JSON inválido

def test_json_invalido():
    client, _ = make_client(make_response(text="<html>error</html>", json_error=True))
    with pytest.raises(MercadoPublicoJSONError) as excinfo:
        client.get_active_licitaciones()
    assert str(excinfo.value) == "No fue posible interpretar la respuesta JSON de Mercado Público."
    assert excinfo.value.body_snippet == "<html>error</html>"


def test_json_que_no_es_objeto():
    client, _ = make_client(make_response(json_data=[1, 2, 3]))
    with pytest.raises(MercadoPublicoJSONError):
        client.get_active_licitaciones()


# 6. Retorno correcto de respuesta simulada

def test_devuelve_json_parseado():
    simulado = {"Cantidad": 1, "Listado": [{"CodigoExterno": "1509-5-L114"}]}
    client, _ = make_client(make_response(json_data=simulado))
    assert client.get_licitaciones_by_date(date(2026, 9, 22)) == simulado


# Configuración

def test_ticket_faltante(monkeypatch):
    monkeypatch.delenv(config.MERCADOPUBLICO_TICKET_ENV, raising=False)
    with pytest.raises(config.ConfigError) as excinfo:
        MercadoPublicoClient(session=Mock())
    assert str(excinfo.value) == config.MISSING_TICKET_MESSAGE


def test_ticket_de_ejemplo_se_considera_faltante(monkeypatch):
    monkeypatch.setenv(config.MERCADOPUBLICO_TICKET_ENV, "PEGA_AQUI_TU_TICKET")
    with pytest.raises(config.ConfigError):
        config.get_mercadopublico_ticket()


def test_ticket_desde_entorno(monkeypatch):
    monkeypatch.setenv(config.MERCADOPUBLICO_TICKET_ENV, f"  {TEST_TICKET}  ")
    assert config.get_mercadopublico_ticket() == TEST_TICKET
