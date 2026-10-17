"""Utilidades compartidas por los tests del cerebro (Dev 2)."""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

from conftest import DATOS, cargar_factura_json

from schemas import FacturaCanonica

REF = date(2026, 10, 17)
ORDEN = [f"{n:02d}" for n in range(1, 16)]
# Matriz v2 (AVISO_DEV2_cambios.md): 09 y 10 pasan de ESCALAR a FRENAR. Ver cerebro/ground_truth_v2.csv.
ESPERADO = {
    "01": "PAGAR", "02": "PAGAR", "03": "PAGAR", "04": "PAGAR", "05": "PAGAR", "06": "PAGAR",
    "07": "FRENAR", "08": "ESCALAR", "09": "FRENAR", "10": "FRENAR", "11": "ESCALAR",
    "12": "ESCALAR", "13": "FRENAR", "14": "FRENAR", "15": "ESCALAR",
}


def factura(numero: str) -> FacturaCanonica:
    return cargar_factura_json(numero)


def variante(base: str, **cambios) -> FacturaCanonica:
    """Copia de una factura del set con otro id_documento (para no chocar en el registro)."""
    original = factura(base)
    semilla = f"{base}:{sorted(cambios.items(), key=str)}".encode()
    cambios.setdefault("id_documento", hashlib.sha256(semilla).hexdigest())
    return original.model_copy(update=cambios)


def nueva_cerebro(tmp_path: Path, **kwargs):
    from cerebro import Cerebro

    kwargs.setdefault("ref_date", REF)
    return Cerebro(db_path=tmp_path / "cerebro.db", datos=DATOS, **kwargs)


def AGENTES_LENTOS(segundos: float):  # noqa: N802 - se usa como constante parametrizada
    """Los cinco agentes más uno que tarda: simula una solicitud en curso."""
    import time

    from cerebro.agentes import AGENTES

    def lento(f, ctx):
        time.sleep(segundos)
        return []

    return (*AGENTES, ("lento", lento))
