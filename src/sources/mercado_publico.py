"""Cliente mínimo para la API pública de licitaciones de Mercado Público.

Solo usa parámetros documentados (fecha, estado, codigo). No asume la
estructura interna del JSON: devuelve el diccionario tal como llega.

Ningún mensaje de error generado aquí incluye la URL ni el ticket.
"""

from datetime import date, datetime

import requests

from src import config

_BODY_SNIPPET_LENGTH = 300


class MercadoPublicoError(Exception):
    """Error base del cliente. Sus mensajes nunca contienen el ticket."""


class MercadoPublicoTimeoutError(MercadoPublicoError):
    """La API no respondió dentro del tiempo límite."""


class MercadoPublicoConnectionError(MercadoPublicoError):
    """No fue posible establecer conexión con la API."""


class MercadoPublicoHTTPError(MercadoPublicoError):
    """La API respondió con un código HTTP distinto de 200."""

    def __init__(self, message: str, status_code: int, body_snippet: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.body_snippet = body_snippet


class MercadoPublicoJSONError(MercadoPublicoError):
    """La respuesta no es JSON válido o no tiene la forma esperada."""

    def __init__(self, message: str, content_type: str = "", body_snippet: str = ""):
        super().__init__(message)
        self.content_type = content_type
        self.body_snippet = body_snippet


def format_fecha(fecha) -> str:
    """Convierte una fecha al formato DDMMAAAA exigido por la API.

    Acepta `datetime.date`, `datetime.datetime` o un string ya en formato
    DDMMAAAA (por ejemplo "22092026"), que se valida como fecha real.
    """
    if isinstance(fecha, (date, datetime)):
        return fecha.strftime("%d%m%Y")
    if isinstance(fecha, str):
        valor = fecha.strip()
        mensaje = f"Fecha inválida: {fecha!r}. Usa datetime.date o el formato DDMMAAAA."
        if len(valor) != 8 or not valor.isdigit():
            raise ValueError(mensaje)
        try:
            datetime.strptime(valor, "%d%m%Y")
        except ValueError:
            raise ValueError(mensaje) from None
        return valor
    raise TypeError("fecha debe ser datetime.date o un string DDMMAAAA.")


def _http_status_hint(status_code: int) -> str:
    if status_code in (401, 403):
        return " Posible problema de ticket o autorización."
    if status_code == 429:
        return " Posible límite de solicitudes (rate limit)."
    if 500 <= status_code < 600:
        return " Error del lado del servidor."
    return ""


class MercadoPublicoClient:
    """Cliente HTTP para el endpoint de licitaciones de Mercado Público."""

    def __init__(self, ticket=None, timeout=config.REQUEST_TIMEOUT, session=None):
        self._ticket = ticket if ticket is not None else config.get_mercadopublico_ticket()
        if not self._ticket:
            raise config.ConfigError(config.MISSING_TICKET_MESSAGE)
        self._timeout = timeout
        self._session = session if session is not None else requests.Session()
        self._url = config.MERCADOPUBLICO_LICITACIONES_URL

    def __repr__(self) -> str:
        return f"MercadoPublicoClient(host={config.MERCADOPUBLICO_HOST!r})"

    def get_licitaciones_by_date(self, fecha) -> dict:
        """Listado (información básica) de licitaciones de un día."""
        return self._request({"fecha": format_fecha(fecha)})

    def get_active_licitaciones(self) -> dict:
        """Licitaciones publicadas activas al momento de la consulta."""
        return self._request({"estado": "activas"})

    def get_licitacion_by_code(self, codigo: str) -> dict:
        """Detalle de una licitación a partir de su código."""
        if not isinstance(codigo, str) or not codigo.strip():
            raise ValueError("El código de licitación no puede estar vacío.")
        return self._request({"codigo": codigo.strip()})

    def _sanitize(self, text: str) -> str:
        """Elimina cualquier aparición del ticket en un texto."""
        if not text:
            return ""
        return text.replace(self._ticket, "***")

    def _request(self, params: dict) -> dict:
        query = {**params, "ticket": self._ticket}

        # `from None` evita que la excepción original de requests (que puede
        # contener la URL completa con el ticket) aparezca en el traceback.
        try:
            response = self._session.get(self._url, params=query, timeout=self._timeout)
        except requests.exceptions.Timeout:
            raise MercadoPublicoTimeoutError("Timeout consultando Mercado Público.") from None
        except requests.exceptions.ConnectionError:
            raise MercadoPublicoConnectionError(
                "No fue posible conectar con Mercado Público "
                "(red, DNS, proxy o firewall)."
            ) from None
        except requests.exceptions.RequestException:
            raise MercadoPublicoError("Error de red consultando Mercado Público.") from None

        body_snippet = self._sanitize(response.text[:_BODY_SNIPPET_LENGTH])

        if response.status_code != 200:
            raise MercadoPublicoHTTPError(
                f"Mercado Público respondió HTTP {response.status_code}."
                f"{_http_status_hint(response.status_code)}",
                status_code=response.status_code,
                body_snippet=body_snippet,
            )

        content_type = response.headers.get("Content-Type", "")
        try:
            data = response.json()
        except ValueError:
            raise MercadoPublicoJSONError(
                "No fue posible interpretar la respuesta JSON de Mercado Público.",
                content_type=content_type,
                body_snippet=body_snippet,
            ) from None

        if not isinstance(data, dict):
            raise MercadoPublicoJSONError(
                "La respuesta JSON de Mercado Público no es un objeto.",
                content_type=content_type,
                body_snippet=body_snippet,
            )
        return data
