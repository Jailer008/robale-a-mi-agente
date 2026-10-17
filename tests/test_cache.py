from __future__ import annotations

from extraccion.cache import CacheExtracciones, con_cache
from extraccion.ingesta import Documento
from extraccion.modelo import CamposExtraidos
from fakes import ExtractorFalso

DOC = Documento(id_documento="a" * 64, archivo="x.pdf", tipo="pdf")
CAMPOS = CamposExtraidos(proveedor="Nubia Studio SAS", total=200.0)


def test_ida_y_vuelta(tmp_path):
    cache = CacheExtracciones(tmp_path)
    assert cache.leer(DOC.id_documento, "A:gemini") is None
    cache.escribir(DOC.id_documento, "A:gemini", CAMPOS)
    assert cache.leer(DOC.id_documento, "A:gemini") == CAMPOS
    assert cache.leer(DOC.id_documento, "B:claude") is None


def test_entrada_corrupta_es_un_fallo_de_cache(tmp_path):
    cache = CacheExtracciones(tmp_path)
    cache.escribir(DOC.id_documento, "A:gemini", CAMPOS)
    for archivo in tmp_path.iterdir():
        archivo.write_text("{roto", encoding="utf-8")
    assert cache.leer(DOC.id_documento, "A:gemini") is None


def test_nombre_de_archivo_seguro(tmp_path):
    cache = CacheExtracciones(tmp_path)
    cache.escribir(DOC.id_documento, "B:../../evil", CAMPOS)
    assert all(p.parent == tmp_path for p in tmp_path.rglob("*.json"))


def test_con_cache_llama_al_modelo_una_sola_vez(tmp_path):
    falso = ExtractorFalso("A:gemini", por_defecto=CAMPOS)
    envuelto = con_cache(falso, CacheExtracciones(tmp_path))
    assert envuelto.nombre == "A:gemini"
    assert envuelto(DOC) == CAMPOS
    assert envuelto(DOC) == CAMPOS
    assert falso.llamadas == [DOC.id_documento]


def test_con_cache_no_guarda_errores(tmp_path):
    falso = ExtractorFalso("A:gemini", por_defecto=RuntimeError("caído"))
    envuelto = con_cache(falso, CacheExtracciones(tmp_path))
    for _ in range(2):
        try:
            envuelto(DOC)
        except RuntimeError:
            pass
    assert len(falso.llamadas) == 2
    assert list(tmp_path.glob("*.json")) == []
