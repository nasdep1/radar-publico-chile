"""Configuración general de Radar Público.

Carga el archivo `.env` de la raíz del proyecto y expone la configuración de
Mercado Público. Nunca imprime ni registra el ticket.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
DATA_DIR = PROJECT_ROOT / "data"

# Las variables ya definidas en el entorno tienen prioridad sobre `.env`.
load_dotenv(ENV_FILE)

MERCADOPUBLICO_TICKET_ENV = "MERCADOPUBLICO_TICKET"
MERCADOPUBLICO_SCHEME = "https"
MERCADOPUBLICO_HOST = "api.mercadopublico.cl"
MERCADOPUBLICO_LICITACIONES_PATH = "/servicios/v1/publico/licitaciones.json"
MERCADOPUBLICO_LICITACIONES_URL = (
    f"{MERCADOPUBLICO_SCHEME}://{MERCADOPUBLICO_HOST}{MERCADOPUBLICO_LICITACIONES_PATH}"
)

REQUEST_TIMEOUT = 30  # segundos

# Esperas (segundos) antes de cada reintento ante HTTP 429. Solo se reintenta 429.
RETRY_429_DELAYS = (3, 6, 12)

MISSING_TICKET_MESSAGE = (
    "No se encontró MERCADOPUBLICO_TICKET. Crea el archivo .env a partir de "
    ".env.example e incorpora tu ticket personal."
)

# Valor de ejemplo de .env.example: no es un ticket válido.
_PLACEHOLDER_TICKET = "PEGA_AQUI_TU_TICKET"


class ConfigError(Exception):
    """Configuración faltante o inválida."""


def get_mercadopublico_ticket() -> str:
    """Devuelve el ticket de Mercado Público o lanza ConfigError si falta."""
    ticket = os.getenv(MERCADOPUBLICO_TICKET_ENV, "").strip()
    if not ticket or ticket == _PLACEHOLDER_TICKET:
        raise ConfigError(MISSING_TICKET_MESSAGE)
    return ticket
