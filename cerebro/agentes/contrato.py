"""Contrato: cada línea debe corresponder a un ítem del contrato y su precio estar dentro de ±5 %.

G2: el "map" casa por descripción normalizada (exacta). Una línea que no casa → severidad 1
("ninguno"). En G3, Jev Choice podrá proponer el ítem; el reduce (precio) sigue en código.
"""

from __future__ import annotations

from decimal import Decimal

from cerebro.contexto import Contexto
from cerebro.dinero import a_decimal, numero_es
from cerebro.normalizar import clave
from schemas import FacturaCanonica, Hallazgo

NOMBRE = "contrato"


def _h(motivo: str, campo: str = "lineas") -> Hallazgo:
    return Hallazgo(agente=NOMBRE, severidad=1, motivo=motivo, campo=campo)


def revisar(factura: FacturaCanonica, ctx: Contexto) -> list[Hallazgo]:
    if not ctx.beneficiario_permitido:
        return []                      # sin proveedor permitido no hay contrato: lo escalan las reglas
    contrato = ctx.contrato
    if contrato is None:
        return [_h(f"No hay contrato vigente con {ctx.nombre_factura}.", "referencia_contrato")]
    cid = contrato["id"]
    hallazgos: list[Hallazgo] = []
    if factura.referencia_contrato and clave(factura.referencia_contrato) != clave(cid):
        hallazgos.append(_h(f"La factura cita el contrato {factura.referencia_contrato}, pero el vigente con "
                            f"{contrato['proveedor']} es {cid}.", "referencia_contrato"))
    if ctx.moneda != str(contrato["moneda"]).upper():
        hallazgos.append(_h(f"La factura está en {ctx.moneda} y el contrato {cid} en {contrato['moneda']}.", "moneda"))

    items = {clave(i["descripcion"]): i for i in contrato.get("items", [])}
    tolerancia: Decimal = ctx.reglas.tolerancia_contrato
    for n, linea in enumerate(factura.lineas, start=1):
        item = items.get(clave(linea.descripcion))
        if item is None:
            hallazgos.append(_h(f"Línea {n} ('{linea.descripcion}') no corresponde a ningún ítem del contrato {cid}."))
            continue
        try:
            precio, pactado = a_decimal(linea.precio_unitario), a_decimal(item["precio_unitario"])
        except ValueError:
            hallazgos.append(_h(f"Línea {n}: el precio no es un número válido."))
            continue
        if pactado <= 0:
            hallazgos.append(_h(f"Línea {n}: el contrato {cid} no tiene un precio válido para "
                                f"'{item['descripcion']}'."))
            continue
        desvio = (precio - pactado) / pactado
        if abs(desvio) > tolerancia:
            unidad = f"/{item['unidad'][0]}" if item.get("unidad") == "hora" else ""
            porcentaje = int((desvio * 100).to_integral_value())
            hallazgos.append(_h(
                f"Línea {n}: tarifa {ctx.moneda} {numero_es(precio)}{unidad} "
                f"vs {ctx.moneda} {numero_es(pactado)}{unidad} "
                f"del contrato {cid} ({porcentaje:+d} %)."
            ))
    return hallazgos
