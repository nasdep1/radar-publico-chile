"""Scoring contextual de relevancia (segunda etapa, sobre licitaciones con detalle).

LISTADO → filtro barato por título → detalle → SCORING CONTEXTUAL → relevante / no

Reglas deterministas, auditables y explicables: sin IA, embeddings ni fuzzy
matching. Todo lo configurable (señales, pesos, combinaciones, factores por
campo y umbral) está en un único perfil declarativo por consulta; este módulo
no contiene números mágicos fuera de ese perfil ni reglas por código de
licitación u organismo específico.

Coincidencia de términos: el mismo criterio que el filtro de candidatas
(texto normalizado sin tildes, término al inicio de una palabra), de modo que
"hospital" coincide con "hospitalaria" y "laparoscop" con "laparoscópico".
"""

import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache

from src.services.candidate_filter import compile_terms
from src.services.normalizer import extract_items, item_text_values, normalize_text

# Campos de contenido de la licitación (sin el organismo comprador).
CONTENT_FIELDS = ("titulo", "descripcion", "items", "categorias")
ALL_FIELDS = CONTENT_FIELDS + ("organismo",)


@dataclass(frozen=True)
class Signal:
    """Grupo de términos que representa un concepto, con su peso."""

    name: str
    weight: float
    terms: tuple
    fields: tuple = CONTENT_FIELDS
    description: str = ""


@dataclass(frozen=True)
class CombinationRule:
    """Suma `weight` cuando se cumplen todos los grupos de `requires`.

    `requires` es una tupla de grupos; cada grupo es una tupla de nombres de
    señales y se cumple si al menos una de ellas está presente.
    """

    name: str
    weight: float
    requires: tuple
    description: str = ""


@dataclass(frozen=True)
class BuyerRule:
    """Clasifica al comprador según su nombre (NombreOrganismo)."""

    municipal_pattern: str
    excluded_terms: tuple
    municipal_weight: float
    non_municipal_weight: float


@dataclass(frozen=True)
class RelevanceProfile:
    name: str
    threshold: float
    field_factors: dict
    signals: tuple
    combinations: tuple
    buyer: BuyerRule


@dataclass
class MatchedSignal:
    name: str
    points: float
    matches: list  # ["termino@campo", ...]
    description: str = ""


@dataclass
class RelevanceResult:
    score: float
    relevant: bool
    threshold: float
    positive_signals: list = field(default_factory=list)
    negative_signals: list = field(default_factory=list)
    explanation: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# --- Perfil: seguridad pública municipal --------------------------------------
#
# Concepto: acciones de seguridad pública/prevención del delito en el territorio
# comunal, impulsadas por municipalidades. NO incluye seguridad institucional de
# edificios (hospitales, tribunales, servicios públicos), militar, penitenciaria,
# informática ni usos polisémicos de "cámara" (sanitaria, médica).
#
# Criterio de pesos:
#   4    señal fuerte: nombra directamente el concepto (seguridad pública,
#        prevención del delito, patrullaje comunitario/municipal/preventivo).
#   3    tecnología o programa típicamente municipal de seguridad
#        (televigilancia, lectores de patentes, alarmas comunitarias) y
#        comprador que es una municipalidad.
#   1    señal débil o de contexto (CCTV y cámaras de seguridad sin contexto,
#        patrullaje genérico, comuna/espacios públicos).
#   0.5  palabra aislada casi sin valor ("seguridad", "prevención").
#   −6   dominio claramente distinto (salud, saneamiento, militar/penitenciario).
#   −5   ciberseguridad.
#   −4   institución no municipal nombrada (tribunales, SII, IPS, SML, museo...).
#   −2   guardias/servicio de vigilancia (seguridad de instalaciones) y
#        comprador que no es municipalidad.
#   −1   palabras de instalaciones (edificio, dependencias, oficinas).
# "cámara" sola no es señal: es polisémica (sanitaria, médica, de comercio).
#
# Umbral 6: exige, por ejemplo, una señal fuerte más comprador municipal
# (4 + 3), o vigilancia genérica en contexto municipal más comprador
# municipal (1×1,5 + 2 + 3). Una sola señal fuerte de un comprador no
# municipal (4 − 2) o un comprador municipal sin propósito de seguridad
# pública (3 + contexto) no alcanzan.

