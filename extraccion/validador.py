"""Validador aritmético 100 % código: nunca le pide cuentas a un modelo.

Devuelve mensajes legibles; lista vacía significa que la factura cuadra.
"""

from __future__ import annotations

from extraccion.formato import monto_es
from schemas import FacturaCanonica

TOLERANCIA = 0.01
MONEDAS_VALIDAS = frozenset({"USD", "COP", "MXN", "ARS", "PEN", "EUR"})


def _distinto(a: float, b: float) -> bool:
    return abs(a - b) > TOLERANCIA + 1e-9


def validar(f: FacturaCanonica) -> list[str]:
    mensajes: list[str] = []

    if not f.lineas:
        mensajes.append("La factura no tiene líneas")
    for i, linea in enumerate(f.lineas, start=1):
        esperado = linea.cantidad * linea.precio_unitario
        if _distinto(esperado, linea.total):
            mensajes.append(
                f"Línea {i}: {monto_es(linea.cantidad)} × {monto_es(linea.precio_unitario)} = "
                f"{monto_es(esperado)}, pero dice {monto_es(linea.total)}"
            )

    suma = sum(linea.total for linea in f.lineas)
    if f.lineas and _distinto(suma, f.subtotal):
        mensajes.append(
            f"Las líneas suman {monto_es(suma)} pero el subtotal dice {monto_es(f.subtotal)}"
        )

    if _distinto(f.subtotal + f.impuestos, f.total):
        mensajes.append(
            f"Subtotal {monto_es(f.subtotal)} + impuestos {monto_es(f.impuestos)} = "
            f"{monto_es(f.subtotal + f.impuestos)}, pero el total dice {monto_es(f.total)}"
        )

    if f.total <= 0:
        mensajes.append("El total debe ser mayor que cero")

    if f.moneda not in MONEDAS_VALIDAS:
        mensajes.append(
            f"Moneda '{f.moneda}' no válida; se aceptan {', '.join(sorted(MONEDAS_VALIDAS))}"
        )

    if f.fecha_vencimiento is not None and f.fecha_vencimiento < f.fecha_emision:
        mensajes.append(
            f"El vencimiento ({f.fecha_vencimiento}) es anterior a la emisión ({f.fecha_emision})"
        )

    return mensajes
