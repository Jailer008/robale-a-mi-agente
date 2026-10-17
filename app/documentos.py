"""Modo «SUBIR DOCUMENTO»: validación del archivo y extracción honesta (caché o LIVE autorizado).

- Extensiones permitidas: .pdf .png .jpg .jpeg .eml .txt; tamaño acotado; firma mágica comprobada.
- Se guarda en entrada/<sha256><ext> con nombre del SERVIDOR (el nombre del cliente nunca forma una ruta).
- Por defecto NO hay llamadas a modelos: extractores que fallan si se los llama + caché de solo lectura.
  Documento nuevo → la extracción falla → extraccion_ok=False → ESCALAR no aprobable, con etiqueta honesta.
- Con ATTACK_LAB_EXTRACCION_LIVE=1 se usan los extractores reales de Dev 1 (cuesta dinero).
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any, Literal

from cerebro.config import RAIZ
from schemas import FacturaCanonica

FIRMAS: dict[str, tuple[bytes, ...] | None] = {
    ".pdf": (b"%PDF-",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".eml": None,          # texto
    ".txt": None,
}
Fuente = Literal["CACHÉ", "LIVE", "SIN_EXTRACCION"]
ETIQUETAS_FUENTE = {
    "CACHÉ": "DOCUMENTO — EXTRACCIÓN DESDE CACHÉ (respuestas grabadas, sin llamadas a modelos)",
    "LIVE": "DOCUMENTO — EXTRACCIÓN LIVE (modelos reales)",
    "SIN_EXTRACCION": "DOCUMENTO — SIN EXTRACCIÓN: documento nuevo y la extracción LIVE no está autorizada",
}


class ArchivoInvalido(ValueError):
    def __init__(self, mensaje: str, status: int) -> None:
        super().__init__(mensaje)
        self.status = status


def nombre_visible(nombre: str | None) -> str:
    base = Path(nombre or "").name                                # descarta cualquier ruta
    return re.sub(r"[^A-Za-z0-9._-]", "_", base)[:60] or "archivo"


def validar(nombre: str | None, contenido: bytes, max_bytes: int) -> tuple[str, str]:
    """Devuelve (extensión, sha256). Lanza ArchivoInvalido con el código HTTP adecuado."""
    extension = Path(nombre or "").suffix.lower()
    if extension not in FIRMAS:
        raise ArchivoInvalido("Tipo de archivo no permitido: use PDF, PNG, JPG, EML o TXT.", 415)
    if not contenido:
        raise ArchivoInvalido("El archivo está vacío.", 400)
    if len(contenido) > max_bytes:
        raise ArchivoInvalido(f"El archivo supera el máximo de {max_bytes // (1024 * 1024)} MB.", 413)
    firmas = FIRMAS[extension]
    if firmas is not None and not contenido.startswith(firmas):
        raise ArchivoInvalido("El contenido no corresponde a la extensión del archivo.", 415)
    if firmas is None:
        if b"\x00" in contenido:
            raise ArchivoInvalido("El archivo de texto contiene bytes binarios.", 415)
        try:
            contenido.decode("utf-8")
        except UnicodeDecodeError:
            raise ArchivoInvalido("El archivo de texto debe estar en UTF-8.", 415) from None
    return extension, hashlib.sha256(contenido).hexdigest()


def guardar(contenido: bytes, extension: str, sha: str, entrada: Path) -> Path:
    entrada = Path(entrada).resolve()
    entrada.mkdir(parents=True, exist_ok=True)
    ruta = (entrada / f"{sha}{extension}").resolve()
    if ruta.parent != entrada:                                  # defensa en profundidad contra traversal
        raise ArchivoInvalido("Ruta de destino inválida.", 400)
    if not ruta.exists():
        with ruta.open("xb") as archivo:
            archivo.write(contenido)
    return ruta


class _SoloCache:
    """Extractor que nunca llama a un modelo: si la caché no tiene la respuesta, falla (fail-closed)."""

    def __init__(self, nombre: str) -> None:
        self.nombre = nombre
        self.llamadas = 0

    def __call__(self, doc: Any) -> Any:
        self.llamadas += 1
        raise RuntimeError("documento sin respuesta en caché y la extracción LIVE no está autorizada")


class _Contador:
    def __init__(self, extractor: Any) -> None:
        self._extractor = extractor
        self.nombre = extractor.nombre
        self.llamadas = 0
        self.exitos = 0

    def __call__(self, doc: Any) -> Any:
        self.llamadas += 1
        resultado = self._extractor(doc)
        self.exitos += 1
        return resultado


def extraer_documento(ruta: Path, canal: str, *, live: bool) -> tuple[FacturaCanonica, Fuente]:
    from extraccion import extractores_por_defecto, extraer
    from extraccion.cache import CacheExtracciones
    from extraccion.extractor_b import MODELO as MODELO_B
    from extraccion.extractor_openai import MODELO_POR_DEFECTO as MODELO_A

    class _CacheSoloLectura(CacheExtracciones):                 # cache/ está versionada: no se escribe
        aciertos = 0

        def leer(self, *args: Any, **kwargs: Any) -> Any:
            resultado = super().leer(*args, **kwargs)
            if resultado is not None:
                self.aciertos += 1
            return resultado

        def escribir(self, *args: Any, **kwargs: Any) -> None:
            return None

    if live:
        base_a, base_b = extractores_por_defecto(cargar_env=False)
        a, b = _Contador(base_a), _Contador(base_b)
    else:
        a = _SoloCache(f"A:{os.environ.get('OPENAI_MODEL') or MODELO_A}")
        b = _SoloCache(f"B:{MODELO_B}")
    cache = _CacheSoloLectura(RAIZ / "cache")
    factura = extraer(ruta, canal, extractor_a=a, extractor_b=b, cache=cache)
    if live and (getattr(a, "exitos", 0) or getattr(b, "exitos", 0)):   # LIVE solo si un modelo respondió
        return factura, "LIVE"
    if cache.aciertos and not (a.llamadas or b.llamadas):               # todo salió de la caché
        return factura, "CACHÉ"
    return factura, "SIN_EXTRACCION"
