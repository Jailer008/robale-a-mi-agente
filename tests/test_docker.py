"""Guardas estáticas de las imágenes Docker (Docker no siempre está disponible para construirlas).

Si la API importa un módulo de app/ que el Dockerfile no copia, o falta una librería de sistema que
WeasyPrint necesita para dibujar las facturas falsificadas, la imagen no arranca.
"""

from __future__ import annotations

import re

from conftest import RAIZ

API = (RAIZ / "docker" / "api.Dockerfile").read_text(encoding="utf-8")


def test_la_imagen_de_la_api_copia_todos_los_modulos_de_app():
    copiados = set(re.findall(r"app/(\w+\.py)", API))
    modulos = {p.name for p in (RAIZ / "app").glob("*.py")}
    assert modulos <= copiados, f"faltan en api.Dockerfile: {sorted(modulos - copiados)}"


def test_la_imagen_de_la_api_trae_lo_que_weasyprint_necesita():
    for paquete in ("libpango-1.0-0", "libpangoft2-1.0-0", "libharfbuzz-subset0", "fonts-dejavu-core"):
        assert paquete in API, paquete


def test_la_imagen_trae_las_bases_y_la_plantilla_del_modo_en_vivo():
    assert re.search(r"^COPY datos \./datos$", API, re.M), "datos/ (base/ y plantillas/) debe copiarse completo"


def test_la_imagen_de_la_ui_copia_su_configuracion_de_streamlit():
    ui = (RAIZ / "docker" / "ui.Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^COPY app/ui/\.streamlit \./\.streamlit$", ui, re.M)
