"""Dinero exacto: Decimal y centavos enteros. Nunca float para operar."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

_CENTAVO = Decimal("0.01")


def a_decimal(valor: object) -> Decimal:
    """float/int/str del esquema → Decimal vía str() para no heredar errores binarios."""
    if valor is None or isinstance(valor, bool):
        raise ValueError(f"monto inválido: {valor!r}")
    try:
        numero = Decimal(str(valor).strip())
    except InvalidOperation as error:
        raise ValueError(f"monto inválido: {valor!r}") from error
    if not numero.is_finite():
        raise ValueError(f"monto no finito: {valor!r}")
    return numero


def a_centavos(valor: Decimal) -> int:
    return int((valor / _CENTAVO).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def cents_a_decimal(cents: int) -> Decimal:
    return Decimal(cents) * _CENTAVO


def numero_es(valor: Decimal) -> str:
    """7400 -> '7.400,00'."""
    texto = f"{valor.quantize(_CENTAVO, rounding=ROUND_HALF_UP):,.2f}"
    return texto.replace(",", "_").replace(".", ",").replace("_", ".")


def usd_es(cents: int) -> str:
    return f"USD {numero_es(cents_a_decimal(cents))}"


def monto_es(valor: Decimal, moneda: str) -> str:
    return f"{moneda} {numero_es(valor)}"
