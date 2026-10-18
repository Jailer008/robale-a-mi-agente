"""Modo «FACTURA FALSIFICADA» (plan v2): el agente lee el documento, no el formulario.

El jurado recibe una factura base del pool de Dev 1 (datos/base/), cambia lo que quiera (monto, cuenta,
proveedor, número, una nota visible u oculta) y elige qué rayar. El servidor:
- valida los cambios con las reglas de Dev 1 (extraccion.render.validar_cambios → 422 si no pasan);
- vuelve a DIBUJAR la factura como PDF (render_factura) y la guarda en entrada/falsificadas/;
- pasa ese PDF por extraer() → decidir(), igual que cualquier documento.
Nunca entrega los campos del formulario al cerebro.

Autoría: Dev 3.
"""

from __future__ import annotations

import base64
import binascii
import secrets
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cerebro.privacidad import enmascarar
from extraccion.render import (
    CambiosInvalidos,
    FacturaBase,
    aplicar_cambios,
    cargar_base,
    listar_bases,
    rayones_sobre,
    render_factura,
    validar_cambios,
)

ETIQUETA_FALSIFICADA = "FACTURA FALSIFICADA — EL AGENTE LEE EL DOCUMENTO"
CARPETA = "falsificadas"
_MAX_B64 = 2_800_000                 # ~2 MB de PNG en base64 (el límite de render_factura)


class CasoFalsificado(BaseModel):
    """Lo único que el celular puede enviar. Cualquier otro campo → 422."""
    model_config = ConfigDict(extra="forbid")
    sesion_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")
    base_id: str = Field(pattern=r"^base_\d{2}$")
    cambios: dict[str, Any] = Field(default_factory=dict, max_length=6)
    rayar: list[Literal["total", "cuenta", "numero"]] = Field(default_factory=list, max_length=3)
    rayones_png_b64: str | None = Field(default=None, max_length=_MAX_B64)

    @model_validator(mode="after")
    def _un_tipo_de_rayon(self) -> CasoFalsificado:
        if self.rayar and self.rayones_png_b64:
            raise ValueError("usa 'rayar' o 'rayones_png_b64', no ambos")
        return self


def resumen_base(f: FacturaBase) -> dict[str, Any]:
    """Lo que ve el celular al cargar: nunca la cuenta completa ni el resultado esperado."""
    return {"base_id": f.base_id, "etiqueta_modo": ETIQUETA_FALSIFICADA, "proveedor": f.proveedor,
            "numero": f.numero, "moneda": f.moneda, "total": f.total, "cuenta_enmascarada": enmascarar(f.cuenta),
            "pista": f.pista, "preview_url": f"/falsificar/base/{f.base_id}/preview.png"}


def base_aleatoria() -> dict[str, Any]:
    return resumen_base(cargar_base(secrets.choice(listar_bases())))


def _rayones(caso: CasoFalsificado, aplicada: FacturaBase) -> bytes | None:
    if caso.rayones_png_b64:
        try:
            return base64.b64decode(caso.rayones_png_b64, validate=True)
        except (binascii.Error, ValueError) as error:
            raise CambiosInvalidos("Los rayones deben venir en base64") from error
    return rayones_sobre(aplicada, list(caso.rayar)) if caso.rayar else None


def campos_cambiados(base: FacturaBase, cambios: dict[str, Any], con_rayones: bool) -> list[str]:
    """Qué cambió de verdad (para el feed): nunca el contenido, solo el nombre del campo."""
    actuales = {"monto": base.total, "cuenta": base.cuenta, "proveedor": base.proveedor, "numero": base.numero}
    salida = [c for c in ("monto", "cuenta", "proveedor", "numero") if c in cambios and cambios[c] != actuales[c]]
    if cambios.get("nota"):
        salida.append("nota")
    return salida + (["rayones"] if con_rayones else [])


def dibujar(caso: CasoFalsificado, sufijo: str, entrada: Path) -> tuple[Path, list[str]]:
    """Valida, dibuja el PDF falsificado y devuelve su ruta. Lanza CambiosInvalidos (→ 422)."""
    base = cargar_base(caso.base_id)
    limpios = validar_cambios(caso.cambios)
    aplicada = aplicar_cambios(base, limpios, sufijo)
    rayones = _rayones(caso, aplicada)
    ruta = render_factura(caso.base_id, limpios, rayones, sufijo, Path(entrada) / CARPETA)
    return ruta, campos_cambiados(base, limpios, rayones is not None)
