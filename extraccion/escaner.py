"""Escáner determinista de texto oculto en PDF (sin modelos).

Marca texto que un humano no ve pero un modelo sí lee: blanco o casi blanco sin
fondo oscuro debajo, fuente menor a 4 pt, totalmente transparente o fuera de la
página. Cualquier hallazgo lleva la factura a FRENAR en el cerebro.

También detecta trazos (imágenes) pintados encima del texto, como los rayones que
el jurado dibuja sobre el total: esa lectura no es confiable y la factura escala.
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


# ---------- trazos encima del texto ----------

UMBRAL_ALFA = 64                  # píxel del trazo que cuenta como tinta
FRACCION_CUBIERTA = 0.05          # 5 % de la caja del texto tapada = lectura no confiable
_TIPOS_TEXTO = ("fill-text", "stroke-text")


def _clave(rect: pymupdf.Rect) -> tuple[int, int, int, int]:
    return (round(rect.x0), round(rect.y0), round(rect.x1), round(rect.y1))


def _fraccion_tapada(alfa: pymupdf.Pixmap | None, imagen: pymupdf.Rect, texto: pymupdf.Rect) -> float:
    """Fracción de la caja del texto cubierta por píxeles opacos de la imagen."""
    if alfa is None:                       # imagen sin transparencia: tapa todo lo que cubre
        return 1.0
    escala_x, escala_y = alfa.width / imagen.width, alfa.height / imagen.height
    x0 = max(0, int((texto.x0 - imagen.x0) * escala_x))
    x1 = min(alfa.width, int((texto.x1 - imagen.x0) * escala_x) + 1)
    y0 = max(0, int((texto.y0 - imagen.y0) * escala_y))
    y1 = min(alfa.height, int((texto.y1 - imagen.y0) * escala_y) + 1)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    muestras, paso = alfa.samples, alfa.stride
    tinta = sum(
        1
        for y in range(y0, y1)
        for valor in muestras[y * paso + x0 * alfa.n: y * paso + x1 * alfa.n: alfa.n]
        if valor > UMBRAL_ALFA
    )
    return tinta / ((x1 - x0) * (y1 - y0))


def trazos_sobre_texto(datos: bytes) -> list[str]:
    """Textos tapados por una imagen pintada después de ellos. Lanza ValueError si no es un PDF.

    Una imagen pintada antes del texto (un escaneo con su capa OCR) no cuenta.
    """
    try:
        doc = pymupdf.open(stream=datos, filetype="pdf")
    except Exception as error:
        raise ValueError(f"No se pudo abrir el PDF: {error}") from error

    tapados: list[str] = []
    with doc:
        for pagina in doc:
            imagenes: dict[tuple[int, int, int, int], int] = {}
            for info in pagina.get_images(full=True):
                xref, smask = info[0], info[1]
                for rect in pagina.get_image_rects(xref):
                    imagenes[_clave(rect)] = smask
            # El bboxlog da el orden de pintado, pero sus cajas de texto pueden abarcar varias
            # líneas (WeasyPrint pinta por lotes): la cobertura se mide span por span.
            spans = [
                (pymupdf.Rect(s["bbox"]), s["text"])
                for b in pagina.get_text("dict", flags=FLAGS)["blocks"]
                for linea in b.get("lines", [])
                for s in linea["spans"]
                if s["text"].strip()
            ]
            textos_previos: list[pymupdf.Rect] = []
            for tipo, caja in pagina.get_bboxlog():
                rect = pymupdf.Rect(caja)
                if tipo in _TIPOS_TEXTO:
                    textos_previos.append(rect)
                    continue
                if tipo != "fill-image" or not textos_previos:
                    continue
                debajo = [
                    (caja_span, texto) for caja_span, texto in spans
                    if caja_span.intersects(rect)
                    and any((caja_span & previa).get_area() > 0.5 * caja_span.get_area() for previa in textos_previos)
                ]
                if not debajo:
                    continue
                smask = imagenes.get(_clave(rect), 0)
                alfa = pymupdf.Pixmap(doc, smask) if smask else None
                for caja_span, texto in debajo:
                    if _fraccion_tapada(alfa, rect, caja_span) >= FRACCION_CUBIERTA:
                        fragmento = " ".join(texto.split())
                        if fragmento not in tapados:
                            tapados.append(fragmento)
    return tapados
