"""Tests del scoring contextual con casos SINTÉTICOS (textos inventados que
representan cada situación; no son las licitaciones reales del ground truth)."""

import json
import re
from pathlib import Path

import pytest

from src.services import contextual_relevance as cr
from src.services.contextual_relevance import (
    SEGURIDAD_MUNICIPAL,
    get_profile,
    score_licitacion,
    score_seguridad_municipal,
)
from src.services.relevance_evaluation import GROUND_TRUTH_FILES, load_ground_truth


def licitacion(nombre, organismo, descripcion="", items=()):
    """Licitación como la devuelve SQLite. `items`: (NombreProducto, Descripcion, Categoria)."""
    listado = [{"NombreProducto": n, "Descripcion": d, "Categoria": c} for n, d, c in items]
    return {
        "codigo_externo": "0-0-SINTETICO",
        "nombre": nombre,
        "descripcion": descripcion,
        "nombre_organismo": organismo,
        "items_json": json.dumps({"Cantidad": len(listado), "Listado": listado}),
        "detalle_descargado": 1,
    }


def names(signals):
    return {s.name for s in signals}


# Casos relevantes

def test_seguridad_publica_municipal():
    r = score_seguridad_municipal(licitacion(
        "Equipamiento para la Dirección de Seguridad Pública", "I MUNICIPALIDAD DE EJEMPLO",
        "Fortalecer la seguridad pública en la comuna."))
    assert r.relevant
    assert {"seguridad_publica", "comprador_municipal"} <= names(r.positive_signals)


def test_patrullaje_comunitario():
    r = score_seguridad_municipal(licitacion(
        "Adquisición de motocicletas para patrullaje comunitario", "ILUSTRE MUNICIPALIDAD DE EJEMPLO"))
    assert r.relevant
    assert "patrullaje_territorial" in names(r.positive_signals)


def test_televigilancia_municipal():
    r = score_seguridad_municipal(licitacion(
        "Sistema de televigilancia comunal", "MUNICIPALIDAD DE EJEMPLO",
        "Cámaras en espacios públicos para la prevención del delito.",
        items=[("Cámara domo", "Cámara IP", "Equipos de seguridad / Cámaras de vigilancia")]))
    assert r.relevant
    assert {"televigilancia", "prevencion_del_delito", "contexto_territorial"} <= names(r.positive_signals)
    assert r.negative_signals == []


def test_camaras_de_seguridad_con_comprador_municipal():
    r = score_seguridad_municipal(licitacion("Adquisición de cámaras de seguridad", "MUNICIPALIDAD DE EJEMPLO"))
    assert r.relevant
    assert "vigilancia_en_contexto_municipal" in names(r.positive_signals)


def test_lectoras_de_patentes_municipales():
    r = score_seguridad_municipal(licitacion(
        "Cámaras lectoras de patentes", "I MUNICIPALIDAD DE EJEMPLO", "Instalación en accesos a la comuna."))
    assert r.relevant
    assert "lectura_de_patentes" in names(r.positive_signals)


# Casos no relevantes

def test_camaras_laparoscopicas():
    r = score_seguridad_municipal(licitacion(
        "Cámara para torre de laparoscopía", "HOSPITAL REGIONAL DE EJEMPLO",
        items=[("Cámara laparoscópica", "Para pabellón", "Equipamiento médico")]))
    assert not r.relevant
    assert "salud" in names(r.negative_signals)


def test_camaras_sanitarias_aunque_compre_una_municipalidad():
    r = score_seguridad_municipal(licitacion(
        "Reposición de cámaras sanitarias", "MUNICIPALIDAD DE EJEMPLO", "Red de alcantarillado de la comuna."))
    assert not r.relevant
    assert "saneamiento" in names(r.negative_signals)


def test_guardias_hospitalarios():
    r = score_seguridad_municipal(licitacion(
        "Servicio de guardias de seguridad", "SERVICIO DE SALUD EJEMPLO", "Vigilancia del hospital base."))
    assert not r.relevant
    assert {"salud", "seguridad_de_instalaciones", "vigilancia_de_recinto_institucional"} <= names(r.negative_signals)


def test_firewall_ciberseguridad():
    r = score_seguridad_municipal(licitacion(
        "Renovación plataforma de seguridad F5", "MINISTERIO DE EJEMPLO", "Licencias de firewall."))
    assert not r.relevant
    assert "ciberseguridad" in names(r.negative_signals)


def test_camaras_gendarmeria():
    r = score_seguridad_municipal(licitacion("Cámaras corporales", "GENDARMERIA DE CHILE", "Para unidades penales."))
    assert not r.relevant
    assert "militar_penitenciario" in names(r.negative_signals)


def test_cctv_institucional_aun_con_contexto_comunal():
    r = score_seguridad_municipal(licitacion(
        "CCTV para edificio del juzgado", "CORPORACION ADMINISTRATIVA DEL PODER JUDICIAL",
        "Edificio ubicado en la comuna de Ejemplo."))
    assert not r.relevant
    assert {"institucion_no_municipal", "camaras_de_institucion_no_municipal"} <= names(r.negative_signals)


