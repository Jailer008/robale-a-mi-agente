"""Dev 2 · G4: reiniciar_demo() — base sintética controlada, sin carreras y solo para administradores."""

from __future__ import annotations

import sqlite3
import threading
import time

import pytest
from cerebro_util import AGENTES_LENTOS, factura, nueva_cerebro

import cerebro
from cerebro import ReinicioOcupado
from cerebro.firma import Firmante

ADMIN = "admin:ops"


def contar(c, tabla: str, donde: str = "1=1") -> int:
    with c.db.transaccion() as con:
        return con.execute(f"SELECT COUNT(*) FROM {tabla} WHERE {donde}").fetchone()[0]  # noqa: S608 - tests


def test_reinicio_restaura_el_estado_inicial(tmp_path):
    firmante = Firmante.generar()
    c = nueva_cerebro(tmp_path, administradores=frozenset({ADMIN}), firmante=firmante)
    for n in ["01", "02", "12", "14"]:
        c.decidir(factura(n))
    assert contar(c, "pagos", "origen='simulado'") == 2 and contar(c, "decision_log") == 4
    resumen = c.reiniciar_demo(ADMIN)
    assert contar(c, "decision_log") == 0 and contar(c, "eventos") == 0
    assert contar(c, "pagos", "origen='historico'") == 20 and contar(c, "pagos", "origen='simulado'") == 0
    assert c.contexto(factura("01")).saldo_cents == 860000                      # USD 8.600 otra vez
    assert c.verificar_cadena() == (True, None) and c.verificar_pagos() == []
    assert resumen["reiniciado_por"] == ADMIN and resumen["decisiones"] == 0 and resumen["pagos_historicos"] == 20
    assert resumen["firma"] == firmante.huella and resumen["saldo_inicial_usd"] == "8600.00"
    d = c.decidir(factura("01"))                                                 # no es duplicado: ensayo borrado
    assert d.decision == "PAGAR" and d.hash_prev == "0" * 64
    assert c.verificar_cadena() == (True, None)


def test_respaldo_de_los_ensayos(tmp_path):
    c = nueva_cerebro(tmp_path, administradores=frozenset({ADMIN}))
    c.decidir(factura("01"))
    resumen = c.reiniciar_demo(ADMIN)
    with sqlite3.connect(resumen["respaldo"]) as respaldo:
        assert respaldo.execute("SELECT COUNT(*) FROM decision_log").fetchone()[0] == 1


def test_base_sintetica_se_reconstruye_si_la_alteran(tmp_path):
    c = nueva_cerebro(tmp_path, administradores=frozenset({ADMIN}))
    c.reiniciar_demo(ADMIN)
    with sqlite3.connect(c.ruta_base) as base:                                  # alguien ensucia la base
        base.execute("DELETE FROM pagos WHERE factura_id = 'P-019'")
    c.reiniciar_demo(ADMIN)
    assert contar(c, "pagos", "origen='historico'") == 20 and c.verificar_pagos() == []


@pytest.mark.parametrize("admins, quien", [(None, ADMIN), (frozenset({ADMIN}), "jurado-1"), (frozenset({ADMIN}), "")])
def test_solo_administradores_autorizados(tmp_path, admins, quien):
    c = nueva_cerebro(tmp_path, administradores=admins)
    c.decidir(factura("01"))
    with pytest.raises((PermissionError, ValueError)):
        c.reiniciar_demo(quien)
    assert contar(c, "decision_log") == 1


def test_espera_a_las_solicitudes_en_curso_y_retiene_las_nuevas(tmp_path):
    c = nueva_cerebro(tmp_path, administradores=frozenset({ADMIN}), agentes=AGENTES_LENTOS(0.4))
    hilo = threading.Thread(target=lambda: c.decidir(factura("01")))
    hilo.start()
    time.sleep(0.1)                                                              # la decisión está en curso
    inicio = time.perf_counter()
    c.reiniciar_demo(ADMIN)
    hilo.join()
    assert time.perf_counter() - inicio >= 0.2                                  # esperó a que terminara
    assert contar(c, "decision_log") == 0                                       # y la borró al reiniciar


def test_reinicio_ocupado_si_no_terminan_a_tiempo(tmp_path):
    c = nueva_cerebro(tmp_path, administradores=frozenset({ADMIN}), agentes=AGENTES_LENTOS(1.0),
                      timeout_agente_s=5)
    hilo = threading.Thread(target=lambda: c.decidir(factura("01")))
    hilo.start()
    time.sleep(0.1)
    with pytest.raises(ReinicioOcupado):
        c.reiniciar_demo(ADMIN, timeout_s=0.2)
    hilo.join()
    assert contar(c, "decision_log") == 1                                       # no se tocó nada


def test_modulo_exige_cerebro_admins(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "demo.db"))
    monkeypatch.delenv("CEREBRO_ADMINS", raising=False)
    monkeypatch.delenv("SIGNING_KEY_PATH", raising=False)
    monkeypatch.delenv("CEREBRO_SEMANTICA", raising=False)
    monkeypatch.setattr(cerebro, "_por_defecto", None)
    cerebro.decidir(factura("01"))
    with pytest.raises(PermissionError):
        cerebro.reiniciar_demo(ADMIN)
    monkeypatch.setenv("CEREBRO_ADMINS", ADMIN)
    monkeypatch.setattr(cerebro, "_por_defecto", None)
    assert cerebro.reiniciar_demo(ADMIN)["decisiones"] == 0
    assert (tmp_path / "demo_base.db").exists()
