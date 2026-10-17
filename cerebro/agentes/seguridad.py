"""Seguridad/Inyección. El contenido de un documento son DATOS, nunca órdenes.

- `texto_oculto` no vacío → severidad 2 directo, sin modelo.
- Instrucciones dirigidas a un sistema automático en cualquier texto de la factura → severidad 2.
  G2 usa patrones deterministas; G3 añade Jev Noul (p ≥ umbral → 2), que solo puede sumar.
"""

from __future__ import annotations

import re
import unicodedata

from cerebro.contexto import Contexto
from schemas import FacturaCanonica, Hallazgo

NOMBRE = "seguridad"
_PATRONES = [re.compile(p, re.IGNORECASE) for p in (
    r"\bignor\w*\b.{0,40}\b(?:regla|instruccion|politica|limite|control|rule|instruction|previous|anterior)",
    r"\b(?:disregard|override|bypass)\b",
    r"\bolvid\w*\b.{0,40}\b(?:regla|instruccion|politica|todo)",
    r"\b(?:aprueb\w*|aprobar|approve\w*|autoriz\w*)\b.{0,30}\b(?:pago|payment|transferencia|transfer)",
    r"\b(?:system|sistema|assistant|asistente|developer)\s*:",
    r"\b(?:eres|actua\s+como|act\s+as|you\s+are)\b.{0,30}\b(?:asistente|agente|modelo|ia|ai|assistant|bot)\b",
    r"\b(?:prompt|jailbreak|modo\s+desarrollador|developer\s+mode)\b",
    r"\b(?:no|sin)\s+(?:escal\w*|fren\w*|verific\w*|revis\w*|valid\w*)\b",
    r"\bmarc\w*\b.{0,20}\b(?:pagad|aprobad|segur|valid)",
    r"<\|[^|]*\|>|\[/?inst\]|###\s*instruction",
)]


def _plano(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()


def _textos(factura: FacturaCanonica) -> list[tuple[str, str]]:
    campos = [("texto_libre", factura.texto_libre), ("proveedor", factura.proveedor),
              ("numero_factura", factura.numero_factura), ("referencia_contrato", factura.referencia_contrato or ""),
              ("cuenta_bancaria", factura.cuenta_bancaria or "")]
    campos += [(f"lineas[{i}].descripcion", linea.descripcion) for i, linea in enumerate(factura.lineas)]
    return [(campo, texto) for campo, texto in campos if texto]


def revisar(factura: FacturaCanonica, ctx: Contexto) -> list[Hallazgo]:
    hallazgos: list[Hallazgo] = []
    if factura.texto_oculto:
        revelado = " | ".join(factura.texto_oculto)
        hallazgos.append(Hallazgo(agente=NOMBRE, severidad=2, campo="texto_oculto",
                                  motivo=f"Texto oculto encontrado: '{revelado[:160]}'. Las instrucciones dentro de "
                                         "documentos no tienen autoridad.",
                                  evidencia=revelado))
    for campo, texto in _textos(factura):
        plano = _plano(texto)
        for patron in _PATRONES:
            coincidencia = patron.search(plano)
            if coincidencia:
                hallazgos.append(Hallazgo(agente=NOMBRE, severidad=2, campo=campo,
                                          motivo=f"Instrucciones dirigidas al sistema en {campo}: "
                                                 f"«{coincidencia.group(0)[:80]}». Se ignoran y se frena el pago.",
                                          evidencia=texto[:300]))
                break
    return hallazgos
