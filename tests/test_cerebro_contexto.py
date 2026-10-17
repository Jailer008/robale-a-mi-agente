"""Dev 2 · dinero, configuración, base de datos y contexto (100 % código, Decimal y centavos)."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import date
from decimal import Decimal

import pytest
from cerebro_util import REF, factura, nueva_cerebro, variante
from conftest import RAIZ

from cerebro.config import cargar_reglas, ref_date_configurada
from cerebro.dinero import a_centavos, a_decimal, usd_es

# ---------- dinero ----------


def test_a_decimal_usa_la_representacion_decimal_del_float():
    assert a_decimal(0.1) + a_decimal(0.2) == Decimal("0.3")
    assert a_decimal(1850) == Decimal("1850")


@pytest.mark.parametrize("malo", [float("nan"), float("inf"), float("-inf"), "abc", None])
def test_a_decimal_rechaza_valores_no_finitos(malo):
    with pytest.raises(ValueError):
        a_decimal(malo)


def test_a_centavos_redondea_half_up():
    assert a_centavos(Decimal("34000") / Decimal("3.75")) == 906667
    assert a_centavos(Decimal("0.005")) == 1
    assert isinstance(a_centavos(Decimal("1")), int)


def test_usd_es_formato_espanol():
    assert usd_es(740000) == "USD 7.400,00"
    assert usd_es(747734) == "USD 7.477,34"
    assert usd_es(-5) == "USD -0,05"


# ---------- configuración ----------


def test_reglas_en_centavos_y_version_sha256():
    reglas = cargar_reglas(RAIZ / "reglas.yaml")
    assert reglas.limite_pago_cents == 500000
    assert reglas.tope_duro_cents == 1500000
    assert reglas.limite_mes_proveedor_cents == 1000000
    assert reglas.limite_mes_global_cents == 4000000
    assert reglas.saldo_inicial_mes_cents == 2500000
    assert reglas.tolerancia_contrato == Decimal("0.05")
    assert reglas.tolerancia_fx == Decimal("0.03")
    assert reglas.tolerancia_monto_duplicado == Decimal("0.02")
    assert reglas.ventana_duplicados_dias == 15
    assert reglas.version == hashlib.sha256((RAIZ / "reglas.yaml").read_bytes()).hexdigest()


def test_ref_date_por_defecto_y_configurable(monkeypatch):
    monkeypatch.delenv("REF_DATE", raising=False)
    assert ref_date_configurada() == date(2026, 10, 17)
    monkeypatch.setenv("REF_DATE", "2026-11-05")
    assert ref_date_configurada() == date(2026, 11, 5)
    monkeypatch.setenv("REF_DATE", "no-es-fecha")
    with pytest.raises(ValueError):
        ref_date_configurada()


# ---------- base de datos ----------


def test_tablas_creadas(tmp_path):
    c = nueva_cerebro(tmp_path)
    with sqlite3.connect(c.db.ruta) as con:
        tablas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"pagos", "decision_log", "reglas_versiones", "eventos"} <= tablas


def test_carga_del_historico_idempotente(tmp_path):
    nueva_cerebro(tmp_path)
    c = nueva_cerebro(tmp_path)          # segunda vez sobre la misma base
    with c.db.transaccion() as con:
        assert con.execute("SELECT COUNT(*) FROM pagos").fetchone()[0] == 20
        assert con.execute("SELECT COUNT(*) FROM pagos WHERE origen='historico'").fetchone()[0] == 20
        versiones = con.execute("SELECT version FROM reglas_versiones").fetchall()
    assert [v[0] for v in versiones] == [c.reglas.version]


def test_pagos_guardan_centavos_enteros(tmp_path):
    c = nueva_cerebro(tmp_path)
    with c.db.transaccion() as con:
        fila = con.execute("SELECT monto_usd_cents FROM pagos WHERE factura_id='P-013'").fetchone()
    assert fila[0] == 113333 and isinstance(fila[0], int)


# ---------- contexto ----------


def test_saldo_inicial_efectivo_de_octubre_es_8600(tmp_path):
    c = nueva_cerebro(tmp_path)
    ctx = c.contexto(factura("01"))
    assert ctx.saldo_cents == 860000
    assert ctx.gastado_mes_global_cents == 1640000
    assert ctx.gastado_mes_proveedor_cents == 200000      # Nubia: 1.250 + 750 en octubre


def test_conversion_fx_de_la_13(tmp_path):
    ctx = nueva_cerebro(tmp_path).contexto(factura("13"))
    assert ctx.monto_original == Decimal("34000")
    assert ctx.fx is not None
    assert ctx.fx.unidades_por_usd == Decimal("3.75")
    assert ctx.fx.fecha == "2026-10-16" and "Ficticia" in ctx.fx.fuente.title()
    assert ctx.monto_usd_cents == 906667


def test_usd_es_tasa_1(tmp_path):
    ctx = nueva_cerebro(tmp_path).contexto(factura("12"))
    assert ctx.fx.unidades_por_usd == Decimal("1")
    assert ctx.monto_usd_cents == 740000


def test_cop_sin_error_de_coma_flotante(tmp_path):
    ctx = nueva_cerebro(tmp_path).contexto(factura("03"))
    assert ctx.monto_usd_cents == 17850                  # 714.000 / 4.000


def test_estado_proveedor_cuenta_y_contrato(tmp_path):
    c = nueva_cerebro(tmp_path)
    limpio = c.contexto(factura("01"))
    assert limpio.beneficiario_permitido and not limpio.beneficiario_bloqueado
    assert limpio.cuenta_coincide and limpio.contrato["id"] == "CT-001"
    assert limpio.extraccion_ok and limpio.problemas == []

    nuevo = c.contexto(factura("09"))
    assert not nuevo.beneficiario_permitido and nuevo.proveedor is None and nuevo.contrato is None

    cambio = c.contexto(factura("10"))
    assert cambio.beneficiario_permitido and not cambio.cuenta_coincide

    bloqueado = c.contexto(variante("01", proveedor="Vicuña Consulting SAC"))
    assert bloqueado.beneficiario_bloqueado and not bloqueado.beneficiario_permitido


def test_proveedor_se_reconoce_sin_tildes_ni_puntuacion(tmp_path):
    ctx = nueva_cerebro(tmp_path).contexto(variante("03", proveedor="CONDOR CLOUD S.A.S."))
    assert ctx.proveedor is not None and ctx.proveedor["nombre"] == "Cóndor Cloud SAS"


def test_moneda_sin_tasa_fx(tmp_path):
    ctx = nueva_cerebro(tmp_path).contexto(variante("01", moneda="EUR"))
    assert ctx.fx is None and ctx.monto_usd_cents is None
    assert any("EUR" in p for p in ctx.problemas)


def test_extraccion_no_validada_se_refleja(tmp_path):
    ctx = nueva_cerebro(tmp_path).contexto(factura("15"))
    assert ctx.extraccion_ok is False


@pytest.mark.parametrize("cambios, texto", [
    ({"total": 0.0, "subtotal": 0.0}, "mayor que cero"),
    ({"total": float("nan")}, "total"),
    ({"total": 999.0}, "total"),                         # subtotal + impuestos != total
    ({"subtotal": 150.0, "total": 150.0}, "líneas"),     # líneas no suman el subtotal
    ({"lineas": []}, "líneas"),
    ({"proveedor": "  "}, "proveedor"),
    ({"numero_factura": ""}, "número"),
])
def test_datos_criticos_inconsistentes_son_problemas(tmp_path, cambios, texto):
    ctx = nueva_cerebro(tmp_path).contexto(variante("01", **cambios))
    assert any(texto in p for p in ctx.problemas), ctx.problemas


def test_ref_date_independiente_del_reloj(tmp_path):
    c = nueva_cerebro(tmp_path, ref_date=date(2026, 11, 5))
    ctx = c.contexto(factura("01"))
    assert ctx.gastado_mes_global_cents == 0             # los pagos de octubre no cuentan en noviembre
    assert ctx.saldo_cents == 2500000
    assert REF == date(2026, 10, 17)
