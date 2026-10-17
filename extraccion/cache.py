"""Caché de demo (DEMO_CACHE=1): respuestas de los extractores por SHA-256 del original.

Patrón content-hash de ECC: la clave es el contenido, no la ruta; una entrada
corrupta es un fallo de caché, nunca un error. Los fallos del modelo no se guardan.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from pydantic import ValidationError

from extraccion.ingesta import Documento
from extraccion.modelo import CamposExtraidos, Extractor

log = logging.getLogger(__name__)


class CacheExtracciones:
    def __init__(self, directorio: Path) -> None:
        self.directorio = Path(directorio)

    def _ruta(self, id_documento: str, extractor: str) -> Path:
        seguro = re.sub(r"[^A-Za-z0-9_.-]", "_", extractor).strip(".")
        return self.directorio / f"{id_documento}__{seguro}.json"

    def leer(self, id_documento: str, extractor: str) -> CamposExtraidos | None:
        ruta = self._ruta(id_documento, extractor)
        if not ruta.is_file():
            return None
        try:
            return CamposExtraidos.model_validate_json(ruta.read_text(encoding="utf-8"))
        except (ValidationError, OSError, ValueError):
            log.warning("Entrada de caché corrupta: %s", ruta.name)
            return None

    def escribir(self, id_documento: str, extractor: str, campos: CamposExtraidos) -> None:
        self.directorio.mkdir(parents=True, exist_ok=True)
        self._ruta(id_documento, extractor).write_text(campos.model_dump_json(indent=2), encoding="utf-8")


class _ConCache:
    def __init__(self, extractor: Extractor, cache: CacheExtracciones) -> None:
        self._extractor = extractor
        self._cache = cache
        self.nombre = extractor.nombre

    def __call__(self, doc: Documento) -> CamposExtraidos:
        guardado = self._cache.leer(doc.id_documento, self.nombre)
        if guardado is not None:
            log.info("Caché: %s para %s", self.nombre, doc.id_documento[:12])
            return guardado
        campos = self._extractor(doc)
        self._cache.escribir(doc.id_documento, self.nombre, campos)
        return campos


def con_cache(extractor: Extractor, cache: CacheExtracciones) -> Extractor:
    return _ConCache(extractor, cache)
