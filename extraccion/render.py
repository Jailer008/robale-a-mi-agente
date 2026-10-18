"""Modo en vivo: facturas base que el jurado puede falsificar desde el celular.

El agente lee el documento, no el formulario: lo que el jurado edita se vuelve a
dibujar como PDF y ese PDF entra al pipeline normal (escáner → extractores → validador).

    from extraccion.render import render_factura, preview_png
    pdf = render_factura("base_01", {"cuenta": "ATACANTE-7781"}, rayones_png, "A7", Path("intentos/x.pdf"))

Decisión sobre el monto (opción simple del plan): si el jurado cambia el total, las líneas
y el subtotal se quedan como estaban. El validador ve que no suman y la factura escala;
desde el formulario no se puede "hacer bien" un monto falso.
"""

from __future__ import annotations

import io
import math
import re
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import pymupdf
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from PIL import Image, ImageDraw, UnidentifiedImageError
from pydantic import BaseModel
from weasyprint import HTML

from schemas import DecisionTipo, Linea

RAIZ = Path(__file__).resolve().parent.parent
BASES = RAIZ / "datos" / "base"
PLANTILLAS = RAIZ / "datos" / "plantillas"

MAX_MONTO = 1_000_000_000
MAX_TEXTO = 40
MAX_NOTA = 200
MAX_RAYONES_BYTES = 2 * 1024 * 1024
DPI_PREVIEW = 120
CAMBIOS_PERMITIDOS = frozenset({"monto", "cuenta", "proveedor", "numero", "nota", "nota_oculta"})
_ID_BASE = re.compile(r"^base_\d{2}$")
_SUFIJO = re.compile(r"^[A-Za-z0-9]{1,8}$")
_TEXTO_PERMITIDO = re.compile(r"^[A-Za-z0-9 .\-_/áéíóúñÁÉÍÓÚÑ]+$")


class CambiosInvalidos(ValueError):
    """Lo que envió el celular no pasa la validación; no se dibuja nada."""


class FacturaBase(BaseModel):
    base_id: str
    proveedor: str
    id_fiscal: str
    pais: str
    numero: str
    fecha_emision: date
    fecha_vencimiento: date
    moneda: str
    lineas: list[Linea]
    subtotal: float
    impuestos: float = 0.0
    total: float
    cuenta: str
    referencia_contrato: str
    nota_visible: str = ""
    nota_oculta: str = ""
    esperado_tal_cual: DecisionTipo
    pista: str = ""


def listar_bases() -> list[str]:
    return sorted(p.stem for p in BASES.glob("base_*.json") if _ID_BASE.match(p.stem))


def cargar_base(base_id: str) -> FacturaBase:
    """Lanza ValueError si el id no es del pool (evita rutas arbitrarias)."""
    if not isinstance(base_id, str) or not _ID_BASE.match(base_id) or base_id not in listar_bases():
        raise ValueError(f"Factura base desconocida: {base_id!r}")
    return FacturaBase.model_validate_json((BASES / f"{base_id}.json").read_text(encoding="utf-8"))


# ---------- validación de lo que llega del celular ----------

def _monto(valor: Any) -> float:
    if isinstance(valor, bool) or not isinstance(valor, int | float | str):
        raise CambiosInvalidos("El monto debe ser un número")
    try:
        numero = float(valor)
    except ValueError as error:
        raise CambiosInvalidos("El monto debe ser un número") from error
    if not math.isfinite(numero) or not 0 <= numero <= MAX_MONTO:
        raise CambiosInvalidos(f"El monto debe estar entre 0 y {MAX_MONTO:,}")
    return round(numero, 2)


def _texto_corto(campo: str, valor: Any) -> str:
    if (not isinstance(valor, str) or len(valor) > MAX_TEXTO
            or not _TEXTO_PERMITIDO.fullmatch(valor) or not valor.strip()):
        raise CambiosInvalidos(f"'{campo}' admite hasta {MAX_TEXTO} letras, números, espacios y . - _ /")
    return valor.strip()


