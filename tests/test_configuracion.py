"""Selección de extractores según las claves disponibles (sin leer el .env real)."""

from __future__ import annotations

import pytest

from extraccion import extractores_por_defecto, timeout_configurado


@pytest.fixture
def entorno(monkeypatch):
    for clave in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "EXTRACCION_TIMEOUT_S", "GEMINI_MODEL"):
        monkeypatch.delenv(clave, raising=False)
    return monkeypatch


def test_con_ambas_claves_a_es_gemini_y_b_es_claude(entorno):
    entorno.setenv("GEMINI_API_KEY", "falsa")
    entorno.setenv("ANTHROPIC_API_KEY", "falsa")
    a, b = extractores_por_defecto(cargar_env=False)
    assert a.nombre.startswith("A:gemini") and b.nombre == "B:claude-haiku-5-5"


def test_sin_anthropic_b_es_relectura_con_gemini(entorno):
    entorno.setenv("GEMINI_API_KEY", "falsa")
    _, b = extractores_por_defecto(cargar_env=False)
    assert b.nombre.startswith("B-relectura:gemini")


def test_sin_claves_los_extractores_fallan_y_la_factura_escala(entorno):
    a, b = extractores_por_defecto(cargar_env=False)
    for extractor in (a, b):
        with pytest.raises(RuntimeError, match="falta"):
            extractor(None)


def test_timeout_por_defecto_y_configurable(entorno):
    assert timeout_configurado() == 45.0
    entorno.setenv("EXTRACCION_TIMEOUT_S", "30")
    assert timeout_configurado() == 30.0
    entorno.setenv("GEMINI_API_KEY", "falsa")
    entorno.setenv("ANTHROPIC_API_KEY", "falsa")
    a, b = extractores_por_defecto(cargar_env=False)
    assert a.timeout_s == b.timeout_s == 25.0     # 5 s de margen para el orquestador


@pytest.mark.parametrize("valor", ["abc", "-3", "0"])
def test_timeout_invalido_usa_el_por_defecto(entorno, valor):
    entorno.setenv("EXTRACCION_TIMEOUT_S", valor)
    assert timeout_configurado() == 45.0
