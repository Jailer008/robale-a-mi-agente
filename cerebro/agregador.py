"""Agregador monotónico: decisión = max(reglas, hallazgos, fallos). Nada baja la severidad.

PAGAR exige además extracción válida, política ALLOW y cero hallazgos; si la
severidad saliera 0 sin cumplir las tres, se sube a ESCALAR con el motivo visible.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from cerebro.contexto import Contexto
from cerebro.dinero import usd_es
from cerebro.reglas import Falla
from schemas import DecisionTipo, Hallazgo

DECISION: dict[int, DecisionTipo] = {0: "PAGAR", 1: "ESCALAR", 2: "FRENAR"}


@dataclass(frozen=True, slots=True)
class Resultado:
    decision: DecisionTipo
    severidad: int
    hallazgos: list[Hallazgo]          # ordenados de mayor a menor severidad (estable)


def agregar(*, extraccion_ok: bool, cedar: str, fallas: Sequence[Falla], hallazgos: Sequence[Hallazgo],
            fallos: Sequence[Hallazgo] = ()) -> Resultado:
    todos = [f.como_hallazgo() for f in fallas] + list(hallazgos) + list(fallos)
    severidad = max([0] + [h.severidad for h in todos])
    if severidad == 0 and not (extraccion_ok and cedar == "ALLOW" and not todos):
        faltantes = [texto for falta, texto in ((not extraccion_ok, "extracción no validada"),
                                                (cedar != "ALLOW", "la política no dio ALLOW"),
                                                (bool(todos), "hay hallazgos sin resolver")) if falta]
        todos.append(Hallazgo(agente="agregador", severidad=1,
                              motivo="No se puede pagar: " + ", ".join(faltantes) + "."))
        severidad = 1
    ordenados = sorted(todos, key=lambda h: -h.severidad)
    return Resultado(DECISION[severidad], severidad, ordenados)


def resumen(hallazgos: Sequence[Hallazgo]) -> str:
    principal = hallazgos[0].motivo
    resto = len(hallazgos) - 1
    return principal if not resto else f"{principal} (y {resto} motivo{'s' if resto != 1 else ''} más)"


def explicar(resultado: Resultado, ctx: Contexto) -> str:
    if resultado.decision != "PAGAR":
        return resumen(resultado.hallazgos)
    monto = ctx.monto_usd_cents or 0
    r = ctx.reglas
    usado = Decimal((ctx.gastado_mes_global_cents + monto) * 100) / Decimal(r.limite_mes_global_cents)
    porcentaje = int(usado.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return (f"Pago autorizado (simulado): {ctx.nombre_factura}, {usd_es(monto)}, dentro del límite de "
            f"{usd_es(r.limite_pago_cents)} (presupuesto mensual usado: {porcentaje} %).")
