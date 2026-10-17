"""Dev 2 · G3: firma Ed25519, paquete de evidencia y aprobación humana segura."""

from __future__ import annotations

import sqlite3
import threading

import pytest
from cerebro_util import factura, nueva_cerebro
from conftest import RAIZ

import cerebro
from cerebro import CadenaAlterada, ReevaluacionNecesaria
from cerebro.agentes import AGENTES
from cerebro.firma import Firmante
from cerebro.semantica import INSTRUCCIONES, CapaFija


def pagos_simulados(c) -> int:
    with c.db.transaccion() as con:
        return con.execute("SELECT COUNT(*) FROM pagos WHERE origen='simulado'").fetchone()[0]


def filas(c) -> int:
    with c.db.transaccion() as con:
        return con.execute("SELECT COUNT(*) FROM decision_log").fetchone()[0]


def _en_paralelo(funciones):
    barrera = threading.Barrier(len(funciones))
    resultados: list = [None] * len(funciones)

    def correr(i, fn):
        barrera.wait()
        try:
            resultados[i] = fn()
        except Exception as error:      # noqa: BLE001 - el test inspecciona el tipo
            resultados[i] = error

    hilos = [threading.Thread(target=correr, args=(i, fn)) for i, fn in enumerate(funciones)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=60)
    return resultados


# ---------- firma Ed25519 ----------