def test_televigilancia_de_edificio_institucional():
    r = score_seguridad_municipal(licitacion(
        "Televigilancia del edificio institucional", "SERVICIO MEDICO LEGAL"))
    assert not r.relevant
    assert "televigilancia" in names(r.positive_signals)
    assert "institucion_no_municipal" in names(r.negative_signals)


def test_camaras_de_edificio_municipal_son_seguridad_institucional():
    r = score_seguridad_municipal(licitacion(
        "Cámaras de seguridad para dependencias del edificio consistorial", "MUNICIPALIDAD DE EJEMPLO"))
    assert not r.relevant
    assert "instalaciones" in names(r.negative_signals)


# Comprador

@pytest.mark.parametrize("organismo", [
    "I MUNICIPALIDAD DE EJEMPLO", "ILUSTRE MUNICIPALIDAD DE EJEMPLO", "MUNICIPALIDAD DE EJEMPLO",
    "I. Municipalidad de Ejemplo",
])
def test_comprador_municipal(organismo):
    r = score_seguridad_municipal(licitacion("Compra de insumos", organismo))
    assert "comprador_municipal" in names(r.positive_signals)


@pytest.mark.parametrize("organismo", [
    "CORPORACION MUNICIPAL CULTURAL DE EJEMPLO", "CORPORACION MUNICIPAL DE SALUD DE EJEMPLO",
    "SERVICIO DE IMPUESTOS INTERNOS",
])
def test_comprador_no_municipal(organismo):
    r = score_seguridad_municipal(licitacion("Compra de insumos", organismo))
    assert "comprador_municipal" not in names(r.positive_signals)
    assert "comprador_no_municipal" in names(r.negative_signals)


def test_comprador_municipal_sin_proposito_de_seguridad_no_basta():
    r = score_seguridad_municipal(licitacion("Servicio de seguridad del parque", "MUNICIPALIDAD DE EJEMPLO"))
    assert not r.relevant


def test_camara_sola_no_suma():
    r = score_seguridad_municipal(licitacion("Cámara", ""))
    assert r.score == 0
    assert r.positive_signals == [] and r.negative_signals == []


# Mecánica del scorer

def test_titulo_pesa_mas_que_categoria():
    en_titulo = score_seguridad_municipal(licitacion("Televigilancia", ""))
    en_categoria = score_seguridad_municipal(licitacion("Compra", "", items=[("x", "y", "Televigilancia")]))
    assert en_titulo.score > en_categoria.score > 0


def test_cada_senal_cuenta_una_vez():
    una = score_seguridad_municipal(licitacion("Televigilancia", ""))
    repetida = score_seguridad_municipal(licitacion("Televigilancia televigilancia", "", "televigilancia"))
    assert una.score == repetida.score


def test_threshold_configurable_y_resultado_serializable():
    caso = licitacion("Sistema de televigilancia comunal", "MUNICIPALIDAD DE EJEMPLO")
    normal = score_seguridad_municipal(caso)
    estricto = score_seguridad_municipal(caso, threshold=100)
    assert normal.threshold == SEGURIDAD_MUNICIPAL.threshold
    assert normal.relevant and not estricto.relevant
    assert normal.score == estricto.score
    data = json.loads(json.dumps(normal.to_dict()))
    assert set(data) == {"score", "relevant", "threshold", "positive_signals", "negative_signals", "explanation"}
    assert "umbral" in data["explanation"]


def test_licitacion_con_campos_vacios():
    r = score_licitacion({"codigo_externo": "x", "items_json": "no es json"}, SEGURIDAD_MUNICIPAL)
    assert r.score == 0 and not r.relevant


def test_get_profile():
    assert get_profile("  Seguridad MUNICIPAL ") is SEGURIDAD_MUNICIPAL
    assert get_profile("aseo") is None


def test_combinaciones_referencian_senales_existentes():
    known = {s.name for s in SEGURIDAD_MUNICIPAL.signals} | {"comprador_municipal", "comprador_no_municipal"}
    for rule in SEGURIDAD_MUNICIPAL.combinations:
        for group in rule.requires:
            assert set(group) <= known, rule.name


# Anti-sobreajuste: las reglas no pueden depender de códigos ni de organismos concretos

def test_scorer_no_contiene_codigos_ni_nombres_del_ground_truth():
    source = Path(cr.__file__).read_text(encoding="utf-8").lower()
    labels = load_ground_truth(GROUND_TRUTH_FILES["seguridad municipal"])
    for codigo in labels:
        assert codigo.lower() not in source
    for lugar in ("punta arenas", "tilcoco", "mariquina", "hurtado"):
        assert lugar not in source
    assert not re.search(r"codigo_externo\s*==", source)