SEGURIDAD_MUNICIPAL = RelevanceProfile(
    name="seguridad municipal",
    threshold=6.0,
    # Un término en el título pesa más que en la descripción o los ítems, y una
    # categoría de ítem (texto genérico de catálogo) pesa menos.
    field_factors={"titulo": 1.5, "descripcion": 1.0, "items": 1.0, "categorias": 0.5, "organismo": 1.0},
    signals=(
        # Positivas fuertes
        Signal("seguridad_publica", 4, (
            "seguridad publica", "seguridad ciudadana", "seguridad comunal",
            "direccion de seguridad",
        ), description="Nombra la seguridad pública o ciudadana."),
        Signal("prevencion_del_delito", 4, (
            "prevencion del delito", "prevencion de delitos", "prevencion situacional",
        ), description="Prevención del delito."),
        Signal("patrullaje_territorial", 4, (
            "patrullaje comunitario", "patrullajes comunitarios",
            "patrullaje municipal", "patrullajes municipales",
            "patrullaje preventivo", "patrullajes preventivos",
        ), description="Patrullaje comunitario, municipal o preventivo."),
        Signal("lectura_de_patentes", 3, (
            "lector de patentes", "lectores de patentes",
            "lectora de patentes", "lectoras de patentes", "lectura de patentes",
        ), description="Cámaras lectoras de patentes (control vial/delictual)."),
        Signal("televigilancia", 3, ("televigilancia", "tele vigilancia"),
               description="Sistemas de televigilancia."),
        Signal("alarmas_comunitarias", 3, ("alarma comunitaria", "alarmas comunitarias"),
               description="Programa de alarmas comunitarias."),
        # Positivas débiles o de contexto
        Signal("vigilancia_generica", 1, (
            "cctv", "circuito cerrado", "videovigilancia",
            "camara de seguridad", "camaras de seguridad",
            "camara de vigilancia", "camaras de vigilancia",
        ), description="Cámaras/CCTV: solo cuentan de verdad con contexto municipal."),
        Signal("patrullaje_generico", 1, ("patrullaje",), description="Patrullaje sin calificar."),
        Signal("contexto_territorial", 1, (
            "comuna", "comunal", "municipal", "espacios publicos", "espacio publico",
            "via publica", "puntos estrategicos", "vecinos", "vecinal", "barrios",
        ), description="Referencia al territorio comunal o a espacios públicos."),
        Signal("seguridad_generica", 0.5, ("seguridad",), description="'Seguridad' aislada: débil."),
        Signal("prevencion_generica", 0.5, ("prevencion",), description="'Prevención' aislada: débil."),
        # Negativas: dominios distintos (también se buscan en el organismo)
        Signal("salud", -6, (
            "hospital", "laparoscop", "clinica", "clinico", "pacientes", "servicio de salud",
            "cesfam", "cecosf", "consultorio", "posta rural", "postas rurales", "posta de salud",
            "quirurgic", "insumos medicos", "equipamiento medico",
        ), fields=ALL_FIELDS, description="Salud/medicina."),
        Signal("saneamiento", -6, (
            "alcantarillado", "desgrasador", "camara sanitaria", "camaras sanitarias",
            "camara de inspeccion", "camaras de inspeccion", "aguas lluvia", "aguas servidas",
        ), fields=ALL_FIELDS, description="Saneamiento: 'cámara' en sentido sanitario."),
        Signal("militar_penitenciario", -6, (
            "ejercito", "armada", "fuerza aerea", "regimiento", "gendarmeria",
            "unidad penal", "unidades penales", "penitenciari", "viviendas fiscales",
        ), fields=ALL_FIELDS, description="Defensa o sistema penitenciario."),
        Signal("ciberseguridad", -5, (
            "ciberseguridad", "firewall", "cortafuego", "f5", "seguridad informatica",
            "seguridad de red", "seguridad de la red", "plataforma de seguridad", "antivirus",
        ), fields=ALL_FIELDS, description="Seguridad informática."),
        Signal("institucion_no_municipal", -4, (
            "poder judicial", "tribunal", "juzgado", "corte de apelaciones",
            "servicio de impuestos internos", "sii", "instituto de prevision social", "ips",
            "servicio medico legal", "museo", "corporacion cultural", "edificio institucional",
        ), fields=ALL_FIELDS, description="Institución o recinto no municipal."),
        Signal("seguridad_de_instalaciones", -2, (
            "guardia", "servicio de vigilancia", "servicios de vigilancia",
            "seguridad y vigilancia", "vigilancia privada",
        ), description="Guardias/vigilancia de recintos: seguridad institucional."),
        Signal("instalaciones", -1, (
            "dependencias", "edificio", "oficinas", "recinto",
        ), description="Recintos o edificios."),
    ),
    combinations=(
        CombinationRule(
            "vigilancia_en_contexto_municipal", 2,
            (("vigilancia_generica",), ("comprador_municipal", "contexto_territorial")),
            "CCTV/cámaras de seguridad con comprador municipal o contexto comunal.",
        ),
        CombinationRule(
            "vigilancia_de_recinto_institucional", -3,
            (("seguridad_de_instalaciones",), ("salud", "institucion_no_municipal", "instalaciones")),
            "Guardias/vigilancia de un hospital, institución o recinto.",
        ),
        CombinationRule(
            "camaras_de_institucion_no_municipal", -3,
            (("vigilancia_generica", "televigilancia"), ("salud", "institucion_no_municipal")),
            "Cámaras o televigilancia de una institución no municipal.",
        ),
    ),
    buyer=BuyerRule(
        # "I MUNICIPALIDAD DE...", "ILUSTRE MUNICIPALIDAD DE...", "MUNICIPALIDAD DE..."
        municipal_pattern=r"(?<!\w)municipalidad(?!\w)",
        # "Corporación Municipal de Salud/Cultura" no es la municipalidad.
        excluded_terms=("corporacion", "asociacion", "fundacion"),
        municipal_weight=3,
        non_municipal_weight=-2,
    ),
)

