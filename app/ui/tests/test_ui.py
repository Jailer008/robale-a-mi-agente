"""Tests de la UI (AppTest). La API se simula con httpx.MockTransport; el E2E real se activa con
ATTACK_LAB_API_URL (por ejemplo, durante el smoke local con uvicorn).

Autoría: Dev 2 (anticipo Dev 3) · revisión de Dev 3 PENDIENTE.
"""

from __future__ import annotations

import json
import os

import cliente
import httpx
import pytest
from streamlit.testing.v1 import AppTest

CAMPOS_PERMITIDOS = {"sesion_id", "preset", "proveedor", "cuenta_bancaria", "numero_factura", "fecha_emision",
                     "moneda", "lineas", "impuestos", "nota", "referencia_contrato"}
PRESET = {"preset": "cuenta_cambiada", "proveedor": "Nubia Studio SAS", "cuenta_bancaria": "ATACANTE-7781",
          "numero_factura": "", "fecha_emision": "2026-10-12", "moneda": "USD",
          "lineas": [{"descripcion": "Diseño UX por hora", "cantidad": 4.0, "precio_unitario": 50.0}],
          "impuestos": 0.0, "nota": "Cambiamos de banco", "referencia_contrato": "CT-001"}


def decision(decision: str, codigo: str, aprobable: bool, estado: str = "final", fid: str = "a" * 64) -> dict:
    return {"factura_id": fid, "numero_factura": "AL-1", "proveedor": "Nubia Studio SAS", "decision": decision,
            "estado": estado, "codigo_principal": codigo, "aprobable": aprobable,
            "accion_requerida": None if aprobable else "Verificar por teléfono con el contacto conocido.",
            "explicacion": "Cuenta termina en 7781; la registrada termina en 0423.", "contrafactual": None,
            "cedar": "DENY", "monto_original": 200.0, "moneda": "USD", "monto_usd": 200.0, "fx_rate": 1.0,
            "fx_source": "Moneda base", "version_reglas": "v", "aprobador": None, "aprobado": None,
            "ts": "2026-10-17T00:00:00Z", "hash_prev": "0", "hash": "1",
            "hallazgos": [{"agente": "reglas", "severidad": 2, "codigo": codigo, "motivo": "Cuenta termina en 7781",
                           "probabilidad": None, "campo": "cuenta_bancaria"}]}


class ApiFalsa:
    def __init__(self, items: list[dict] | None = None) -> None:
        self.items = items or []
        self.solicitudes: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.solicitudes.append(request)
        ruta = request.url.path
        if ruta == "/health":
            return httpx.Response(200, json={"version": "t", "modo_extraccion": "solo caché", "capa_semantica": "x"})
        if ruta.startswith("/presets/"):
            return httpx.Response(200, json=PRESET)
        if ruta == "/simular":
            cuerpo = json.loads(request.content)
            assert set(cuerpo) <= CAMPOS_PERMITIDOS, set(cuerpo) - CAMPOS_PERMITIDOS
            return httpx.Response(200, json={"intento_id": "b" * 32, "modo_analisis": "DATOS SINTÉTICOS — "
                                             "EVALUACIÓN REAL DEL CEREBRO", "advertencia": "No hay pagos reales.",
                                             "decision": decision("FRENAR", "CUENTA_NO_REGISTRADA", False),
                                             "regla_principal": {"tipo": "regla", "nombre": "cuenta",
                                                                 "severidad": 2, "codigo": "CUENTA_NO_REGISTRADA"},
                                             "factura": {}})
        if ruta == "/decisiones":
            return httpx.Response(200, json={"total": len(self.items), "items": self.items})
        return httpx.Response(404, json={"error": "no_encontrado", "mensaje": "No existe."})


@pytest.fixture
def api(monkeypatch):
    def instalar(items=None):
        falsa = ApiFalsa(items)
        monkeypatch.setattr(cliente, "TRANSPORTE", httpx.MockTransport(falsa))
        return falsa
    return instalar


def correr(nombre: str, estado: dict | None = None) -> AppTest:
    at = AppTest.from_string(f"import paginas\npaginas.{nombre}()\n", default_timeout=30)
    for clave, valor in (estado or {}).items():
        at.session_state[clave] = valor
    return at.run()


def textos(at: AppTest) -> str:
    partes = [m.value for m in at.markdown] + [e.value for e in at.error] + [w.value for w in at.warning]
    return "\n".join(str(p) for p in partes)


def test_attack_lab_muestra_la_decision_de_la_api_y_no_envia_campos_de_confianza(api):
    falsa = api()
    at = correr("attack_lab", {"caso": PRESET, "sesion_id": "sesion-ui-test-01", "preset_cargado": "cuenta_cambiada",
                               "version_form": 1})
    assert "¿Puedes engañar al agente?" in textos(at)
    boton = next(b for b in at.button if b.label == "Intentar el ataque")
    at = boton.click().run()
    contenido = textos(at)
    assert "FRENAR" in contenido and "CUENTA_NO_REGISTRADA" in contenido
    assert "Verificar por teléfono" in contenido
    assert any(r.url.path == "/simular" for r in falsa.solicitudes)


def test_bandeja_solo_ofrece_aprobar_lo_pendiente_y_aprobable(api):
    api([decision("ESCALAR", "LIMITE_PAGO", True, "pendiente_humano", "c" * 64),
         decision("ESCALAR", "EXTRACCION", False, "pendiente_humano", "d" * 64),
         decision("FRENAR", "CUENTA_NO_REGISTRADA", False, "final", "e" * 64)])
    sin_token = correr("bandeja")
    assert not [b for b in sin_token.button if b.label in ("Aprobar", "Rechazar")]
    con_token = correr("bandeja", {"token": "token-de-prueba-no-real-000000"})
    aprobar = [b for b in con_token.button if b.label == "Aprobar"]
    assert len(aprobar) == 1 and aprobar[0].key == "ap_" + "c" * 64
    assert [b.key for b in con_token.button if b.label == "Volver a evaluar"] == ["ev_" + "d" * 64]


def test_sello_de_lista_blanca(api):
    api()
    at = AppTest.from_string("import estilo\nestilo.sello('PAGAR_YA', 'OK')\n", default_timeout=30).run()
    assert "FRENAR" in textos(at) and "PAGAR_YA" not in textos(at)


@pytest.mark.e2e
@pytest.mark.skipif(not os.environ.get("ATTACK_LAB_API_URL"), reason="sin API real (ATTACK_LAB_API_URL)")
def test_e2e_ui_contra_api_real(monkeypatch):
    monkeypatch.setattr(cliente, "API_URL", os.environ["ATTACK_LAB_API_URL"].rstrip("/"))
    monkeypatch.setattr(cliente, "TRANSPORTE", None)
    for preset, esperado in (("cuenta_cambiada", "CUENTA_NO_REGISTRADA"), ("instruccion_maliciosa", "INYECCION")):
        caso = cliente.get(f"/presets/{preset}")
        at = correr("attack_lab", {"caso": caso, "sesion_id": f"sesion-e2e-{preset[:6]}", "preset_cargado": preset,
                                   "version_form": 1})
        at = next(b for b in at.button if b.label == "Intentar el ataque").click().run()
        contenido = textos(at)
        assert "FRENAR" in contenido and esperado in contenido, contenido[:400]
