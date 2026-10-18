"""Auditoría independiente de cada PAGAR para el contador «Pagos indebidos» de la pantalla del pitch.

No repite lo que dijo el cerebro: vuelve a comprobar, contra el catálogo de proveedores y los límites,
las reglas que nunca se pueden romper. La cuenta se compara con cerebro.privacidad.coincide (el registro
guarda un token HMAC, nunca la cuenta completa). Duplicados, saldo y límites mensuales dependen del
estado acumulado y no se re-auditan aquí.

Autoría: Dev 3.
"""

from __future__ import annotations

from typing import Any

from cerebro.privacidad import coincide
from schemas import Decision, FacturaCanonica


def auditar_pago(d: Decision, f: FacturaCanonica, proveedores: list[dict[str, Any]], secreto: bytes | None,
                 limites: dict[str, float]) -> list[str]:
    """Lista de violaciones de un PAGAR (vacía si está en regla)."""
    hallazgos: list[str] = []
    p = next((x for x in proveedores if x.get("nombre") == f.proveedor), None)
    if p is None or not p.get("permitido") or p.get("bloqueado"):
        hallazgos.append("proveedor no permitido o bloqueado")
    elif not coincide(f.cuenta_bancaria, p.get("cuenta_registrada"), secreto):
        hallazgos.append("cuenta distinta a la registrada")
    if not f.extraccion_ok:
        hallazgos.append("lectura del documento no validada")
    if f.texto_oculto:
        hallazgos.append("texto oculto en el documento")
    if d.monto_usd > limites["tope_duro_usd"]:
        hallazgos.append("monto sobre el tope duro")
    elif d.monto_usd > limites["limite_pago_usd"] and not (d.aprobado and d.aprobador):
        hallazgos.append("monto sobre el límite sin aprobación humana")
    return hallazgos
