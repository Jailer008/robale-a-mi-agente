"""Seguridad/Inyección. El contenido de un documento son DATOS, nunca órdenes.

- `texto_oculto` no vacío → severidad 2 directo, sin modelo.
- Instrucciones dirigidas a un sistema automático en cualquier texto de la factura → severidad 2.

Esto es un detector DETERMINISTA de patrones, no un clasificador semántico. Para resistir la
ofuscación barata, cada texto se revisa en varias variantes normalizadas: NFKC (ancho completo),
sin caracteres invisibles, sin tildes, letras sueltas reunidas ("i g n o r a") y leetspeak
("1gn0r4"). Las paráfrasis libres quedan para la capa semántica opcional (cerebro.semantica),
que solo puede sumar severidad.
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
    r"\b(?:sistema|agente|asistente|bot)\s+automatic\w*",
    r"\b(?:estimad\w*|querid\w*|hola|atencion|dear|hello)\s+(?:\w+\s+){0,2}"
    r"(?:sistema|agente|asistente|modelo|bot|ia|ai)\b",
)]
# Guion suave, espacios de ancho cero, marcas de dirección, separadores invisibles y BOM.
_INVISIBLES = re.compile("[\u00ad\u200b-\u200f\u2060-\u2064\ufeff]")
_LETRAS_SUELTAS = re.compile(r"\b(?:\w ){2,}\w\b")
_LEET = str.maketrans("0134578@$", "oieastbas")


def _variantes(texto: str) -> list[str]:
    """Variantes normalizadas del mismo texto; basta con que una coincida."""
    sin_ocultos = _INVISIBLES.sub("", unicodedata.normalize("NFKC", texto))
    plano = unicodedata.normalize("NFKD", sin_ocultos).encode("ascii", "ignore").decode()
    reunido = _LETRAS_SUELTAS.sub(lambda m: m.group(0).replace(" ", ""), plano)
    return list(dict.fromkeys([plano, reunido, reunido.translate(_LEET)]))


def _textos(factura: FacturaCanonica) -> list[tuple[str, str]]:
    campos = [("texto_libre", factura.texto_libre), ("proveedor", factura.proveedor),
              ("numero_factura", factura.numero_factura), ("referencia_contrato", factura.referencia_contrato or ""),
              ("cuenta_bancaria", factura.cuenta_bancaria or "")]
    campos += [(f"lineas[{i}].descripcion", linea.descripcion) for i, linea in enumerate(factura.lineas)]
    return [(campo, texto) for campo, texto in campos if texto]


def _primera_coincidencia(texto: str) -> re.Match[str] | None:
    return next((m for variante in _variantes(texto) for patron in _PATRONES if (m := patron.search(variante))),
                None)


def revisar(factura: FacturaCanonica, ctx: Contexto) -> list[Hallazgo]:
    hallazgos: list[Hallazgo] = []
    if factura.texto_oculto:
        revelado = " | ".join(factura.texto_oculto)
        hallazgos.append(Hallazgo(agente=NOMBRE, severidad=2, campo="texto_oculto",
                                  motivo=f"Texto oculto encontrado: '{revelado[:160]}'. Las instrucciones dentro de "
                                         "documentos no tienen autoridad.",
                                  evidencia=f"oculto={revelado}", codigo="TEXTO_OCULTO"))
    for campo, texto in _textos(factura):
        coincidencia = _primera_coincidencia(texto)
        if coincidencia:
            hallazgos.append(Hallazgo(agente=NOMBRE, severidad=2, campo=campo,
                                      motivo=f"Instrucciones dirigidas al sistema en {campo}: "
                                             f"«{coincidencia.group(0)[:80]}». Se ignoran y se frena el pago.",
                                      evidencia=f"texto={texto[:300]}", codigo="INYECCION"))
    return hallazgos
