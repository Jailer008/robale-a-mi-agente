"""Attack Lab · API FastAPI de punta a punta sobre el cerebro REAL (base temporal, sin red ni modelos).

Autoría: Dev 2 (anticipo del alcance de Dev 3) · revisión de Dev 3 PENDIENTE.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from conftest import DATOS
from fastapi.testclient import TestClient

from app.api import crear_app
from app.config import Ajustes
from app.servicios import Servicio
from cerebro import Cerebro
from cerebro.privacidad import CAMPOS_PUBLICOS

TOKEN_APROBADOR = "aprobador-token-de-prueba-0123456789"  # noqa: S105 - token falso de test
TOKEN_ADMIN = "admin-token-de-prueba-0123456789abcd"  # noqa: S105 - token falso de test
# Válido para la API, pero su identidad no está en CEREBRO_APROBADORES.
TOKEN_INTRUSO = "intruso-token-de-prueba-0123456789xx"  # noqa: S105 - token falso de test
APROBADOR = {"Authorization": f"Bearer {TOKEN_APROBADOR}"}
ADMIN = {"Authorization": f"Bearer {TOKEN_ADMIN}"}
COMPLETAS = ("ATACANTE-7781", "CO-BANCO-7781", "CO-BANCO-0423", "CO-BANCO-5555", "AR-BANCO-9015")


def _h(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


def nuevo_cliente(tmp_path, **ajustes) -> TestClient:
    motor = Cerebro(db_path=tmp_path / "demo.db", aprobadores=frozenset({"tg:111"}), exigir_aprobadores=True,
                    administradores=frozenset({"admin:ops"}), **ajustes.pop("motor", {}))
    base = dict(entrada=tmp_path / "entrada", origenes_cors=("http://localhost:8501",),
                tokens={_h(TOKEN_APROBADOR): ("tg:111", "aprobador"), _h(TOKEN_ADMIN): ("admin:ops", "admin"),
                        _h(TOKEN_INTRUSO): ("tg:999", "aprobador")})
    base.update(ajustes)
    return TestClient(crear_app(Servicio(Ajustes(**base), motor)))


@pytest.fixture
def cliente(tmp_path):
    return nuevo_cliente(tmp_path)


def caso(cliente, nombre: str, sesion: str = "sesion-prueba-001", **cambios) -> dict:
    datos = cliente.get(f"/presets/{nombre}").json()
    return {**datos, "sesion_id": sesion, **cambios}


def atacar(cliente, nombre: str, **cambios) -> dict:
    r = cliente.post("/simular", json=caso(cliente, nombre, **cambios))
    assert r.status_code == 200, r.text
    return r.json()


def sin_cuentas(texto: str) -> bool:
    return not any(c in texto for c in COMPLETAS)


# ---------- salud y presets ----------

def test_health_sin_secretos(cliente):
    r = cliente.get("/health")
    assert r.status_code == 200
    datos = r.json()
    assert datos["estado"] == "ok" and datos["revision_dev3"] == "pendiente" and datos["cadena_integra"] is True
    assert TOKEN_APROBADOR not in r.text and TOKEN_ADMIN not in r.text and "demo.db" not in r.text
    assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["X-Frame-Options"] == "DENY"


def test_presets(cliente):
    assert cliente.get("/presets").json()["presets"] == ["limpia", "cuenta_cambiada", "proveedor_nuevo",
                                                         "monto_inflado", "duplicado", "instruccion_maliciosa"]
    assert cliente.get("/presets/inventado").status_code == 422


# ---------- E2E: los ataques del jurado contra el cerebro real ----------

@pytest.mark.parametrize("nombre, decision, codigo, aprobable", [
    ("limpia", "PAGAR", "OK", False),
    ("cuenta_cambiada", "FRENAR", "CUENTA_NO_REGISTRADA", False),
    ("proveedor_nuevo", "FRENAR", "PROVEEDOR_NO_PERMITIDO", False),
    ("monto_inflado", "ESCALAR", "LIMITE_PAGO", True),
    ("duplicado", "FRENAR", "DUPLICADO_EXACTO", False),
    ("instruccion_maliciosa", "FRENAR", "INYECCION", False),
])
def test_ataques_de_punta_a_punta(cliente, nombre, decision, codigo, aprobable):
    r = atacar(cliente, nombre)
    d = r["decision"]
    assert (d["decision"], d["codigo_principal"], d["aprobable"]) == (decision, codigo, aprobable)
    assert r["modo_analisis"] == "DATOS SINTÉTICOS — EVALUACIÓN REAL DEL CEREBRO"
    assert r["regla_principal"]["codigo"] == codigo and "No hay pagos reales" in r["advertencia"]
    assert sin_cuentas(json.dumps(r, ensure_ascii=False))


def test_monto_absurdo_frena_por_tope_duro(cliente):
    datos = caso(cliente, "monto_inflado")
    datos["lineas"][0]["cantidad"] = 9_999_999
    d = cliente.post("/simular", json=datos).json()["decision"]
    assert (d["decision"], d["codigo_principal"], d["aprobable"]) == ("FRENAR", "TOPE_DURO", False)


def test_el_servidor_recalcula_la_aritmetica(cliente):
    datos = caso(cliente, "limpia")
    r = cliente.post("/simular", json=datos).json()
    lineas = r["factura"]["lineas"]
    assert all(abs(li["cantidad"] * li["precio_unitario"] - li["total"]) < 0.01 for li in lineas)
    assert abs(sum(li["total"] for li in lineas) + r["factura"]["impuestos"] - r["factura"]["total"]) < 0.01


@pytest.mark.parametrize("campo, valor", [
    ("extraccion_ok", True), ("texto_oculto", []), ("id_documento", "a" * 64), ("codigo_principal", "OK"),
    ("decision", "PAGAR"), ("aprobable", True), ("total", 1.0), ("diferencias", []),
])
def test_el_cliente_no_puede_inyectar_campos_de_confianza(cliente, campo, valor):
    datos = caso(cliente, "cuenta_cambiada", **{campo: valor})
    r = cliente.post("/simular", json=datos)
    assert r.status_code == 422 and r.json()["error"] == "datos_invalidos"
    assert "campo no permitido" in r.text
    assert cliente.get("/decisiones").json()["total"] == 0                      # no se decidió nada


@pytest.mark.parametrize("cambios", [
    {"moneda": "BTC"}, {"cuenta_bancaria": "<script>alert(1)</script>"}, {"fecha_emision": "1999-01-01"},
    {"lineas": []}, {"sesion_id": "x"}, {"impuestos": -5},
])
def test_validacion_en_espanol(cliente, cambios):
    r = cliente.post("/simular", json=caso(cliente, "limpia", **cambios))
    assert r.status_code == 422 and "Revisa los datos" in r.json()["mensaje"]


def test_contrato_json_igual_a_vista_publica(cliente):
    d = atacar(cliente, "monto_inflado")["decision"]
    assert set(d) == set(CAMPOS_PUBLICOS) | {"hallazgos"}
    assert set(d["hallazgos"][0]) == {"agente", "severidad", "codigo", "motivo", "probabilidad", "campo"}
    assert d["decision"] in ("PAGAR", "ESCALAR", "FRENAR") and d["cedar"] in ("ALLOW", "DENY")


def test_sesiones_distintas_no_se_pisan(cliente):
    a = atacar(cliente, "monto_inflado", sesion="sesion-jurado-a")["decision"]
    b = atacar(cliente, "monto_inflado", sesion="sesion-jurado-b")["decision"]
    assert a["factura_id"] != b["factura_id"]
    assert cliente.get("/decisiones").json()["total"] == 2


# ---------- aprobación: solo en el servidor y solo lo aprobable ----------

def test_aprobar_un_frenar_directo_por_api_se_rechaza(cliente):
    d = atacar(cliente, "cuenta_cambiada")["decision"]
    r = cliente.post(f"/aprobar/{d['factura_id']}", headers=APROBADOR)
    assert r.status_code == 409 and r.json()["error"] == "no_aprobable"
    assert r.json()["codigo"] == "CUENTA_NO_REGISTRADA" and r.json()["accion_requerida"]
    assert cliente.get("/verificar").json()["pagos_integros"] is True
    assert all(x["decision"] != "PAGAR" for x in cliente.get("/decisiones").json()["items"])


def test_aprobar_exige_token_y_rol(cliente):
    d = atacar(cliente, "monto_inflado")["decision"]
    assert cliente.post(f"/aprobar/{d['factura_id']}").status_code == 401
    assert cliente.post(f"/aprobar/{d['factura_id']}", headers={"Authorization": "Bearer falso"}).status_code == 401
    assert cliente.post(f"/aprobar/{d['factura_id']}", headers={"X-Aprobador": "tg:111"}).status_code == 401
    assert cliente.post(f"/aprobar/{d['factura_id']}", headers=ADMIN).status_code == 403
    intruso = cliente.post(f"/aprobar/{d['factura_id']}", headers={"Authorization": f"Bearer {TOKEN_INTRUSO}"})
    assert intruso.status_code == 403                                           # el cerebro no lo autoriza


def test_aprobar_lo_aprobable_paga_una_sola_vez(cliente):
    d = atacar(cliente, "monto_inflado")["decision"]
    primera = cliente.post(f"/aprobar/{d['factura_id']}", headers={**APROBADOR, "Idempotency-Key": "cb-001"})
    assert primera.status_code == 200 and primera.json()["decision"] == "PAGAR"
    misma = cliente.post(f"/aprobar/{d['factura_id']}", headers={**APROBADOR, "Idempotency-Key": "cb-001"})
    assert misma.status_code == 200 and misma.json()["hash"] == primera.json()["hash"]       # idempotente
    segunda = cliente.post(f"/aprobar/{d['factura_id']}", headers=APROBADOR)
    assert segunda.status_code == 409                                            # doble aprobación
    assert cliente.get("/verificar").json() == {"integra": True, "fila_rota": None, "pagos_integros": True}


def test_rechazar(cliente):
    d = atacar(cliente, "monto_inflado")["decision"]
    r = cliente.post(f"/rechazar/{d['factura_id']}", headers=APROBADOR)
    assert r.status_code == 200 and r.json()["decision"] == "FRENAR" and r.json()["aprobado"] is False


def test_extraccion_incierta_escala_no_aprobable(cliente):
    contenido = (DATOS / "facturas" / "15_borrosa.jpg").read_bytes()
    r = cliente.post("/ingest", files={"archivo": ("../../foto.jpg", contenido, "image/jpeg")},
                     data={"canal": "telegram"})
    assert r.status_code == 200, r.text
    d = r.json()["decision"]
    assert (d["decision"], d["codigo_principal"], d["aprobable"]) == ("ESCALAR", "EXTRACCION", False)
    assert r.json()["fuente_extraccion"] == "CACHÉ" and "CACHÉ" in r.json()["modo_analisis"]
    aprobar = cliente.post(f"/aprobar/{d['factura_id']}", headers=APROBADOR)
    assert aprobar.status_code == 409 and aprobar.json()["error"] == "no_aprobable"


def test_jev_caido_no_aprobable_hasta_reevaluar(tmp_path):
    from cerebro.semantica import CapaJev

    estado = {"caido": True}

    def transporte(url, cuerpo, cabeceras, timeout_s):
        if estado["caido"]:
            return 503, b'{"error": {"code": 503, "message": "Service temporarily unavailable"}}'
        q = json.loads(cuerpo)["questions"]["respuesta"]
        respuesta = ({"type": "noul", "noul": 0.01} if q["type"] == "noul" else
                     {"type": "choice", "choice": "ninguno", "probabilities": {o: 0.5 for o in q["criteria"]}})
        return 200, json.dumps({"model": "typesafe/jev-1.13-x", "answers": {"respuesta": respuesta},
                                "usage": {"input_tokens": 1, "output_tokens": 0, "cost": 0.0}}).encode()

    c = nuevo_cliente(tmp_path, motor={"capa": CapaJev(clave="clave-de-prueba", transporte=transporte)})
    d = atacar(c, "monto_inflado")["decision"]
    assert (d["decision"], d["codigo_principal"], d["aprobable"]) == ("ESCALAR", "ERROR_TECNICO", False)
    assert c.post(f"/aprobar/{d['factura_id']}", headers=APROBADOR).status_code == 409
    assert c.post(f"/reevaluar/{d['factura_id']}").status_code == 401
    estado["caido"] = False
    nueva = c.post(f"/reevaluar/{d['factura_id']}", headers=APROBADOR).json()
    assert (nueva["decision"], nueva["codigo_principal"], nueva["aprobable"]) == ("ESCALAR", "LIMITE_PAGO", True)
    assert c.post(f"/aprobar/{d['factura_id']}", headers=APROBADOR).json()["decision"] == "PAGAR"


# ---------- archivos ----------

@pytest.mark.parametrize("nombre, contenido, status", [
    ("factura.exe", b"MZ\x90\x00", 415),
    ("factura.pdf", b"esto no es un pdf", 415),
    ("factura.txt", b"\x00\x01\x02", 415),
    ("factura.pdf", b"", 400),
])
def test_archivos_invalidos(cliente, nombre, contenido, status):
    r = cliente.post("/ingest", files={"archivo": (nombre, contenido)}, data={"canal": "web"})
    assert r.status_code == status and r.json()["error"] == "archivo_invalido"


def test_archivo_demasiado_grande(tmp_path):
    c = nuevo_cliente(tmp_path, max_upload_bytes=1024)
    r = c.post("/ingest", files={"archivo": ("f.pdf", b"%PDF-" + b"0" * 2048)}, data={"canal": "web"})
    assert r.status_code == 413


def test_documento_nuevo_sin_extraccion_live_escala_honesto(cliente, tmp_path):
    r = cliente.post("/ingest", files={"archivo": ("chat.txt", b"Factura NUEVA-1 por USD 100 de Nubia")},
                     data={"canal": "chat"})
    assert r.status_code == 200
    d = r.json()["decision"]
    assert d["decision"] == "ESCALAR" and d["aprobable"] is False
    assert r.json()["fuente_extraccion"] == "SIN_EXTRACCION" and "no está autorizada" in r.json()["modo_analisis"]
    guardados = list((tmp_path / "entrada").iterdir())
    esperado = hashlib.sha256(b"Factura NUEVA-1 por USD 100 de Nubia").hexdigest()
    assert len(guardados) == 1 and guardados[0].name == f"{esperado}.txt"


# ---------- cuotas, CORS y lectura ----------

def test_cuota_por_sesion_con_mensaje_en_espanol(tmp_path):
    c = nuevo_cliente(tmp_path, simular_por_hora_sesion=2)
    assert c.post("/simular", json=caso(c, "duplicado")).status_code == 200
    assert c.post("/simular", json=caso(c, "duplicado")).status_code == 200
    r = c.post("/simular", json=caso(c, "duplicado"))
    assert r.status_code == 429 and "Demasiados intentos" in r.json()["mensaje"]


def test_cors_estricto(cliente):
    permitido = cliente.options("/simular", headers={"Origin": "http://localhost:8501",
                                                     "Access-Control-Request-Method": "POST"})
    assert permitido.headers.get("access-control-allow-origin") == "http://localhost:8501"
    ajeno = cliente.options("/simular", headers={"Origin": "https://evil.example",
                                                 "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in ajeno.headers


def test_decisiones_paginadas_y_enmascaradas(cliente):
    for nombre in ("cuenta_cambiada", "proveedor_nuevo", "monto_inflado"):
        atacar(cliente, nombre)
    pagina = cliente.get("/decisiones?limite=2").json()
    assert pagina["total"] == 3 and len(pagina["items"]) == 2
    assert all(x["origen"] for x in pagina["items"])
    assert sin_cuentas(json.dumps(cliente.get("/decisiones").json(), ensure_ascii=False))
    assert cliente.get("/decisiones?limite=1000").status_code == 422


def test_eventos_solo_verdaderos(cliente):
    d = atacar(cliente, "instruccion_maliciosa")["decision"]
    ev = cliente.get(f"/eventos/{d['factura_id']}").json()
    assert ev["estado"] == "listo"
    agentes = [e["agente"] for e in ev["eventos"]]
    assert agentes[:5] == ["duplicados", "contrato", "beneficiario", "seguridad", "presupuesto"]
    seguridad = next(e for e in ev["eventos"] if e["agente"] == "seguridad")
    assert seguridad["severidad"] == 2 and seguridad["probabilidad"] is None      # sin capa semántica: no se inventa
    assert cliente.get("/eventos/" + "f" * 64).status_code == 404
    assert cliente.get("/eventos/../../etc").status_code == 404


def test_evidencia_publica_restringida_y_completa_para_operador(cliente):
    d = atacar(cliente, "cuenta_cambiada")["decision"]
    publica = cliente.get(f"/evidencia/{d['factura_id']}").json()
    assert publica["acceso"] == "publico" and "reglas" not in publica and "eventos" not in publica
    assert publica["factura"]["cuenta_enmascarada"] == "****7781"
    assert publica["regla_principal"]["codigo"] == "CUENTA_NO_REGISTRADA"
    completa = cliente.get(f"/evidencia/{d['factura_id']}", headers=APROBADOR).json()
    assert completa["acceso"] == "operador" and "reglas" in completa
    assert sin_cuentas(json.dumps(publica, ensure_ascii=False))
    assert sin_cuentas(json.dumps(completa, ensure_ascii=False))


def test_reglas_solo_lectura_y_politica_sin_efectos(cliente):
    reglas = cliente.get("/reglas").json()
    assert reglas["solo_lectura"] is True and reglas["limites"]["limite_pago_usd"] == "5.000,00"
    assert sin_cuentas(json.dumps(reglas, ensure_ascii=False))
    d = atacar(cliente, "monto_inflado")["decision"]
    antes = cliente.get("/decisiones").json()["total"]
    sim = cliente.post("/politica/simular", json={"factura_id": d["factura_id"],
                                                  "cambios": {"limite_pago_usd": 8000}}).json()
    assert sim["modo"] == "SANDBOX" and sim["simulada"]["decision"] == "PAGAR"
    assert cliente.get("/decisiones").json()["total"] == antes
    assert cliente.post("/politica/simular", json={"factura_id": d["factura_id"],
                                                   "cambios": {"inventado": 1}}).status_code == 400


def test_metricas_mock_etiquetadas(cliente):
    m = cliente.get("/metricas?modo=mock").json()
    assert m["modo"] == "MOCK" and m["ground_truth"] == "v2"
    assert m["resumen"]["aciertos"] == 15 and m["resumen"]["falsos_pagar"] == 0
    assert m["costo"]["usd_total"] is None
    assert cliente.get("/metricas?modo=live").status_code == 422


# ---------- paquete del jurado, reinicio y persistencia ----------

def test_paquete_del_jurado_reproducible_y_sin_pagos(cliente):
    assert cliente.post("/paquete-jurado").status_code == 401
    primero = cliente.post("/paquete-jurado", headers=APROBADOR).json()["resultados"]
    assert [x["numero"] for x in primero] == ["07", "08", "10", "11", "12", "14"]
    assert all(x["decision"]["decision"] != "PAGAR" for x in primero)
    segundo = cliente.post("/paquete-jurado", headers=APROBADOR).json()["resultados"]
    assert [x["decision"]["hash"] for x in primero] == [x["decision"]["hash"] for x in segundo]
    assert cliente.get("/decisiones").json()["total"] == 6


def test_reinicio_solo_admin_y_restaura(cliente):
    atacar(cliente, "limpia")
    assert cliente.post("/admin/reiniciar-demo").status_code == 401
    assert cliente.post("/admin/reiniciar-demo", headers=APROBADOR).status_code == 403
    r = cliente.post("/admin/reiniciar-demo", headers=ADMIN)
    assert r.status_code == 200 and r.json()["decisiones"] == 0 and r.json()["saldo_inicial_usd"] == "8600.00"
    assert cliente.get("/decisiones").json()["total"] == 0


def test_persistencia_entre_reinicios_del_proceso(tmp_path):
    d = atacar(nuevo_cliente(tmp_path), "monto_inflado")["decision"]
    otro = nuevo_cliente(tmp_path)                                               # "reinicio" del proceso API
    assert otro.get("/decisiones").json()["items"][0]["factura_id"] == d["factura_id"]
    assert otro.post(f"/aprobar/{d['factura_id']}", headers=APROBADOR).json()["decision"] == "PAGAR"