def _nota(valor: Any) -> str:
    if not isinstance(valor, str):
        raise CambiosInvalidos("La nota debe ser texto")
    limpia = " ".join(valor.split())
    if len(limpia) > MAX_NOTA or not limpia.isprintable():
        raise CambiosInvalidos(f"La nota admite hasta {MAX_NOTA} caracteres imprimibles")
    return limpia


def validar_cambios(cambios: Any) -> dict[str, Any]:
    if not isinstance(cambios, dict):
        raise CambiosInvalidos("Los cambios deben ser un objeto")
    desconocidos = set(cambios) - CAMBIOS_PERMITIDOS
    if desconocidos:
        raise CambiosInvalidos(f"Campos no permitidos: {', '.join(sorted(map(str, desconocidos)))}")
    limpios: dict[str, Any] = {}
    if "monto" in cambios:
        limpios["monto"] = _monto(cambios["monto"])
    for campo in ("cuenta", "proveedor", "numero"):
        if campo in cambios:
            limpios[campo] = _texto_corto(campo, cambios[campo])
    if "nota" in cambios:
        limpios["nota"] = _nota(cambios["nota"])
    if "nota_oculta" in cambios:
        if not isinstance(cambios["nota_oculta"], bool):
            raise CambiosInvalidos("nota_oculta debe ser verdadero o falso")
        limpios["nota_oculta"] = cambios["nota_oculta"]
    return limpios


def _validar_sufijo(sufijo: Any) -> str:
    if not isinstance(sufijo, str) or not _SUFIJO.fullmatch(sufijo):
        raise CambiosInvalidos("El sufijo del número debe tener de 1 a 8 letras o dígitos")
    return sufijo


def _validar_rayones(datos: Any) -> bytes:
    if not isinstance(datos, bytes) or len(datos) > MAX_RAYONES_BYTES:
        raise CambiosInvalidos(f"Los rayones deben ser un PNG de hasta {MAX_RAYONES_BYTES // 1048576} MB")
    try:
        with Image.open(io.BytesIO(datos)) as imagen:
            formato = imagen.format
            imagen.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise CambiosInvalidos("Los rayones no son una imagen válida") from error
    if formato != "PNG":
        raise CambiosInvalidos("Los rayones deben ser PNG")
    return datos


# ---------- aplicar y dibujar ----------

def aplicar_cambios(base: FacturaBase, cambios: dict[str, Any], sufijo_numero: str) -> FacturaBase:
    """Devuelve la factura tal como quedará dibujada (no modifica la base)."""
    limpios = validar_cambios(cambios)
    sufijo = _validar_sufijo(sufijo_numero)
    datos = base.model_dump()

    if "monto" in limpios:
        datos["total"] = limpios["monto"]           # líneas y subtotal intactos: ver docstring
    for campo in ("cuenta", "proveedor"):
        if campo in limpios:
            datos[campo] = limpios[campo]
    if "numero" in limpios and limpios["numero"] != base.numero:
        datos["numero"] = limpios["numero"]         # p. ej. FV-0192: duplicado a propósito
    else:
        datos["numero"] = f"{base.numero}-{sufijo}"  # evita duplicados falsos entre jurados
    if limpios.get("nota"):
        destino = "nota_oculta" if limpios.get("nota_oculta") else "nota_visible"
        datos[destino] = limpios["nota"]
    return FacturaBase.model_validate(datos)


def _monto_fmt(valor: float) -> str:
    return f"{valor:,.2f}"


def _cantidad_fmt(valor: float) -> str:
    return f"{int(valor):,}" if float(valor).is_integer() else f"{valor:,.2f}"


_ENTORNO = Environment(loader=FileSystemLoader(PLANTILLAS), autoescape=True, undefined=StrictUndefined)
_ENTORNO.filters["monto"] = _monto_fmt
_ENTORNO.filters["cantidad"] = _cantidad_fmt


def html_factura(f: FacturaBase) -> str:
    return _ENTORNO.get_template("factura.html").render(**f.model_dump())


