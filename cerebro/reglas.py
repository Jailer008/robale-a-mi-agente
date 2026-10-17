"""Reglas deterministas: opción B de DEV2 §1.3 (Python puro, misma lógica que la política Cedar).

ALLOW solo si TODAS las condiciones del `permit` se cumplen y la extracción está validada.
Cada condición que falla devuelve su severidad y su frase en español.
Si falta un dato para evaluar una regla de dinero, la regla no se da por cumplida.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from cerebro.contexto import Contexto
from cerebro.dinero import usd_es
from cerebro.normalizar import ultimos4
from schemas import Hallazgo


@dataclass(frozen=True, slots=True)
class Falla:
    regla: str
    severidad: Literal[1, 2]
    motivo: str
    campo: str | None = None
    evidencia: str = ""

    def como_hallazgo(self) -> Hallazgo:
        return Hallazgo(agente="reglas", severidad=self.severidad, motivo=self.motivo,
                        evidencia=self.evidencia or f"regla={self.regla}", campo=self.campo)


@dataclass(frozen=True, slots=True)
class Evaluacion:
    cedar: Literal["ALLOW", "DENY"]
    fallas: list[Falla]


def _reglas_de_dinero(ctx: Contexto, monto: int) -> list[Falla]:
    r = ctx.reglas
    fallas: list[Falla] = []
    if monto > r.tope_duro_cents:
        fallas.append(Falla("tope_duro", 2, f"{usd_es(monto)} supera el tope duro de {usd_es(r.tope_duro_cents)}.",
                            "total"))
    elif monto > r.limite_pago_cents:
        fallas.append(Falla("limite_pago", 1, f"{usd_es(monto)} supera el límite de {usd_es(r.limite_pago_cents)} "
                            "sin aprobación humana.", "total"))
    if ctx.gastado_mes_proveedor_cents + monto > r.limite_mes_proveedor_cents:
        fallas.append(Falla("mensual_proveedor", 2, "Excede el tope mensual del proveedor "
                            f"({usd_es(r.limite_mes_proveedor_cents)}): ya se pagaron "
                            f"{usd_es(ctx.gastado_mes_proveedor_cents)} este mes.", "total"))
    if ctx.gastado_mes_global_cents + monto > r.limite_mes_global_cents:
        fallas.append(Falla("mensual_global", 2, "Excede el tope mensual global "
                            f"({usd_es(r.limite_mes_global_cents)}): ya se pagaron "
                            f"{usd_es(ctx.gastado_mes_global_cents)} este mes.", "total"))
    if monto > ctx.saldo_cents:
        fallas.append(Falla("saldo", 2, f"Saldo de {usd_es(ctx.saldo_cents)} menor a los {usd_es(monto)} requeridos.",
                            "total"))
    return fallas


def evaluar(ctx: Contexto) -> Evaluacion:
    fallas: list[Falla] = []

    if not ctx.extraccion_ok:
        detalle = "; ".join(ctx.diferencias) or "sin detalle del extractor"
        fallas.append(Falla("extraccion", 1, f"Extracción no validada: {detalle}", "extraccion_ok"))
    if ctx.problemas:
        fallas.append(Falla("datos", 1, "Datos no confiables: " + "; ".join(ctx.problemas) + "."))
    if ctx.fx is None or ctx.monto_usd_cents is None:
        moneda = ctx.moneda or "sin moneda"
        fallas.append(Falla("fx", 1, f"No se puede convertir el monto a USD de forma confiable ({moneda}); "
                            "no se evalúan los límites de dinero.", "moneda"))

    if ctx.beneficiario_bloqueado:
        fallas.append(Falla("beneficiario_bloqueado", 2, "El proveedor está bloqueado por la empresa.", "proveedor"))
    elif not ctx.beneficiario_permitido:
        nombre = (ctx.proveedor or {}).get("nombre") or ctx.nombre_factura
        fallas.append(Falla("beneficiario_no_permitido", 1, f"'{nombre}' no está en la lista aprobada.", "proveedor"))
    elif not ctx.cuenta_coincide:
        registrada = ultimos4(ctx.proveedor.get("cuenta_registrada"))
        if ctx.cuenta_factura:
            motivo = f"Cuenta termina en {ultimos4(ctx.cuenta_factura)}; la registrada termina en {registrada}."
        else:
            motivo = f"No se pudo leer la cuenta de la factura; la registrada termina en {registrada}."
        fallas.append(Falla("cuenta", 1, motivo, "cuenta_bancaria"))

    if ctx.monto_usd_cents is not None:
        fallas += _reglas_de_dinero(ctx, ctx.monto_usd_cents)

    return Evaluacion("ALLOW" if not fallas else "DENY", fallas)


def reglas_de_dinero_con(ctx: Contexto, monto_cents: int) -> list[Falla]:
    """Reevalúa solo las reglas de dinero con otro monto (para el contrafactual)."""
    return _reglas_de_dinero(ctx, monto_cents)
