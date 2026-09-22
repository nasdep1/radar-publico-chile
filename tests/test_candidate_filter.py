from src.services.candidate_filter import filter_candidates
from src.services.normalizer import normalize_list_item

TERMS = ["seguridad", "cámara", "camaras", "televigilancia", "cctv", "patrullaje", "alarma"]


def licitacion(codigo, nombre):
    return normalize_list_item({"CodigoExterno": codigo, "Nombre": nombre})


def test_camaras_de_televigilancia_coincide_con_camaras():
    result = filter_candidates([licitacion("1", "CÁMARAS DE TELEVIGILANCIA")], ["camaras"])
    assert result.total_candidatas == 1
    assert result.coincidencias["1"] == ["camaras"]


def test_termino_con_tilde_coincide_con_nombre_sin_tilde():
    result = filter_candidates([licitacion("1", "Compra de camaras IP")], ["cámara"])
    assert result.total_candidatas == 1


def test_termino_coincide_como_inicio_de_palabra():
    listado = [licitacion("1", "Sistema de alarmas comunitarias"), licitacion("2", "Servicio XCCTV")]
    result = filter_candidates(listado, ["alarma", "cctv"])
    assert [c["codigo_externo"] for c in result.candidatas] == ["1"]


def test_espacios_multiples_en_nombre_y_termino():
    result = filter_candidates([licitacion("1", "Plan de  PREVENCIÓN   DEL DELITO")], ["prevencion del  delito"])
    assert result.total_candidatas == 1


def test_resultado_con_totales():
    listado = [
        licitacion("1", "ADQUISICIÓN DE CÁMARAS DE SEGURIDAD"),
        licitacion("2", "Compra de papel"),
        licitacion("3", "Servicio de patrullaje preventivo"),
        licitacion("4", None),
    ]
    result = filter_candidates(listado, TERMS)
    assert result.total_revisadas == 4
    assert result.total_candidatas == 2
    assert [c["codigo_externo"] for c in result.candidatas] == ["1", "3"]
    assert result.coincidencias["1"] == ["seguridad", "camara", "camaras"]


def test_acepta_registros_crudos_de_la_api():
    result = filter_candidates([{"CodigoExterno": "1", "Nombre": "Cámaras CCTV"}], ["cctv"])
    assert result.total_candidatas == 1


def test_sin_terminos_o_listado_vacio():
    assert filter_candidates([licitacion("1", "Cámaras")], []).total_candidatas == 0
    result = filter_candidates([], TERMS)
    assert (result.total_revisadas, result.total_candidatas) == (0, 0)
