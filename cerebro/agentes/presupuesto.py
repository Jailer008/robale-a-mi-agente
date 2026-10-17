"""Presupuesto/FX (100 % código): tasa vs la pactada en el contrato y frescura de la tasa.

Los límites de dinero y el saldo los evalúan las reglas; aquí solo lo que es propio del FX.
"""

from __future__ import annotations

from datetime import date

from cerebro.contexto import Contexto
from cerebro.dinero import a_decimal, numero_es
from cerebro.tipos import sin_evidencia
from schemas import FacturaCanonica, Hallazgo

NOMBRE = "presupuesto"
MAX_ANTIGUEDAD_FX_DIAS = 7


def _h(motivo: str) -> Hallazgo:
    return Hallazgo(agente=NOMBRE, severidad=1, motivo=motivo, campo="moneda")


def revisar(factura: FacturaCanonica, ctx: Contexto) -> list[Hallazgo]:
    fx = ctx.fx
    if fx is None or fx.moneda == "USD":
        return []                     # sin tasa: ya lo escala la regla "fx"; USD no tiene conversión
    hallazgos: list[Hallazgo] = []
    try:
        antiguedad = (ctx.ref_date - date.fromisoformat(fx.fecha)).days
    except ValueError:
        hallazgos.append(sin_evidencia(NOMBRE, f"La tasa {fx.moneda} no tiene una fecha válida ('{fx.fecha}').",
                                       "moneda"))
    else:
        if antiguedad > MAX_ANTIGUEDAD_FX_DIAS or antiguedad < 0:
            hallazgos.append(_h(f"La tasa {fx.moneda} es del {fx.fecha}: fuera de la ventana de "
                                f"{MAX_ANTIGUEDAD_FX_DIAS} días respecto al {ctx.ref_date.isoformat()}."))

    contrato = ctx.contrato
    if contrato and contrato.get("tasa_pactada_por_usd") is not None and str(contrato["moneda"]).upper() == fx.moneda:
        pactada = a_decimal(contrato["tasa_pactada_por_usd"])
        if pactada > 0:
            desvio = abs(fx.unidades_por_usd - pactada) / pactada
            if desvio > ctx.reglas.tolerancia_fx:
                hallazgos.append(_h(
                    f"La tasa {fx.moneda} {numero_es(fx.unidades_por_usd)} por USD se desvía "
                    f"{int((desvio * 100).to_integral_value())} % de la pactada ({numero_es(pactada)}) en el contrato "
                    f"{contrato['id']}."
                ))
    return hallazgos