PROFILES = {SEGURIDAD_MUNICIPAL.name: SEGURIDAD_MUNICIPAL}


def get_profile(query: str):
    """Perfil contextual de una consulta, o None si no existe."""
    return PROFILES.get(normalize_text(query))


# --- Motor de scoring -----------------------------------------------------------

def build_fields(licitacion: dict) -> dict:
    """Textos normalizados por campo, a partir de una licitación guardada en SQLite."""
    items = extract_items(licitacion.get("items_json"))
    return {
        "titulo": normalize_text(licitacion.get("nombre")),
        "descripcion": normalize_text(licitacion.get("descripcion")),
        "items": normalize_text(" | ".join(
            item_text_values(items, "NombreProducto") + item_text_values(items, "Descripcion")
        )),
        "categorias": normalize_text(" | ".join(dict.fromkeys(item_text_values(items, "Categoria")))),
        "organismo": normalize_text(licitacion.get("nombre_organismo")),
    }


@lru_cache(maxsize=None)
def _patterns(terms: tuple) -> list:
    return compile_terms(terms)


def _match_signal(signal: Signal, fields: dict, factors: dict):
    """Devuelve (puntos, coincidencias) o None. Cada señal cuenta una sola vez,
    con el factor del campo más importante donde aparece."""
    matches, best_factor = [], None
    for field_name in signal.fields:
        text = fields.get(field_name, "")
        if not text:
            continue
        for term, pattern in _patterns(signal.terms):
            if pattern.search(text):
                matches.append(f"{term}@{field_name}")
                factor = factors[field_name]
                best_factor = factor if best_factor is None else max(best_factor, factor)
    if not matches:
        return None
    return round(signal.weight * best_factor, 2), matches


def _buyer_signal(buyer: BuyerRule, organismo: str):
    if not organismo:
        return None
    excluded = any(pattern.search(organismo) for _, pattern in _patterns(buyer.excluded_terms))
    if re.search(buyer.municipal_pattern, organismo) and not excluded:
        return MatchedSignal("comprador_municipal", buyer.municipal_weight, [f"{organismo}@organismo"],
                             "El comprador es una municipalidad.")
    return MatchedSignal("comprador_no_municipal", buyer.non_municipal_weight, [f"{organismo}@organismo"],
                         "El comprador no es una municipalidad.")


def score_licitacion(licitacion: dict, profile: RelevanceProfile, threshold=None) -> RelevanceResult:
    threshold = profile.threshold if threshold is None else float(threshold)
    fields = build_fields(licitacion)

    matched = []
    for signal in profile.signals:
        result = _match_signal(signal, fields, profile.field_factors)
        if result is not None:
            points, matches = result
            matched.append(MatchedSignal(signal.name, points, matches, signal.description))
    buyer = _buyer_signal(profile.buyer, fields["organismo"])
    if buyer is not None:
        matched.append(buyer)

    present = {m.name for m in matched}
    for rule in profile.combinations:
        if all(any(name in present for name in group) for group in rule.requires):
            matched.append(MatchedSignal(rule.name, rule.weight, ["combinación"], rule.description))

    score = round(sum(m.points for m in matched), 2)
    relevant = score >= threshold
    positives = [m for m in matched if m.points > 0]
    negatives = [m for m in matched if m.points < 0]
    return RelevanceResult(
        score=score,
        relevant=relevant,
        threshold=threshold,
        positive_signals=positives,
        negative_signals=negatives,
        explanation=_explain(score, threshold, relevant, positives, negatives),
    )


def score_seguridad_municipal(licitacion: dict, threshold=None) -> RelevanceResult:
    return score_licitacion(licitacion, SEGURIDAD_MUNICIPAL, threshold=threshold)


def format_signals(signals) -> str:
    return ", ".join(f"{s.name}({s.points:+g})" for s in signals) or "-"


def _explain(score, threshold, relevant, positives, negatives) -> str:
    verdict = "relevante" if relevant else "no relevante"
    comparison = "≥" if relevant else "<"
    return (
        f"Score {score:g} {comparison} umbral {threshold:g} → {verdict}. "
        f"Positivas: {format_signals(positives)}. Negativas: {format_signals(negatives)}."
    )
