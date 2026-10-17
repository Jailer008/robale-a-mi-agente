from __future__ import annotations

import pytest

from extraccion.comparador import comparar, normalizar_monto, normalizar_texto
from extraccion.modelo import CamposExtraidos


@pytest.mark.parametrize(
    "entrada, esperado",
    [
        (4800, 4800.0), (4800.5, 4800.5), ("4.800,00", 4800.0), ("4,800.00", 4800.0),
        ("48.000", 48000.0), ("4,8", 4.8), (" USD 1,850.00 ", 1850.0), ("$ 952.000", 952000.0),
        ("1.234.567,89", 1234567.89), ("1,234,567", 1234567.0), ("-20", -20.0),
        (None, None), ("", None), ("abc", None),
    ],
)
def test_normalizar_monto(entrada, esperado):
    assert normalizar_monto(entrada) == esperado


@pytest.mark.parametrize(
    "a, b",
    [("Nubia Studio S.A.S.", "NUBIA STUDIO SAS"), ("CO-BANCO-0423", "co banco 0423"),
     ("Cóndor Cloud SAS", "Condor  Cloud SAS"), ("FV-0192", "fv 0192")],
)
def test_normalizar_texto_equivalentes(a, b):
    assert normalizar_texto(a) == normalizar_texto(b)


def test_normalizar_texto_distintos():
    assert normalizar_texto("CO-BANCO-0423") != normalizar_texto("CO-BANCO-7781")
    assert normalizar_texto(None) is None


def campos(**cambios) -> CamposExtraidos:
    base = dict(proveedor="Nubia Studio SAS", cuenta_bancaria="CO-BANCO-0423",
                numero_factura="NS-1", moneda="USD", total=4800.0)
    return CamposExtraidos(**(base | cambios))


def test_iguales_tras_normalizar_no_generan_diferencias():
    a = campos()
    b = campos(proveedor="NUBIA STUDIO S.A.S.", moneda="usd", cuenta_bancaria="co banco 0423")
    assert comparar(a, b) == []


def test_total_distinto_mensaje_legible():
    assert comparar(campos(), campos(total=48000.0)) == [
        "Extractor A leyó 4.800 y B leyó 48.000 en el total"
    ]


def test_cuenta_distinta():
    assert comparar(campos(), campos(cuenta_bancaria="CO-BANCO-7781")) == [
        "Extractor A leyó 'CO-BANCO-0423' y B leyó 'CO-BANCO-7781' en la cuenta bancaria"
    ]


def test_un_lado_vacio_cuenta_como_diferencia():
    assert comparar(campos(), campos(numero_factura=None)) == [
        "Extractor A leyó 'NS-1' y B leyó (vacío) en el número de factura"
    ]


def test_varias_diferencias_en_orden_fijo():
    b = campos(total=1.0, moneda="MXN", proveedor="Otro")
    mensajes = comparar(campos(), b)
    assert [m.rsplit(" en ", 1)[1] for m in mensajes] == ["el total", "la moneda", "el proveedor"]
