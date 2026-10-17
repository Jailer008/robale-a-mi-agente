"""Contrafactual: "Se habría pagado si …". Por cada regla fallida se calcula el valor frontera.

Para las reglas de dinero la frontera es el mayor monto que cumple TODAS a la vez, y se
reevalúa con ese monto para confirmar que pasa. Un FRENAR que no depende de un valor
(texto oculto, duplicado exacto, proveedor bloqueado) no tiene contrafactual.
"""

from __future__ import annotations

from collections.abc import Sequence

from cerebro.contexto import Contexto
from cerebro.dinero import usd_es
from cerebro.normalizar import ultimos4
from cerebro.reglas import Falla, reglas_de_dinero_con
from cerebro.tipos import tipo_de
from schemas import Hallazgo

DINERO = frozenset({"limite_pago", "tope_duro", "mensual_proveedor", "mensual_global", "saldo"})
# v2: FRENAR por identidad del beneficiario, pero con una condición verificable (alta / cuenta verificada).
CON_CONDICION = frozenset({"cuenta", "beneficiario_no_permitido"})
_POR_AGENTE = {
    "duplicados": "no existiera un pago previo parecido",
    "contrato": "las líneas cuadraran con el contrato",
    "presupuesto": "la tasa FX estuviera dentro de la tolerancia del contrato",
}


def _frontera_de_dinero(ctx: Contexto) -> str:
    r = ctx.reglas
    frontera = min(r.limite_pago_cents, r.tope_duro_cents,
                   r.limite_mes_proveedor_cents - ctx.gastado_mes_proveedor_cents,
                   r.limite_mes_global_cents - ctx.gastado_mes_global_cents, ctx.saldo_cents)
    if frontera <= 0 or reglas_de_dinero_con(ctx, frontera):
        return "hubiera presupuesto y saldo disponibles este mes"
    return f"el monto fuera ≤ {usd_es(frontera)}"


def _por_regla(falla: Falla, ctx: Contexto) -> str:
    if falla.regla == "beneficiario_no_permitido":
        return f"'{ctx.nombre_factura}' estuviera en la lista permitida"
    if falla.regla == "cuenta":
        registrada = ultimos4((ctx.proveedor or {}).get("cuenta_registrada"))
        return f"la cuenta coincidiera con la registrada (termina en {registrada})"
    if falla.regla == "extraccion":
        return "la extracción se validara (A y B coinciden y la aritmética cuadra)"
    if falla.regla == "fx":
        return f"hubiera una tasa FX confiable para {ctx.moneda or 'la moneda'}"
    return "los datos de la factura fueran coherentes"


def _por_hallazgo(h: Hallazgo) -> str:
    if h.agente == "beneficiario":
        return ("el ID fiscal coincidiera con el registrado" if h.campo == "id_fiscal"
                else "el mensaje no pidiera cambiar los datos de pago")
    if tipo_de(h) == "fallo_tecnico":
        return f"la verificación de {h.agente} no hubiera fallado"
    if tipo_de(h) == "sin_evidencia":
        return f"hubiera datos suficientes para que {h.agente} verifique"
    return _POR_AGENTE.get(h.agente, f"se resolviera el hallazgo de {h.agente}")


def contrafactual(ctx: Contexto, fallas: Sequence[Falla], hallazgos: Sequence[Hallazgo]) -> str | None:
    if not fallas and not hallazgos:
        return None
    sin_frontera = [f.motivo for f in fallas if f.severidad == 2 and f.regla not in DINERO | CON_CONDICION]
    sin_frontera += [h.motivo for h in hallazgos if h.severidad == 2]
    if sin_frontera:
        return f"Sin contrafactual: {sin_frontera[0]} No se corrige cambiando un valor."

    condiciones: list[str] = []
    if any(f.regla in DINERO for f in fallas):
        condiciones.append(_frontera_de_dinero(ctx))
    condiciones += [_por_regla(f, ctx) for f in fallas if f.regla not in DINERO]
    condiciones += [_por_hallazgo(h) for h in hallazgos]
    return "Se habría pagado si " + " y ".join(dict.fromkeys(condiciones)) + "."
