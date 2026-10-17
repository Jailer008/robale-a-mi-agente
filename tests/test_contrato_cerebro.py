"""Contrato público del cerebro para Dev 3 (app/API/UI/bot). Sin APIs externas ni claves.

    uv run pytest tests/test_contrato_cerebro.py -q

Si alguno falla, la integración de Dev 3 puede romperse: avisar a Dev 2 antes de tocar nada.
"""

from __future__ import annotations

import inspect
import re
import sqlite3

import pytest
from cerebro_util import factura, nueva_cerebro
from conftest import RAIZ

import cerebro
from cerebro.medir import Resultados
from cerebro.tipos import FALLO_TECNICO, SIN_EVIDENCIA
from schemas import Decision, Hallazgo

README = (RAIZ / "cerebro" / "README.md").read_text(encoding="utf-8")


def test_funciones_publicas_y_firmas():
    esperadas = {
        "decidir": ["factura"],
        "decidir_async": ["factura"],
        "reanudar": ["factura_id", "aprobado", "aprobador", "clave_idempotencia"],
        "verificar_cadena": [],
        "paquete_evidencia": ["factura_id"],
        "simular_politica": ["factura", "cambios"],
    }
    for nombre, parametros in esperadas.items():
        assert nombre in cerebro.__all__
        assert list(inspect.signature(getattr(cerebro, nombre)).parameters) == parametros, nombre
    assert inspect.iscoroutinefunction(cerebro.decidir_async)


def test_errores_documentados():
    assert issubclass(cerebro.CadenaAlterada, RuntimeError)
    assert issubclass(cerebro.ReevaluacionNecesaria, RuntimeError)
    for nombre in ("LookupError", "ValueError", "PermissionError", "CadenaAlterada", "ReevaluacionNecesaria"):
        assert nombre in README


def test_estructura_de_decision_y_hallazgo_documentada():
    for campo in Decision.model_fields:
        assert f"`{campo}`" in README, campo
    for campo in Hallazgo.model_fields:
        assert f"`{campo}`" in README, campo
    assert FALLO_TECNICO in README and SIN_EVIDENCIA in README


def test_columnas_de_eventos(tmp_path):
    c = nueva_cerebro(tmp_path)
    c.decidir(factura("14"))
    with sqlite3.connect(c.db.ruta) as con:
        columnas = [fila[1] for fila in con.execute("PRAGMA table_info(eventos)")]
    assert columnas == ["id", "factura_id", "decision_id", "agente", "severidad", "probabilidad", "latencia_ms",
                        "motivo", "ts", "tipo"]
    for columna in columnas:
        assert f"`{columna}`" in README, columna


def test_contrato_de_resultados_json_documentado():
    for campo in Resultados.model_fields:
        assert f"`{campo}`" in README, campo


def test_variables_de_entorno_documentadas():
    leidas = set()
    for ruta in (RAIZ / "cerebro").rglob("*.py"):
        leidas |= set(re.findall(r"os\.environ\.get\(\s*[\"']([A-Z_]+)[\"']", ruta.read_text(encoding="utf-8")))
    leidas |= {"CEREBRO_APROBADORES", "TELEGRAM_APROBADORES"}
    assert leidas >= {"DB_PATH", "REF_DATE", "SIGNING_KEY_PATH", "CEREBRO_SEMANTICA"}
    for variable in leidas:
        assert f"`{variable}`" in README, variable


def test_decidir_nunca_lanza_con_una_factura_ilegible(tmp_path):
    from extraccion.ensamblar import factura_vacia

    vacia = factura_vacia("", "entrada/roto.pdf", "telegram", ["No se pudo leer el archivo"])
    d = nueva_cerebro(tmp_path).decidir(vacia)
    assert d.decision == "ESCALAR" and d.factura_id.startswith("sin-hash-")


def test_ejemplo_de_integracion_end_to_end(tmp_path):
    """El mismo flujo que muestra el README, con extracción desde la caché y sin red."""
    from extraccion import extraer
    from extraccion.cache import CacheExtracciones

    class SoloCache:
        def __init__(self, nombre):
            self.nombre = nombre

        def __call__(self, doc):
            raise RuntimeError("sin red en este test")

    c = nueva_cerebro(tmp_path, aprobadores=frozenset({"tg:111"}))
    f = extraer(RAIZ / "datos/facturas/12_monto_alto.pdf", "web", extractor_a=SoloCache("A:gpt-6-luna"),
                extractor_b=SoloCache("B:claude-haiku-5-5"), cache=CacheExtracciones(RAIZ / "cache"))
    d = c.decidir(f)
    assert (d.decision, d.estado) == ("ESCALAR", "pendiente_humano")
    assert c.simular_politica(d.factura_id, {"limite_pago_usd": 8000})["simulada"]["decision"] == "PAGAR"
    with pytest.raises(PermissionError):
        c.reanudar(d.factura_id, True, "tg:999")
    aprobada = c.reanudar(d.factura_id, True, "tg:111", clave_idempotencia="cb-1")
    assert aprobada.decision == "PAGAR" and aprobada.aprobador == "tg:111"
    assert c.verificar_cadena() == (True, None)
    assert c.paquete_evidencia(d.factura_id)["autoridad_humana"] == {"aprobador": "tg:111", "aprobado": True}
    # El sandbox evalúa contra el estado ACTUAL: ya pagada, la misma factura es un duplicado exacto.
    despues = c.simular_politica(d.factura_id, {"limite_pago_usd": 8000})
    assert despues["simulada"]["decision"] == "FRENAR"
    assert any("Duplicado exacto" in h for h in despues["simulada"]["hallazgos"])


def test_readme_explica_lo_simulado_y_lo_no_validado():
    for frase in ("SIMULAD", "SIN VALIDAR", "MOCK", "CACHÉ", "LIVE", "pendiente_humano"):
        assert frase in README.upper() or frase in README, frase
