"""De CamposExtraidos (lo que leyó un modelo) a FacturaCanonica (el contrato común).

Cualquier campo crítico ilegible se convierte en un problema: nunca se inventa un valor.
"""

from __future__ import annotations

from datetime import date
from typing import get_args

from extraccion.ingesta import Documento
from extraccion.modelo import CamposExtraidos
from schemas import Canal, FacturaCanonica, Linea

FECHA_DESCONOCIDA = date(1970, 1, 1)
CANALES = frozenset(get_args(Canal))
ETIQUETAS = {
    "proveedor": "el proveedor",
    "numero_factura": "el número de factura",
    "moneda": "la moneda",
    "total": "el total",
}


def _fecha(valor: str | None, etiqueta: str, problemas: list[str]) -> date | None:
    if not valor:
        return None
    try:
        return date.fromisoformat(valor.strip())
    except ValueError:
        problemas.append(f"{etiqueta} ilegible: '{valor}'")
        return None


def _texto_libre(doc: Documento, campos: CamposExtraidos) -> str:
    """Cuerpo del correo o chat + "Observaciones" de la factura: lo que lee el agente de seguridad.

    Manda la lectura determinista del PDF; la del modelo solo se usa si el PDF no trae el bloque.
    """
    observaciones = doc.observaciones or (campos.observaciones or "").strip()
    return "\n\n".join(parte for parte in (doc.texto_libre, observaciones) if parte)


def factura_vacia(id_documento: str, archivo: str, canal: str, diferencias: list[str],
                  texto_libre: str = "", texto_oculto: list[str] | None = None) -> FacturaCanonica:
    """Factura que solo sirve para escalar: no hay datos confiables."""
    return FacturaCanonica(
        id_documento=id_documento, archivo=archivo,
        canal=canal if canal in CANALES else "web",
        proveedor="", numero_factura="", fecha_emision=FECHA_DESCONOCIDA, moneda="",
        lineas=[], subtotal=0.0, impuestos=0.0, total=0.0,
        texto_libre=texto_libre, texto_oculto=texto_oculto or [],
        extraccion_ok=False, diferencias=diferencias,
    )


def construir_factura(doc: Documento, campos: CamposExtraidos, canal: str) -> tuple[FacturaCanonica, list[str]]:
    problemas: list[str] = []

    for campo, etiqueta in ETIQUETAS.items():
        valor = getattr(campos, campo)
        if valor is None or (isinstance(valor, str) and not valor.strip()):
            problemas.append(f"No se pudo leer {etiqueta}")

    emision = _fecha(campos.fecha_emision, "La fecha de emisión", problemas)
    if emision is None and not any("emisión" in p for p in problemas):
        problemas.append("No se pudo leer la fecha de emisión")
    vencimiento = _fecha(campos.fecha_vencimiento, "La fecha de vencimiento", problemas)

    lineas = []
    for i, linea in enumerate(campos.lineas, start=1):
        faltan = [n for n in ("cantidad", "precio_unitario", "total") if getattr(linea, n) is None]
        if faltan:
            problemas.append(f"Línea {i} incompleta: falta {', '.join(faltan)}")
        lineas.append(Linea(
            descripcion=linea.descripcion,
            cantidad=linea.cantidad or 0.0,
            precio_unitario=linea.precio_unitario or 0.0,
            total=linea.total or 0.0,
        ))
    if campos.subtotal is None and lineas:
        problemas.append("No se pudo leer el subtotal")

    factura = FacturaCanonica(
        id_documento=doc.id_documento,
        archivo=doc.archivo,
        canal=canal,
        proveedor=(campos.proveedor or "").strip(),
        id_fiscal=campos.id_fiscal,
        cuenta_bancaria=campos.cuenta_bancaria,
        numero_factura=(campos.numero_factura or "").strip(),
        fecha_emision=emision or FECHA_DESCONOCIDA,
        fecha_vencimiento=vencimiento,
        moneda=(campos.moneda or "").strip().upper(),
        lineas=lineas,
        subtotal=campos.subtotal if campos.subtotal is not None else 0.0,
        impuestos=campos.impuestos or 0.0,
        total=campos.total if campos.total is not None else 0.0,
        referencia_contrato=campos.referencia_contrato,
        texto_libre=_texto_libre(doc, campos),
    )
    return factura, problemas
