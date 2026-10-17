"""Dev 1 · extracción: convierte cualquier factura en una FacturaCanonica confiable.

    from extraccion import extraer
    factura = extraer(Path("datos/facturas/01_limpia.pdf"), "web")

`extraer` nunca lanza. Ante cualquier error, timeout, desacuerdo entre A y B,
aritmética rota o imagen borrosa devuelve extraccion_ok=False con el motivo en
`diferencias`, y el cerebro escala (fail-closed).
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as TiempoAgotado
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from extraccion.cache import CacheExtracciones, con_cache
from extraccion.comparador import comparar
from extraccion.ensamblar import CANALES, construir_factura, factura_vacia
from extraccion.escaner import textos_ocultos
from extraccion.ingesta import Documento, IngestaError, ingerir, sha256_archivo
from extraccion.modelo import CamposExtraidos, Extractor
from extraccion.validador import validar
from schemas import FacturaCanonica

__all__ = ["extraer", "extractores_por_defecto", "timeout_configurado"]

log = logging.getLogger(__name__)
# Gemini tardó 17-28 s en leer facturas correctamente en la prueba real del 2026-10-17.
TIMEOUT_POR_DEFECTO_S = 45.0
MARGEN_S = 5.0          # cada extractor corta antes que el orquestador
_MAX_ERROR = 200


def timeout_configurado() -> float:
    """Timeout total de la extracción: EXTRACCION_TIMEOUT_S o 45 s si falta o es inválido."""
    try:
        valor = float(os.environ.get("EXTRACCION_TIMEOUT_S", TIMEOUT_POR_DEFECTO_S))
    except ValueError:
        return TIMEOUT_POR_DEFECTO_S
    return valor if valor > 0 else TIMEOUT_POR_DEFECTO_S


@dataclass(frozen=True, slots=True)
class Resultado:
    nombre: str
    campos: CamposExtraidos | None
    error: str | None
    latencia_ms: int


class _NoDisponible:
    """Extractor sin clave configurada: falla siempre, y por tanto la factura escala."""

    def __init__(self, nombre: str, motivo: str) -> None:
        self.nombre = nombre
        self._motivo = motivo

    def __call__(self, doc: Documento) -> CamposExtraidos:
        raise RuntimeError(self._motivo)


def extractores_por_defecto(*, cargar_env: bool = True) -> tuple[Extractor, Extractor]:
    """A = Gemini; B = Claude Haiku 5.5, o relectura con Gemini si no hay clave de Anthropic."""
    if cargar_env:
        load_dotenv()
    from extraccion.extractor_a import ExtractorGemini
    from extraccion.extractor_b import ExtractorClaude
    from extraccion.modelo import PROMPT

    limite = max(1.0, timeout_configurado() - MARGEN_S)
    hay_gemini = bool(os.environ.get("GEMINI_API_KEY"))
    a: Extractor = (ExtractorGemini(timeout_s=limite) if hay_gemini
                    else _NoDisponible("A", "falta GEMINI_API_KEY"))
    if os.environ.get("ANTHROPIC_API_KEY"):
        b: Extractor = ExtractorClaude(timeout_s=limite)
    elif hay_gemini:
        # Recorte previsto en el plan: se pierde descorrelación, se mantiene la comparación.
        relectura = PROMPT + " Revisa dos veces cada cifra antes de responder."
        b = ExtractorGemini(prompt=relectura, etiqueta="B-relectura", timeout_s=limite)
    else:
        b = _NoDisponible("B", "falta ANTHROPIC_API_KEY")
    return a, b


def _ejecutar(extractores: list[Extractor], doc: Documento, timeout_s: float) -> list[Resultado]:
    inicio = time.monotonic()
    piscina = ThreadPoolExecutor(max_workers=len(extractores), thread_name_prefix="extractor")
    futuros = [(e, piscina.submit(e, doc)) for e in extractores]
    resultados = []
    try:
        for extractor, futuro in futuros:
            restante = max(0.0, timeout_s - (time.monotonic() - inicio))
            try:
                campos, error = futuro.result(timeout=restante), None
            except TiempoAgotado:
                campos, error = None, f"no respondió a tiempo ({timeout_s:g} s)"
            except Exception as falla:  # cualquier error del modelo o del SDK escala
                campos, error = None, f"{type(falla).__name__}: {falla}"[:_MAX_ERROR]
            latencia = int((time.monotonic() - inicio) * 1000)
            resultados.append(Resultado(extractor.nombre, campos, error, latencia))
            log.info("extractor=%s ok=%s latencia_ms=%d", extractor.nombre, error is None, latencia)
    finally:
        # No esperamos a un extractor colgado: su hilo termina solo y se ignora.
        piscina.shutdown(wait=False, cancel_futures=True)
    return resultados


def _sin_repetidos(mensajes: list[str]) -> list[str]:
    return list(dict.fromkeys(mensajes))


def _extraer(ruta: Path, canal: str, a: Extractor, b: Extractor, timeout_s: float,
             cache: CacheExtracciones | None) -> FacturaCanonica:
    diferencias: list[str] = []
    if canal not in CANALES:
        diferencias.append(f"Canal desconocido '{canal}'; se esperaba uno de {sorted(CANALES)}")
        canal = "web"

    try:
        doc = ingerir(ruta)
    except IngestaError as error:
        try:
            id_documento = sha256_archivo(Path(ruta))
        except OSError:
            id_documento = ""
        return factura_vacia(id_documento, Path(ruta).as_posix(), canal,
                             diferencias + [f"No se pudo leer el archivo: {error}"])

    ocultos: list[str] = []
    if doc.pdf is not None:
        try:
            ocultos = textos_ocultos(doc.pdf)
        except ValueError as error:
            diferencias.append(f"No se pudo escanear el PDF en busca de texto oculto: {error}")

    if cache is not None:
        a, b = con_cache(a, cache), con_cache(b, cache)
    res_a, res_b = _ejecutar([a, b], doc, timeout_s)
    if res_a.error:
        diferencias.append(f"Extractor A falló: {res_a.error}")
    if res_b.error:
        diferencias.append(f"No se pudo verificar con el extractor B: {res_b.error}")

    base = res_a.campos or res_b.campos
    if base is None:
        return factura_vacia(doc.id_documento, doc.archivo, canal, _sin_repetidos(diferencias),
                             doc.texto_libre, ocultos)
    if res_a.campos and res_b.campos:
        diferencias += comparar(res_a.campos, res_b.campos)

    factura, problemas = construir_factura(doc, base, canal)
    diferencias += problemas + validar(factura) + list(doc.avisos)
    diferencias = _sin_repetidos(diferencias)
    return factura.model_copy(update={
        "texto_oculto": ocultos,
        "extraccion_ok": not diferencias,
        "diferencias": diferencias,
    })


def extraer(
    ruta: Path,
    canal: str,
    *,
    extractor_a: Extractor | None = None,
    extractor_b: Extractor | None = None,
    timeout_s: float | None = None,
    cache: CacheExtracciones | None = None,
) -> FacturaCanonica:
    """Lee una factura y devuelve su FacturaCanonica. Nunca lanza."""
    try:
        if extractor_a is None or extractor_b is None:
            por_defecto_a, por_defecto_b = extractores_por_defecto()
            extractor_a = extractor_a or por_defecto_a
            extractor_b = extractor_b or por_defecto_b
        if timeout_s is None:
            timeout_s = timeout_configurado()
        if cache is None and os.environ.get("DEMO_CACHE") == "1":
            cache = CacheExtracciones(Path("cache"))
        return _extraer(Path(ruta), canal, extractor_a, extractor_b, timeout_s, cache)
    except Exception as error:  # última red: el contrato es no lanzar nunca
        log.exception("Error inesperado extrayendo %s", ruta)
        return factura_vacia("", Path(ruta).as_posix(), canal,
                             [f"Error técnico en la extracción: {type(error).__name__}"])
