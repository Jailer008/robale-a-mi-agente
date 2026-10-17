"""Compara campo a campo lo que leyeron A y B. Nunca promedia: si difieren, se escala."""

from __future__ import annotations

import re
import unicodedata

from extraccion.formato import monto_es
from extraccion.modelo import CamposExtraidos

TOLERANCIA = 0.01
CAMPOS_TEXTO = {
    "moneda": "la moneda",
    "proveedor": "el proveedor",
    "cuenta_bancaria": "la cuenta bancaria",
    "numero_factura": "el número de factura",
}


def normalizar_texto(valor: str | None) -> str | None:
    """Sin tildes, en mayúsculas y solo letras y dígitos: 'S.A.S.' == 'SAS'."""
    if valor is None:
        return None
    sin_tildes = unicodedata.normalize("NFKD", valor).encode("ascii", "ignore").decode()
    limpio = re.sub(r"[^A-Z0-9]", "", sin_tildes.upper())
    return limpio or None


def normalizar_monto(valor: float | int | str | None) -> float | None:
    """Acepta '4.800,00', '4,800.00', '48.000', 'USD 1,850.00'. Devuelve None si no es un número."""
    if valor is None:
        return None
    if isinstance(valor, int | float):
        return float(valor)
    texto = re.sub(r"[^\d.,-]", "", valor)
    if not re.search(r"\d", texto):
        return None
    if "." in texto and "," in texto:
        decimal = "." if texto.rfind(".") > texto.rfind(",") else ","
        texto = texto.replace("," if decimal == "." else ".", "").replace(decimal, ".")
    else:
        separador = "." if "." in texto else "," if "," in texto else None
        if separador:
            partes = texto.split(separador)
            es_miles = len(partes) > 2 or len(partes[-1]) == 3
            texto = texto.replace(separador, "") if es_miles else texto.replace(separador, ".")
    try:
        return float(texto)
    except ValueError:
        return None


def _texto_mostrado(valor: str | None) -> str:
    return f"'{valor}'" if valor else "(vacío)"


def comparar(a: CamposExtraidos, b: CamposExtraidos) -> list[str]:
    diferencias: list[str] = []

    total_a, total_b = normalizar_monto(a.total), normalizar_monto(b.total)
    if (total_a is None) != (total_b is None) or (
        total_a is not None and total_b is not None and abs(total_a - total_b) > TOLERANCIA
    ):
        mostrar = lambda v: monto_es(v) if v is not None else "(vacío)"  # noqa: E731
        diferencias.append(f"Extractor A leyó {mostrar(total_a)} y B leyó {mostrar(total_b)} en el total")

    for campo, etiqueta in CAMPOS_TEXTO.items():
        valor_a, valor_b = getattr(a, campo), getattr(b, campo)
        if normalizar_texto(valor_a) != normalizar_texto(valor_b):
            diferencias.append(
                f"Extractor A leyó {_texto_mostrado(valor_a)} y B leyó "
                f"{_texto_mostrado(valor_b)} en {etiqueta}"
            )
    return diferencias
