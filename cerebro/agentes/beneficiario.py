"""Beneficiario/Cuenta. Permitido/bloqueado/cuenta ya los cubren las reglas.

Extra determinista de G2: el mensaje pide cambiar datos de pago, o el ID fiscal no es el
registrado → severidad 1. (G3: Jev Noul sobre texto_libre, solo puede sumar.)
"""

from __future__ import annotations

import re

from cerebro.contexto import Contexto
from cerebro.normalizar import clave
from schemas import FacturaCanonica, Hallazgo

NOMBRE = "beneficiario"
_CAMBIO_DE_DATOS = re.compile(
    r"cambi\w*\s+(?:de\s+|el\s+|la\s+|los\s+|nuestr\w+\s+)?(?:banco|cuenta|datos\s+bancarios|datos\s+de\s+pago)"
    r"|nueva\s+cuenta|nuevos\s+datos\s+(?:bancarios|de\s+pago)"
    r"|(?:actualic|modifiqu|actualiz)\w*\s+(?:la\s+|los\s+|sus\s+|el\s+)?(?:cuenta|datos\s+bancarios|datos\s+de\s+pago)"
    r"|new\s+(?:bank|account)|changed?\s+(?:our\s+)?bank",
    re.IGNORECASE,
)


def revisar(factura: FacturaCanonica, ctx: Contexto) -> list[Hallazgo]:
    hallazgos: list[Hallazgo] = []
    coincidencia = _CAMBIO_DE_DATOS.search(factura.texto_libre or "")
    if coincidencia:
        hallazgos.append(Hallazgo(agente=NOMBRE, severidad=1, campo="texto_libre",
                                  motivo="El mensaje pide cambiar los datos de pago; requiere verificación "
                                         "por otro canal.",
                                  evidencia=f"«{coincidencia.group(0)}»", codigo="CUENTA_NO_REGISTRADA"))
    registrado = ctx.proveedor
    if registrado and factura.id_fiscal and clave(factura.id_fiscal) != clave(registrado.get("id_fiscal")):
        hallazgos.append(Hallazgo(agente=NOMBRE, severidad=1, campo="id_fiscal",
                                  motivo=f"El ID fiscal {factura.id_fiscal} no coincide con el registrado de "
                                         f"{registrado['nombre']}.", codigo="PROVEEDOR_NO_PERMITIDO"))
    return hallazgos
