"""Formato de cifras para los mensajes en español que lee el jurado."""

from __future__ import annotations


def monto_es(valor: float) -> str:
    """4300 -> '4.300'; 1850.5 -> '1.850,50'. Sin decimales si el valor es entero."""
    redondeado = round(valor, 2)
    if redondeado == int(redondeado):
        return f"{int(redondeado):,}".replace(",", ".")
    entero, decimales = f"{redondeado:,.2f}".split(".")
    return f"{entero.replace(',', '.')},{decimales}"
