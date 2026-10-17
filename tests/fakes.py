"""Dobles de prueba: ningún test llama a una API real."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from extraccion.ingesta import Documento
from extraccion.modelo import CamposExtraidos, LineaExtraida
from schemas import FacturaCanonica


def campos_desde(f: FacturaCanonica, **cambios) -> CamposExtraidos:
    datos = dict(
        proveedor=f.proveedor, id_fiscal=f.id_fiscal, cuenta_bancaria=f.cuenta_bancaria,
        numero_factura=f.numero_factura, fecha_emision=f.fecha_emision.isoformat(),
        fecha_vencimiento=f.fecha_vencimiento.isoformat() if f.fecha_vencimiento else None,
        moneda=f.moneda,
        lineas=[LineaExtraida(**l.model_dump()) for l in f.lineas],
        subtotal=f.subtotal, impuestos=f.impuestos, total=f.total,
        referencia_contrato=f.referencia_contrato,
    )
    return CamposExtraidos(**(datos | cambios))


@dataclass
class ExtractorFalso:
    """Responde por id_documento; una Exception en las respuestas se lanza."""

    nombre: str
    respuestas: dict[str, CamposExtraidos | Exception] = field(default_factory=dict)
    por_defecto: CamposExtraidos | Exception | None = None
    demora_s: float = 0.0
    llamadas: list[str] = field(default_factory=list)

    def __call__(self, doc: Documento) -> CamposExtraidos:
        self.llamadas.append(doc.id_documento)
        if self.demora_s:
            time.sleep(self.demora_s)
        respuesta = self.respuestas.get(doc.id_documento, self.por_defecto)
        if respuesta is None:
            raise RuntimeError("sin respuesta preparada")
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta
