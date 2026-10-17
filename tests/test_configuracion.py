"""Selección de extractores según las claves disponibles (sin leer el .env real)."""

from __future__ import annotations

import pytest

from extraccion import extractores_por_defecto, timeout_configurado

CLAVES = ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")


@pytest.fixture
def entorno(monkeypatch):
    for clave in CLAVES + ("EXTRACCION_TIMEOUT_S", "GEMINI_MODEL", "OPENAI_MODEL", "EXTRACTORES"):
        monkeypatch.delenv(clave, raising=False)
    return monkeypatch


def con_claves(entorno, *claves):
    for clave in claves:
        entorno.setenv(clave, "falsa")


def nombres(entorno) -> tuple[str, str]:
    a, b = extractores_por_defecto(cargar_env=False)
    return a.nombre, b.nombre


def test_con_las_tres_claves_a_es_openai_y_b_es_claude(entorno):
    con_claves(entorno, *CLAVES)
    assert nombres(entorno) == ("A:gpt-6-luna", "B:claude-haiku-5-5")


def test_sin_openai_a_es_claude_y_b_es_gemini(entorno):
    con_claves(entorno, "GEMINI_API_KEY", "ANTHROPIC_API_KEY")
    assert nombres(entorno) == ("A:claude-haiku-5-5", "B:gemini-3.8-flash")


def test_extractores_permite_elegir_el_orden(entorno):
    con_claves(entorno, *CLAVES)
    entorno.setenv("EXTRACTORES", "gemini, claude")
    assert nombres(entorno) == ("A:gemini-3.8-flash", "B:claude-haiku-5-5")


def test_extractores_ignora_nombres_desconocidos(entorno):
    con_claves(entorno, *CLAVES)
    entorno.setenv("EXTRACTORES", "mistral,openai,claude")
    assert nombres(entorno) == ("A:gpt-6-luna", "B:claude-haiku-5-5")


@pytest.mark.parametrize(
    "clave, esperado",
    [("GEMINI_API_KEY", "gemini-3.8-flash"), ("ANTHROPIC_API_KEY", "claude-haiku-5-5"),
     ("OPENAI_API_KEY", "gpt-6-luna")],
)
def test_con_un_solo_proveedor_b_es_una_relectura(entorno, clave, esperado):
    con_claves(entorno, clave)
    assert nombres(entorno) == (f"A:{esperado}", f"B-relectura:{esperado}")


def test_sin_claves_los_extractores_fallan_y_la_factura_escala(entorno):
    a, b = extractores_por_defecto(cargar_env=False)
    for extractor in (a, b):
        with pytest.raises(RuntimeError, match="falta"):
            extractor(None)


def test_timeout_por_defecto_y_configurable(entorno):
    assert timeout_configurado() == 45.0
    entorno.setenv("EXTRACCION_TIMEOUT_S", "30")
    assert timeout_configurado() == 30.0
    con_claves(entorno, *CLAVES)
    a, b = extractores_por_defecto(cargar_env=False)
    assert a.timeout_s == b.timeout_s == 25.0     # 5 s de margen para el orquestador


@pytest.mark.parametrize("valor", ["abc", "-3", "0"])
def test_timeout_invalido_usa_el_por_defecto(entorno, valor):
    entorno.setenv("EXTRACCION_TIMEOUT_S", valor)
    assert timeout_configurado() == 45.0
