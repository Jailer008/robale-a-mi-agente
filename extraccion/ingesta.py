"""Ingesta: del archivo original a un Documento listo para extractores y escáner.

El original no se modifica; su SHA-256 es el id_documento (evidencia cero).
"""

from __future__ import annotations

import email
import hashlib
import io
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.policy import default as politica_email
from pathlib import Path
from typing import Literal

import pymupdf
from PIL import Image, ImageFilter, ImageStat, UnidentifiedImageError

TipoDocumento = Literal["pdf", "imagen", "texto"]

DPI = 170
MAX_PAGINAS = 5
MAX_LADO_PX = 2400                # tope de la imagen enviada al modelo: evita agotar memoria
MAX_BYTES = 20 * 1024 * 1024      # igual que el límite de archivos de un bot de Telegram
_BLOQUE_HASH = 65536
MIME_IMAGEN = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
# Varianza de bordes por debajo de este umbral = foto borrosa.
# Calibrado con el set: 02_limpia.png = 1372, 15_borrosa.jpg = 368.
UMBRAL_NITIDEZ = 600.0


class IngestaError(Exception):
    """El archivo no se puede leer como factura."""


@dataclass(frozen=True, slots=True)
class Documento:
    id_documento: str
    archivo: str
    tipo: TipoDocumento
    imagenes: tuple[bytes, ...] = ()
    mime_imagen: str = "image/png"
    texto: str = ""
    texto_libre: str = ""
    pdf: bytes | None = None
    avisos: tuple[str, ...] = field(default_factory=tuple)


def sha256_archivo(ruta: Path) -> str:
    sha = hashlib.sha256()
    with ruta.open("rb") as archivo:
        while bloque := archivo.read(_BLOQUE_HASH):
            sha.update(bloque)
    return sha.hexdigest()


def _ruta_relativa(ruta: Path) -> str:
    try:
        return ruta.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return ruta.as_posix()


def nitidez(datos_imagen: bytes) -> float:
    """Varianza del mapa de bordes en escala de grises: baja = borrosa."""
    with Image.open(io.BytesIO(datos_imagen)) as imagen:
        gris = imagen.convert("L")
        if max(gris.size) > 1200:
            gris.thumbnail((1200, 1200))
        return ImageStat.Stat(gris.filter(ImageFilter.FIND_EDGES)).var[0]


def _dpi_seguro(pagina: pymupdf.Page) -> int:
    """Baja los dpi si la página es tan grande que la imagen pasaría de MAX_LADO_PX."""
    lado_pt = max(pagina.rect.width, pagina.rect.height, 1)
    return max(1, min(DPI, int(MAX_LADO_PX * 72 / lado_pt)))


def _desde_pdf(datos: bytes) -> dict:
    try:
        doc = pymupdf.open(stream=datos, filetype="pdf")
    except Exception as error:
        raise IngestaError(f"PDF ilegible: {error}") from error
    with doc:
        if doc.page_count == 0:
            raise IngestaError("El PDF no tiene páginas")
        paginas = list(doc)[:MAX_PAGINAS]
        imagenes = tuple(p.get_pixmap(dpi=_dpi_seguro(p)).tobytes("png") for p in paginas)
        texto = "\n".join(p.get_text() for p in paginas).strip()
    return {"tipo": "pdf", "imagenes": imagenes, "mime_imagen": "image/png", "texto": texto, "pdf": datos}


def _desde_imagen(datos: bytes, mime: str) -> dict:
    try:
        with Image.open(io.BytesIO(datos)) as imagen:
            imagen.verify()
        valor = nitidez(datos)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise IngestaError(f"Imagen ilegible: {error}") from error
    avisos = ()
    if valor < UMBRAL_NITIDEZ:
        avisos = (
            f"La imagen está borrosa (nitidez {valor:.0f} < {UMBRAL_NITIDEZ:.0f}): "
            "la extracción no es confiable.",
        )
    return {"tipo": "imagen", "imagenes": (datos,), "mime_imagen": mime, "avisos": avisos}


def _desde_eml(datos: bytes) -> dict:
    mensaje = email.message_from_bytes(datos, policy=politica_email)
    if not isinstance(mensaje, EmailMessage):
        raise IngestaError("Correo ilegible")
    cuerpo = mensaje.get_body(preferencelist=("plain", "html"))
    texto_libre = cuerpo.get_content().replace("\r\n", "\n").strip() if cuerpo else ""

    for adjunto in mensaje.iter_attachments():
        tipo = adjunto.get_content_type()
        contenido = adjunto.get_payload(decode=True) or b""
        if tipo == "application/pdf":
            return _desde_pdf(contenido) | {"texto_libre": texto_libre}
        if tipo in ("image/png", "image/jpeg"):
            return _desde_imagen(contenido, tipo) | {"texto_libre": texto_libre}

    if not texto_libre:
        raise IngestaError("El correo no tiene adjunto ni cuerpo de texto")
    return {"tipo": "texto", "texto": texto_libre, "texto_libre": texto_libre}


def ingerir(ruta: Path) -> Documento:
    """Lee el original y lo normaliza. Lanza IngestaError si no es una factura legible."""
    ruta = Path(ruta)
    if not ruta.is_file():
        raise IngestaError(f"No existe el archivo {ruta}")
    tamano = ruta.stat().st_size
    if tamano > MAX_BYTES:
        raise IngestaError(
            f"El archivo es demasiado grande ({tamano / 1048576:.1f} MB; máximo {MAX_BYTES / 1048576:.0f} MB)"
        )
    datos = ruta.read_bytes()
    extension = ruta.suffix.lower()

    if extension == ".pdf":
        partes = _desde_pdf(datos)
    elif extension in MIME_IMAGEN:
        partes = _desde_imagen(datos, MIME_IMAGEN[extension])
    elif extension == ".eml":
        partes = _desde_eml(datos)
    elif extension == ".txt":
        try:
            texto = datos.decode("utf-8").strip()
        except UnicodeDecodeError as error:
            raise IngestaError("El texto no está en UTF-8") from error
        partes = {"tipo": "texto", "texto": texto, "texto_libre": texto}
    else:
        raise IngestaError(f"Formato no soportado: {extension or 'sin extensión'}")

    return Documento(
        id_documento=hashlib.sha256(datos).hexdigest(),
        archivo=_ruta_relativa(ruta),
        **partes,
    )