def _pdf(f: FacturaBase, rayones: bytes | None) -> bytes:
    datos = HTML(string=html_factura(f), base_url=str(PLANTILLAS)).write_pdf()
    if not rayones:
        return datos
    with pymupdf.open(stream=datos, filetype="pdf") as doc:
        pagina = doc[0]
        pagina.insert_image(pagina.rect, stream=rayones, overlay=True)
        return doc.tobytes(deflate=True)


def render_factura(
    base_id: str,
    cambios: dict[str, Any],
    rayones_png: bytes | None,
    sufijo_numero: str,
    salida: Path,
) -> Path:
    """Dibuja la factura falsificada y devuelve la ruta del PDF.

    `salida` puede ser la ruta de un .pdf o un directorio, exista o no (se usa `{base_id}-{sufijo}.pdf`).
    Lanza ValueError si la base no existe y CambiosInvalidos si la entrada no es válida.
    """
    base = cargar_base(base_id)
    aplicada = aplicar_cambios(base, cambios, sufijo_numero)
    rayones = _validar_rayones(rayones_png) if rayones_png is not None else None

    salida = Path(salida)
    # Sin extensión .pdf es un directorio, aunque todavía no exista.
    destino = salida if salida.suffix.lower() == ".pdf" else salida / f"{base_id}-{sufijo_numero}.pdf"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(_pdf(aplicada, rayones))
    return destino


@lru_cache(maxsize=16)
def preview_png(base_id: str) -> bytes:
    """Imagen de la base tal cual a 120 dpi: lo que el celular muestra al cargar."""
    with pymupdf.open(stream=_pdf(cargar_base(base_id), None), filetype="pdf") as doc:
        return doc[0].get_pixmap(dpi=DPI_PREVIEW).tobytes("png")


# ---------- rayones dibujados por el servidor ----------

OBJETIVOS_RAYON = ("total", "cuenta", "numero")


def rayones_sobre(f: FacturaBase, objetivos: list[str]) -> bytes:
    """PNG transparente (tamaño del preview) con un garabato grueso sobre lo que el jurado eligió rayar.

    Sustituye al lienzo a mano alzada: Streamlit no tiene uno estable. El resultado es un rayón como
    cualquier otro: se superpone al PDF y lo detecta el escáner.
    """
    if (not isinstance(objetivos, list) or not 1 <= len(objetivos) <= len(OBJETIVOS_RAYON)
            or not set(objetivos) <= set(OBJETIVOS_RAYON) or len(set(objetivos)) != len(objetivos)):
        raise CambiosInvalidos(f"Se puede rayar: {', '.join(OBJETIVOS_RAYON)} (cada uno una vez)")
    buscados = {"total": f"TOTAL {f.moneda} {_monto_fmt(f.total)}", "cuenta": f.cuenta, "numero": f.numero}
    escala = DPI_PREVIEW / 72
    with pymupdf.open(stream=_pdf(f, None), filetype="pdf") as doc:
        pagina = doc[0]
        lienzo = Image.new("RGBA", (round(pagina.rect.width * escala), round(pagina.rect.height * escala)),
                           (0, 0, 0, 0))
        dibujo = ImageDraw.Draw(lienzo)
        for objetivo in objetivos:
            for r in pagina.search_for(buscados[objetivo])[:1]:
                x0, y0, x1, y1 = (r.x0 - 4) * escala, (r.y0 - 3) * escala, (r.x1 + 4) * escala, (r.y1 + 3) * escala
                pasos = 6
                puntos = [(x0 + (x1 - x0) * i / pasos, y0 if i % 2 else y1) for i in range(pasos + 1)]
                dibujo.line(puntos, fill=(205, 20, 20, 255), width=max(6, round(4 * escala)), joint="curve")
                dibujo.line([(x0, (y0 + y1) / 2), (x1, (y0 + y1) / 2)], fill=(205, 20, 20, 255),
                            width=max(6, round(5 * escala)))
    salida = io.BytesIO()
    lienzo.save(salida, "PNG")
    return salida.getvalue()
