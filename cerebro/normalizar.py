"""Normalización para comparar nombres, números y cuentas: sin tildes, mayúsculas, solo A-Z0-9."""

from __future__ import annotations

import re
import unicodedata


def _ascii(texto: str) -> str:
    return unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", texto)).encode("ascii", "ignore").decode()


def clave(texto: str | None) -> str:
    if not texto:
        return ""
    return re.sub(r"[^A-Z0-9]", "", _ascii(texto).upper())


def clave_numero(texto: str | None) -> str:
    """Número de factura sin formato: 'FV-0192', 'fv 00192' y 'FV.192' → 'FV192'.

    Se separa en grupos de letras y dígitos ANTES de quitar separadores y se quitan los
    ceros a la izquierda de cada grupo numérico.
    """
    if not texto:
        return ""
    grupos = re.findall(r"[A-Z]+|\d+", _ascii(texto).upper())
    return "".join(g if g.isalpha() else str(int(g)) for g in grupos)


def ultimos4(cuenta: str | None) -> str:
    return clave(cuenta)[-4:] or "????"
