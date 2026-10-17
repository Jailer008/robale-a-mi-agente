"""Pool de facturas base del modo en vivo (datos/base/): lo que el servidor reparte al jurado.

Todas son de proveedores permitidos. Enviadas "tal cual" sobre el estado inicial de la demo
(solo el histórico) deben dar exactamente su `esperado_tal_cual`.
"""

from __future__ import annotations

import pytest
from conftest import DATOS
from extraccion.render import FacturaBase, cargar_base, listar_bases
from oraculo import (
    FRENAN,
    a_usd,
    candidatos_duplicado,
    contrato_de,
    estado_inicial,
    proveedor_por_nombre,
    reglas_de_dinero,
)

IDS = [f"base_{n:02d}" for n in range(1, 9)]


@pytest.fixture(scope="module")
def bases() -> dict[str, FacturaBase]:
    return {base_id: cargar_base(base_id) for base_id in IDS}


def test_ocho_bases_listadas():
    assert listar_bases() == IDS
    assert sorted(p.stem for p in (DATOS / "base").glob("*.json")) == IDS


def test_cada_base_valida_y_con_su_id(bases):
    for base_id, b in bases.items():
        assert b.base_id == base_id
        assert b.esperado_tal_cual in {"PAGAR", "ESCALAR", "FRENAR"}
        assert b.pista


def test_proveedores_permitidos_con_sus_datos_registrados(bases, proveedores, contratos):
    for base_id, b in bases.items():
        p = proveedor_por_nombre(proveedores, b.proveedor)
        assert p and p["permitido"] and not p["bloqueado"], base_id
        assert (b.cuenta, b.id_fiscal, b.pais) == (p["cuenta_registrada"], p["id_fiscal"], p["pais"]), base_id
        c = contrato_de(contratos, b.proveedor)
        assert (b.referencia_contrato, b.moneda) == (c["id"], c["moneda"]), base_id


def test_aritmetica_cuadra(bases):
    for base_id, b in bases.items():
        for linea in b.lineas:
            assert abs(linea.cantidad * linea.precio_unitario - linea.total) <= 0.01, base_id
        assert abs(sum(linea.total for linea in b.lineas) - b.subtotal) <= 0.01, base_id
        assert abs(b.subtotal + b.impuestos - b.total) <= 0.01, base_id
        assert b.fecha_vencimiento >= b.fecha_emision


def test_cinco_limpias_entre_800_y_4000_usd_que_cuadran_con_su_contrato(bases, contratos, tasas):
    limpias = [b for b in bases.values() if b.esperado_tal_cual == "PAGAR"]
    assert len(limpias) == 5
    assert len({b.moneda for b in limpias}) >= 3
    for b in limpias:
        assert 800 <= a_usd(b.total, b.moneda, tasas) <= 4000, b.base_id
        precios = {i["descripcion"]: i["precio_unitario"] for i in contrato_de(contratos, b.proveedor)["items"]}
        for linea in b.lineas:
            assert precios.get(linea.descripcion) == linea.precio_unitario, (b.base_id, linea)
        assert not b.nota_oculta and not b.nota_visible


def test_tres_trampas(bases, contratos, tasas):
    trampas = {b.base_id: b for b in bases.values() if b.esperado_tal_cual != "PAGAR"}
    assert len(trampas) == 3

    infladas = [
        b for b in trampas.values()
        if any(
            linea.precio_unitario > {i["descripcion"]: i["precio_unitario"]
                                     for i in contrato_de(contratos, b.proveedor)["items"]}[linea.descripcion] * 1.05
            for linea in b.lineas
        )
    ]
    assert len(infladas) == 1 and infladas[0].esperado_tal_cual == "ESCALAR"

    altas = [b for b in trampas.values() if a_usd(b.total, b.moneda, tasas) == 7400]
    assert len(altas) == 1 and altas[0].esperado_tal_cual == "ESCALAR"

    ocultas = [b for b in trampas.values() if b.nota_oculta]
    assert len(ocultas) == 1 and ocultas[0].esperado_tal_cual == "FRENAR"


def test_tal_cual_sobre_el_estado_inicial_solo_dispara_su_regla(bases, historico, reglas, tasas):
    """Cada base por separado, como queda la demo tras reiniciar_demo() (solo el histórico)."""
    for base_id, b in bases.items():
        gastado_prov, gastado_global, saldo = estado_inicial(historico, reglas)
        disparadas = reglas_de_dinero(b, gastado_prov, gastado_global, saldo, reglas, tasas)
        assert not disparadas & FRENAN, (base_id, disparadas)
        if a_usd(b.total, b.moneda, tasas) == 7400:
            assert disparadas == {"limite_pago"}
        else:
            assert disparadas == set(), (base_id, disparadas)
        assert candidatos_duplicado(b, historico, reglas) == [], base_id
        assert not any(p["numero_factura"] == b.numero for p in historico), base_id


def test_las_cinco_limpias_juntas_caben_en_el_saldo_inicial(bases, historico, reglas, tasas):
    _, _, saldo = estado_inicial(historico, reglas)
    total = sum(a_usd(b.total, b.moneda, tasas) for b in bases.values() if b.esperado_tal_cual == "PAGAR")
    assert total <= saldo
