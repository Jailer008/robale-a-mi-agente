from __future__ import annotations

from datetime import date

import pytest
from conftest import cargar_factura_json

from extraccion.formato import monto_es
from extraccion.validador import validar
from schemas import FacturaCanonica, Linea


def factura(**cambios) -> FacturaCanonica:
    base = dict(
        id_documento="x", archivo="x.pdf", canal="web", proveedor="P", numero_factura="F-1",
        fecha_emision=date(2026, 10, 1), fecha_vencimiento=date(2026, 10, 31), moneda="USD",
        lineas=[Linea(descripcion="a", cantidad=2, precio_unitario=100, total=200),
                Linea(descripcion="b", cantidad=1, precio_unitario=50, total=50)],
        subtotal=250, impuestos=0, total=250,
    )
    return FacturaCanonica(**(base | cambios))


@pytest.mark.parametrize(
    "valor, texto",
    [(4300, "4.300"), (4800.0, "4.800"), (1850.5, "1.850,50"), (0.1, "0,10"),
     (1234567.891, "1.234.567,89"), (-20, "-20")],
)
def test_monto_es(valor, texto):
    assert monto_es(valor) == texto


@pytest.mark.parametrize("n", [f"{i:02d}" for i in range(1, 16)])
def test_las_15_facturas_del_set_son_validas(n):
    assert validar(cargar_factura_json(n)) == []


def test_factura_correcta_sin_mensajes():
    assert validar(factura()) == []


def test_lineas_no_suman_el_subtotal():
    mensajes = validar(factura(subtotal=300, total=300))
    assert "Las líneas suman 250 pero el subtotal dice 300" in mensajes


def test_subtotal_mas_impuestos_distinto_del_total():
    mensajes = validar(factura(impuestos=10, total=250))
    assert "Subtotal 250 + impuestos 10 = 260, pero el total dice 250" in mensajes


def test_linea_mal_multiplicada():
    lineas = [Linea(descripcion="a", cantidad=3, precio_unitario=600, total=1900)]
    mensajes = validar(factura(lineas=lineas, subtotal=1900, total=1900))
    assert mensajes == ["Línea 1: 3 × 600 = 1.800, pero dice 1.900"]


def test_tolerancia_de_un_centavo():
    lineas = [Linea(descripcion="a", cantidad=3, precio_unitario=33.33, total=99.99)]
    assert validar(factura(lineas=lineas, subtotal=100.0, total=100.0)) == []


@pytest.mark.parametrize("moneda", ["BTC", "usd", "", "DOLARES"])
def test_moneda_fuera_de_la_lista_cerrada(moneda):
    mensajes = validar(factura(moneda=moneda))
    assert any("Moneda" in m for m in mensajes)


def test_vencimiento_anterior_a_emision():
    mensajes = validar(factura(fecha_vencimiento=date(2026, 9, 1)))
    assert "El vencimiento (2026-09-01) es anterior a la emisión (2026-10-01)" in mensajes


def test_sin_vencimiento_es_valido():
    assert validar(factura(fecha_vencimiento=None)) == []


def test_sin_lineas_y_total_no_positivo():
    mensajes = validar(factura(lineas=[], subtotal=0, total=0))
    assert "La factura no tiene líneas" in mensajes
    assert "El total debe ser mayor que cero" in mensajes


def test_acumula_todos_los_problemas():
    lineas = [Linea(descripcion="a", cantidad=1, precio_unitario=10, total=11)]
    mensajes = validar(factura(lineas=lineas, subtotal=20, total=30, moneda="XXX"))
    assert len(mensajes) == 4
