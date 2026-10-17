"""Modo en vivo: facturas base que el jurado puede falsificar desde el celular.

El agente lee el documento, no el formulario: lo que el jurado edita se vuelve a
dibujar como PDF y ese PDF entra al pipeline normal (escáner → extractores → validador).
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from pydantic import BaseModel

from schemas import DecisionTipo, Linea

RAIZ = Path(__file__).resolve().parent.parent
BASES = RAIZ / "datos" / "base"
_ID_BASE = re.compile(r"^base_\d{2}$")


class FacturaBase(BaseModel):
    base_id: str
    proveedor: str
    id_fiscal: str
    pais: str
    numero: str
    fecha_emision: date
    fecha_vencimiento: date
    moneda: str
    lineas: list[Linea]
    subtotal: float
    impuestos: float = 0.0
    total: float
    cuenta: str
    referencia_contrato: str
    nota_visible: str = ""
    nota_oculta: str = ""
    esperado_tal_cual: DecisionTipo
    pista: str = ""


def listar_bases() -> list[str]:
    return sorted(p.stem for p in BASES.glob("base_*.json") if _ID_BASE.match(p.stem))


def cargar_base(base_id: str) -> FacturaBase:
    """Lanza ValueError si el id no es del pool (evita rutas arbitrarias)."""
    if not _ID_BASE.match(base_id) or base_id not in listar_bases():
        raise ValueError(f"Factura base desconocida: {base_id!r}")
    return FacturaBase.model_validate_json((BASES / f"{base_id}.json").read_text(encoding="utf-8"))
