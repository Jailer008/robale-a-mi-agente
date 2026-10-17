"""Normalización para comparar nombres, números y cuentas: sin tildes, mayúsculas, solo A-Z0-9."""

from __future__ import annotations

import re
import unicodedata


def clave(texto: str | None) -> str:
    if not texto:
        return ""
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]", "", sin_tildes.upper())


def ultimos4(cuenta: str | None) -> str:
    return clave(cuenta)[-4:] or "????"
