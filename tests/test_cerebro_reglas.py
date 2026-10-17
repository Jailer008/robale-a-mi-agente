"""Dev 2 · reglas deterministas (alternativa Python a Cedar, misma tabla de DEV2 §1.3)."""

from __future__ import annotations

import dataclasses

import pytest
from cerebro_util import factura, nueva_cerebro, variante

from cerebro.reglas import evaluar


@pytest.fixture
def cerebro(tmp_path):
    return nueva_cerebro(tmp_path)


def ids(evaluacion):
    return {f.regla for f in evaluacion.fallas}


@pytest.mark.parametrize("n", ["01", "02", "03", "04", "05", "06"])
def test_limpias_allow_sin_fallas(cerebro, n):
    ev = evaluar(cerebro.contexto(factura(n)))
    assert ev.cedar == "ALLOW" and ev.fallas == []


def test_12_solo_supera_el_limite_por_pago(cerebro):
    ev = evaluar(cerebro.contexto(factura("12")))
    assert ev.cedar == "DENY"
    assert ids(ev) == {"limite_pago"}
    falla = ev.fallas[0]
    assert falla.severidad == 1
    assert falla.motivo == "USD 7.400,00 supera el límite de USD 5.000,00 sin aprobación humana."


def test_13_frena_por_saldo_sin_tope_duro(cerebro):
    ev = evaluar(cerebro.contexto(factura("13")))
    assert "saldo" in ids(ev) and "tope_duro" not in ids(ev)
    assert not ids(ev) & {"mensual_proveedor", "mensual_global"}
    saldo = next(f for f in ev.fallas if f.regla == "saldo")
    assert saldo.severidad == 2
    assert saldo.motivo == "Saldo de USD 8.600,00 menor a los USD 9.066,67 requeridos."


def test_limite_exacto_de_5000_se_permite(cerebro):
    ctx = dataclasses.replace(cerebro.contexto(factura("01")), monto_usd_cents=500000)
    assert evaluar(ctx).cedar == "ALLOW"
    ctx = dataclasses.replace(ctx, monto_usd_cents=500001)
    assert ids(evaluar(ctx)) == {"limite_pago"}


def test_tope_duro_frena(cerebro):
    ctx = dataclasses.replace(cerebro.contexto(factura("01")), monto_usd_cents=1500001, saldo_cents=10**9)
    ev = evaluar(ctx)
    assert "tope_duro" in ids(ev) and "limite_pago" not in ids(ev)
    assert max(f.severidad for f in ev.fallas) == 2


def test_limite_mensual_del_proveedor_frena(cerebro):
    ctx = dataclasses.replace(cerebro.contexto(factura("01")), gastado_mes_proveedor_cents=990000)
    ev = evaluar(ctx)
    assert ids(ev) == {"mensual_proveedor"}
    assert ev.fallas[0].severidad == 2
    assert "USD 10.000,00" in ev.fallas[0].motivo


def test_limite_mensual_global_frena(cerebro):
    ctx = dataclasses.replace(cerebro.contexto(factura("01")), gastado_mes_global_cents=3990000)
    ev = evaluar(ctx)
    assert ids(ev) == {"mensual_global"} and ev.fallas[0].severidad == 2


def test_saldo_insuficiente_frena(cerebro):
    ctx = dataclasses.replace(cerebro.contexto(factura("01")), saldo_cents=19999)
    ev = evaluar(ctx)
    assert ids(ev) == {"saldo"} and ev.fallas[0].severidad == 2


def test_proveedor_nuevo_frena_v2(cerebro):
    ev = evaluar(cerebro.contexto(factura("09")))
    assert ids(ev) == {"beneficiario_no_permitido"}
    assert ev.fallas[0].severidad == 2 and ev.fallas[0].codigo == "PROVEEDOR_NO_PERMITIDO"
    assert ev.fallas[0].motivo == "'Delta Devs' no está en la lista aprobada."


def test_proveedor_bloqueado_frena(cerebro):
    ev = evaluar(cerebro.contexto(variante("01", proveedor="Vicuña Consulting SAC", cuenta_bancaria="PE-BANCO-7310")))
    assert "beneficiario_bloqueado" in ids(ev)
    assert max(f.severidad for f in ev.fallas) == 2


def test_cuenta_alterada_frena_v2(cerebro):
    ev = evaluar(cerebro.contexto(factura("10")))
    assert ids(ev) == {"cuenta"}
    assert ev.fallas[0].severidad == 2 and ev.fallas[0].codigo == "CUENTA_NO_REGISTRADA"
    assert ev.fallas[0].motivo == "Cuenta termina en 7781; la registrada termina en 0423."


def test_cuenta_ausente_frena_v2(cerebro):
    ev = evaluar(cerebro.contexto(variante("01", cuenta_bancaria=None)))
    assert ids(ev) == {"cuenta"} and ev.fallas[0].severidad == 2


def test_extraccion_no_validada_escala_con_sus_diferencias(cerebro):
    ev = evaluar(cerebro.contexto(factura("15")))
    assert "extraccion" in ids(ev)
    falla = next(f for f in ev.fallas if f.regla == "extraccion")
    assert falla.severidad == 1 and "borrosa" in falla.motivo


def test_sin_tasa_fx_nunca_allow(cerebro):
    ev = evaluar(cerebro.contexto(variante("01", moneda="EUR")))
    assert ev.cedar == "DENY"
    assert "fx" in ids(ev)
    assert max(f.severidad for f in ev.fallas) >= 1


def test_datos_incoherentes_nunca_allow(cerebro):
    ev = evaluar(cerebro.contexto(variante("01", total=999.0)))
    assert ev.cedar == "DENY" and "datos" in ids(ev)
