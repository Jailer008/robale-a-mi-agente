"""Duplicados contra `pagos` (histórico + autorizaciones simuladas).

- Mismo proveedor + número + monto → severidad 2 (FRENAR).
- Mismo proveedor + número con otro monto → severidad 1.
- Candidato difuso: mismo proveedor y moneda, monto ±2 % y fecha ±15 días → severidad 1.
  En G2 se escala directo; en G3 Jev podrá confirmar, nunca descartar.
  "Número parecido" NO dispara solo: NS-2026-0145 (limpia) está a distancia 2 de NS-2026-0138.
- Los números se comparan sin formato: 'FV-0192' == 'fv 00192' == 'FV.192' (clave_numero).
"""

from __future__ import annotations

from decimal import Decimal

from cerebro.contexto import Contexto
from cerebro.dinero import a_decimal, monto_es
from cerebro.normalizar import clave, clave_numero
from cerebro.tipos import sin_evidencia
from schemas import FacturaCanonica, Hallazgo

NOMBRE = "duplicados"
_IGUAL = Decimal("0.01")


def revisar(factura: FacturaCanonica, ctx: Contexto) -> list[Hallazgo]:
    if ctx.monto_original is None:
        return [sin_evidencia(NOMBRE, "No se pudo buscar duplicados: el monto no es confiable.", "total")]
    proveedor, numero, moneda = clave(factura.proveedor), clave_numero(factura.numero_factura), ctx.moneda
    r = ctx.reglas
    hallazgos: list[Hallazgo] = []
    for pago in ctx.pagos:
        if clave(pago.proveedor) != proveedor:
            continue
        monto_previo = a_decimal(pago.monto)
        mismo_monto = pago.moneda == moneda and abs(monto_previo - ctx.monto_original) <= _IGUAL
        previo = f"{pago.numero_factura} de {pago.proveedor} ya se pagó el {pago.fecha_pago.isoformat()} " \
                 f"por {monto_es(monto_previo, pago.moneda)}"
        if numero and clave_numero(pago.numero_factura) == numero:
            if mismo_monto:
                hallazgos.append(Hallazgo(agente=NOMBRE, severidad=2, campo="numero_factura",
                                          motivo=f"Duplicado exacto: {previo}.", evidencia=f"pago={pago.factura_id}"))
            else:
                hallazgos.append(Hallazgo(agente=NOMBRE, severidad=1, campo="numero_factura",
                                          motivo=f"El número {factura.numero_factura} ya se usó: {previo}.",
                                          evidencia=f"pago={pago.factura_id}"))
            continue
        if pago.moneda != moneda or monto_previo <= 0:
            continue
        desvio = abs(monto_previo - ctx.monto_original) / monto_previo
        dias = abs((pago.fecha_pago - factura.fecha_emision).days)
        if desvio <= r.tolerancia_monto_duplicado and dias <= r.ventana_duplicados_dias:
            hallazgos.append(Hallazgo(
                agente=NOMBRE, severidad=1, campo="total",
                motivo=f"Posible duplicado disfrazado de {pago.numero_factura}: otro número, mismo proveedor, "
                       f"monto {monto_es(ctx.monto_original, moneda)} vs {monto_es(monto_previo, pago.moneda)} "
                       f"y {dias} día{'' if dias == 1 else 's'} de diferencia.",
                evidencia=f"pago={pago.factura_id}",
            ))
    return hallazgos
