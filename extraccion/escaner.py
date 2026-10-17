"""Escáner determinista de texto oculto en PDF (sin modelos).

Marca texto que un humano no ve pero un modelo sí lee: blanco o casi blanco sin
fondo oscuro debajo, fuente menor a 4 pt, totalmente transparente o fuera de la
página. Cualquier hallazgo lleva la factura a FRENAR en el cerebro.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pymupdf

Motivo = Literal["blanco", "diminuto", "fuera_de_pagina", "transparente"]

TAMANO_MINIMO_PT = 4.0
CANAL_CASI_BLANCO = 0xF0          # cada canal RGB >= 240
LUMINANCIA_FONDO_OSCURO = 0.85    # un fondo por debajo de esto hace visible el texto blanco
# Sin TEXT_MEDIABOX_CLIP PyMuPDF también devuelve el texto fuera de la página.
FLAGS = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_MEDIABOX_CLIP


@dataclass(frozen=True, slots=True)
class FragmentoOculto:
    texto: str
    motivo: Motivo
    pagina: int


def _casi_blanco(color: int) -> bool:
    r, g, b = (color >> 16) & 0xFF, (color >> 8) & 0xFF, color & 0xFF
    return min(r, g, b) >= CANAL_CASI_BLANCO


def _fondos_oscuros(pagina: pymupdf.Page) -> list[pymupdf.Rect]:
    fondos = []
    for dibujo in pagina.get_drawings():
        relleno = dibujo.get("fill")
        if not relleno:
            continue
        r, g, b = (list(relleno) + [0, 0, 0])[:3]
        if 0.2126 * r + 0.7152 * g + 0.0722 * b < LUMINANCIA_FONDO_OSCURO:
            fondos.append(pymupdf.Rect(dibujo["rect"]))
    return fondos


def _motivo(span: dict, pagina: pymupdf.Page, fondos: list[pymupdf.Rect]) -> Motivo | None:
    caja = pymupdf.Rect(span["bbox"])
    if not caja.intersects(pagina.rect):
        return "fuera_de_pagina"
    if span.get("alpha", 255) == 0:
        return "transparente"
    if span["size"] < TAMANO_MINIMO_PT:
        return "diminuto"
    if _casi_blanco(span["color"]):
        centro = pymupdf.Point((caja.x0 + caja.x1) / 2, (caja.y0 + caja.y1) / 2)
        if not any(centro in fondo for fondo in fondos):
            return "blanco"
    return None


def escanear_pdf(datos: bytes) -> list[FragmentoOculto]:
    """Devuelve los fragmentos ocultos agrupados por línea. Lanza ValueError si no es un PDF."""
    try:
        doc = pymupdf.open(stream=datos, filetype="pdf")
    except Exception as error:  # PyMuPDF lanza varios tipos según el daño del archivo
        raise ValueError(f"No se pudo abrir el PDF: {error}") from error

    hallados: list[FragmentoOculto] = []
    with doc:
        for numero, pagina in enumerate(doc, start=1):
            fondos = _fondos_oscuros(pagina)
            texto = pagina.get_text("dict", flags=FLAGS, clip=pymupdf.INFINITE_RECT())
            for bloque in texto["blocks"]:
                for linea in bloque.get("lines", []):
                    partes: list[str] = []
                    motivo_linea: Motivo | None = None
                    for span in linea["spans"]:
                        if not span["text"].strip():
                            continue
                        motivo = _motivo(span, pagina, fondos)
                        if motivo:
                            partes.append(span["text"])
                            motivo_linea = motivo_linea or motivo
                    if partes and motivo_linea:
                        texto = " ".join(" ".join(partes).split())
                        hallados.append(FragmentoOculto(texto, motivo_linea, numero))
    return hallados


def textos_ocultos(datos: bytes) -> list[str]:
    return [fragmento.texto for fragmento in escanear_pdf(datos)]