def test_clave_se_crea_fuera_del_repo_y_se_recarga(tmp_path):
    ruta = tmp_path / "claves" / "firma.pem"
    primera = Firmante.desde_archivo(ruta)
    assert ruta.read_text().startswith("-----BEGIN PRIVATE KEY-----")
    assert Firmante.desde_archivo(ruta).huella == primera.huella
    assert "*.pem" in (RAIZ / ".gitignore").read_text(encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        Firmante.desde_archivo(tmp_path / "no.pem", crear=False)


def test_cada_fila_queda_firmada_y_verificada(tmp_path):
    firmante = Firmante.generar()
    c = nueva_cerebro(tmp_path, firmante=firmante)
    d = c.decidir(factura("01"))
    with c.db.transaccion() as con:
        firma, huella = con.execute("SELECT firma, clave_firma FROM decision_log").fetchone()
    assert huella == firmante.huella and firmante.verificar(d.hash, firma)
    assert c.verificar_cadena() == (True, None)


def test_firma_alterada_rompe_la_cadena(tmp_path):
    c = nueva_cerebro(tmp_path, firmante=Firmante.generar())
    for n in ["01", "12", "13"]:
        c.decidir(factura(n))
    with sqlite3.connect(c.db.ruta) as con:
        con.execute("UPDATE decision_log SET firma = ? WHERE id = 2", ("00" * 64,))
    assert c.verificar_cadena() == (False, 2)


def test_otra_clave_no_valida_las_firmas(tmp_path):
    nueva_cerebro(tmp_path, firmante=Firmante.generar()).decidir(factura("01"))
    intruso = nueva_cerebro(tmp_path, firmante=Firmante.generar())
    assert intruso.verificar_cadena() == (False, 1)


def test_filas_sin_firmar_no_pasan_con_clave(tmp_path):
    nueva_cerebro(tmp_path).decidir(factura("01"))
    assert nueva_cerebro(tmp_path, firmante=Firmante.generar()).verificar_cadena() == (False, 1)


def test_no_se_aprueba_con_firma_invalida(tmp_path):
    c = nueva_cerebro(tmp_path, firmante=Firmante.generar())
    pendiente = c.decidir(factura("12"))
    with sqlite3.connect(c.db.ruta) as con:
        con.execute("UPDATE decision_log SET firma = ? WHERE id = 1", ("ab" * 64,))
    with pytest.raises(CadenaAlterada):
        c.reanudar(pendiente.factura_id, True, "jurado-1")
    assert pagos_simulados(c) == 0


# ---------- paquete de evidencia ----------

def test_evidencia_reconstruye_decision_y_resolucion_humana(tmp_path):
    c = nueva_cerebro(tmp_path, firmante=Firmante.generar())
    pendiente = c.decidir(factura("12"))
    c.reanudar(pendiente.factura_id, True, "jurado-1")
    antes = filas(c)
    p = c.paquete_evidencia(pendiente.factura_id)
    assert filas(c) == antes                                      # leer no escribe
    assert [x["decision"]["decision"] for x in p["decisiones"]] == ["ESCALAR", "PAGAR"]
    assert p["decisiones"][0]["decision"]["estado"] == "pendiente_humano"     # la evidencia original se conserva
    assert p["decisiones"][0]["responsable"] == {"tipo": "regla", "nombre": "limite_pago", "severidad": 1,
                                                  "motivo": pendiente.explicacion, "evidencia": "regla=limite_pago",
                                                  "campo": "total"}
    assert p["autoridad_humana"] == {"aprobador": "jurado-1", "aprobado": True}
    assert p["responsable"]["tipo"] == "humano"
    assert "limite_pago_usd: 5000" in p["reglas"][pendiente.version_reglas]
    assert p["factura"]["numero_factura"] == "QL-1109"
    assert p["documento_original"] == {"archivo": "datos/facturas/12_monto_alto.pdf",
                                       "sha256_esperado": pendiente.factura_id, "encontrado": True, "coincide": True}
    assert p["cadena"]["integra"] is True and p["cadena"]["firmada"] is True
    assert all(x["firma"]["valida"] for x in p["decisiones"])
    assert p["pago_simulado"]["monto_usd_cents"] == 740000
    assert "SIMULAD" in p["advertencia"].upper()
    assert p["decision_final"]["fx_rate"] == 1.0 and p["decision_final"]["ts"]


@pytest.mark.parametrize("n, tipo, nombre", [("14", "agente", "seguridad"), ("07", "agente", "duplicados"),
                                              ("13", "regla", "saldo"), ("01", "reglas", "politica")])
def test_responsable_del_veto(tmp_path, n, tipo, nombre):
    c = nueva_cerebro(tmp_path)
    d = c.decidir(factura(n))
    responsable = c.paquete_evidencia(d.factura_id)["responsable"]
    assert (responsable["tipo"], responsable["nombre"]) == (tipo, nombre)


def test_evidencia_de_factura_inexistente(tmp_path):
    with pytest.raises(LookupError):
        nueva_cerebro(tmp_path).paquete_evidencia("no-existe")


def test_evidencia_informa_cadena_rota(tmp_path):
    c = nueva_cerebro(tmp_path)
    d = c.decidir(factura("09"))
    with sqlite3.connect(c.db.ruta) as con:
        con.execute("UPDATE decision_log SET decision='PAGAR'")
    assert c.paquete_evidencia(d.factura_id)["cadena"] == {"integra": False, "fila_rota": 1, "firmada": False,
                                                           "clave_publica": None}


# ---------- aprobación humana segura ----------

def test_idempotencia_con_clave(tmp_path):
    c = nueva_cerebro(tmp_path)
    pendiente = c.decidir(factura("12"))
    primera = c.reanudar(pendiente.factura_id, True, "jurado-1", clave_idempotencia="tg-cb-1")
    segunda = c.reanudar(pendiente.factura_id, True, "jurado-1", clave_idempotencia="tg-cb-1")
    assert primera.hash == segunda.hash and primera.decision == "PAGAR"
    assert pagos_simulados(c) == 1
    with pytest.raises(ValueError):
        c.reanudar(pendiente.factura_id, False, "jurado-1", clave_idempotencia="tg-cb-1")


def test_doble_aprobacion_concurrente_paga_una_vez(tmp_path):
    c = nueva_cerebro(tmp_path)
    pendiente = c.decidir(factura("12"))
    resultados = _en_paralelo([lambda: c.reanudar(pendiente.factura_id, True, "jurado-1")] * 6)
    decisiones = [r for r in resultados if not isinstance(r, Exception)]
    assert [d.decision for d in decisiones] == ["PAGAR"]
    assert all(isinstance(r, ValueError) for r in resultados if isinstance(r, Exception))
    assert pagos_simulados(c) == 1 and c.verificar_cadena() == (True, None)


def test_doble_aprobacion_concurrente_con_la_misma_clave(tmp_path):
    c = nueva_cerebro(tmp_path)
    pendiente = c.decidir(factura("12"))
    resultados = _en_paralelo([lambda: c.reanudar(pendiente.factura_id, True, "jurado-1",
                                                  clave_idempotencia="tg-42")] * 6)
    assert len({r.hash for r in resultados}) == 1 and pagos_simulados(c) == 1


def test_fallo_tecnico_al_aprobar_exige_reevaluar_y_sigue_pendiente(tmp_path):
    estado = {"roto": False}

    def a_veces(f, ctx):
        if estado["roto"]:
            raise ConnectionError("servicio caído")
        return []

    c = nueva_cerebro(tmp_path, agentes=(*AGENTES, ("externo", a_veces)))
    pendiente = c.decidir(factura("12"))
    estado["roto"] = True
    with pytest.raises(ReevaluacionNecesaria):
        c.reanudar(pendiente.factura_id, True, "jurado-1")
    assert pagos_simulados(c) == 0
    estado["roto"] = False
    assert c.reanudar(pendiente.factura_id, True, "jurado-1").decision == "PAGAR"


def test_aprobar_no_silencia_una_inyeccion_detectada_al_revalidar(tmp_path):
    capa = CapaFija(error=ConnectionError("sin red"))
    c = nueva_cerebro(tmp_path, capa=capa)
    pendiente = c.decidir(factura("03"))
    assert pendiente.decision == "ESCALAR"
    with pytest.raises(ReevaluacionNecesaria):                       # la capa sigue caída
        c.reanudar(pendiente.factura_id, True, "jurado-1")
    capa.error, capa.probabilidades = None, {INSTRUCCIONES: 0.9}
    d = c.reanudar(pendiente.factura_id, True, "jurado-1")
    assert d.decision == "FRENAR" and "No se puede aprobar" in d.explicacion
    assert pagos_simulados(c) == 0


def test_rechazo_queda_registrado_sin_borrar_la_evidencia(tmp_path):
    c = nueva_cerebro(tmp_path)
    pendiente = c.decidir(factura("11"))          # v2: la 10 ya es FRENAR no aprobable
    rechazo = c.reanudar(pendiente.factura_id, False, "jurado-2")
    p = c.paquete_evidencia(pendiente.factura_id)
    assert [x["decision"]["hash"] for x in p["decisiones"]] == [pendiente.hash, rechazo.hash]
    assert p["responsable"] == {"tipo": "humano", "nombre": "jurado-2", "severidad": 2,
                                "motivo": rechazo.explicacion, "evidencia": "rechazo humano", "campo": None}


def test_aprobar_exige_lista_cuando_se_pide(tmp_path):
    c = nueva_cerebro(tmp_path, exigir_aprobadores=True)
    pendiente = c.decidir(factura("12"))
    with pytest.raises(PermissionError):
        c.reanudar(pendiente.factura_id, True, "jurado-1")
    assert c.reanudar(pendiente.factura_id, False, "jurado-1").decision == "FRENAR"


def test_modulo_respeta_cerebro_aprobadores(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "m.db"))
    monkeypatch.setenv("CEREBRO_APROBADORES", "tg:111, tg:222")
    monkeypatch.delenv("REF_DATE", raising=False)
    monkeypatch.delenv("SIGNING_KEY_PATH", raising=False)
    monkeypatch.delenv("CEREBRO_SEMANTICA", raising=False)
    monkeypatch.setattr(cerebro, "_por_defecto", None)
    pendiente = cerebro.decidir(factura("12"))
    with pytest.raises(PermissionError):
        cerebro.reanudar(pendiente.factura_id, True, "tg:999")
    assert cerebro.reanudar(pendiente.factura_id, True, "tg:222").decision == "PAGAR"


def test_modulo_firma_con_signing_key_path(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "f.db"))
    monkeypatch.setenv("SIGNING_KEY_PATH", str(tmp_path / "firma.pem"))
    monkeypatch.delenv("CEREBRO_SEMANTICA", raising=False)
    monkeypatch.setattr(cerebro, "_por_defecto", None)
    cerebro.decidir(factura("01"))
    assert (tmp_path / "firma.pem").exists() and cerebro.verificar_cadena() == (True, None)
    assert cerebro.paquete_evidencia(factura("01").id_documento)["cadena"]["firmada"] is True
