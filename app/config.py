"""Configuración de la API desde el entorno. Nunca se registran ni se devuelven tokens.

Variables (además de las del cerebro: DB_PATH, CEREBRO_APROBADORES, CEREBRO_ADMINS, SIGNING_KEY_PATH…):
  APP_APROBADOR_TOKENS   "identidad=token,identidad2=token2"  (la identidad debe estar en CEREBRO_APROBADORES)
  APP_ADMIN_TOKENS       "identidad=token"                     (la identidad debe estar en CEREBRO_ADMINS)
  APP_CORS_ORIGINS       orígenes permitidos, separados por coma (por defecto, la UI local en :8501)
  APP_MAX_UPLOAD_MB      tamaño máximo de archivo (por defecto 10; tope 20, como la ingesta de Dev 1)
  APP_ENTRADA_DIR        carpeta de archivos subidos (por defecto "entrada", ignorada por git)
  ATTACK_LAB_EXTRACCION_LIVE=1   autoriza extractores LIVE (cuesta dinero). Por defecto: solo caché.
  APP_CONFIAR_EN_PROXY=1         usar X-Forwarded-For para el límite por IP (solo detrás de un proxy propio)
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)
_MIN_TOKEN = 24
_TOPE_UPLOAD_MB = 20


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _tokens(variable: str, rol: str) -> dict[str, tuple[str, str]]:
    """{sha256(token): (identidad, rol)}. Tokens cortos se ignoran (sin registrar su valor)."""
    salida: dict[str, tuple[str, str]] = {}
    for par in (os.environ.get(variable) or "").split(","):
        identidad, _, token = par.strip().partition("=")
        identidad, token = identidad.strip(), token.strip()
        if not identidad or not token:
            continue
        if len(token) < _MIN_TOKEN:
            log.warning("%s: token de '%s' demasiado corto (mínimo %d caracteres); se ignora", variable,
                        identidad, _MIN_TOKEN)
            continue
        salida[_hash(token)] = (identidad, rol)
    return salida


@dataclass(frozen=True)
class Ajustes:
    max_upload_bytes: int = 10 * 1024 * 1024
    origenes_cors: tuple[str, ...] = ("http://localhost:8501", "http://127.0.0.1:8501")
    extraccion_live: bool = False
    entrada: Path = Path("entrada")
    confiar_en_proxy: bool = False
    tokens: dict[str, tuple[str, str]] = field(default_factory=dict)
    # Cuotas (ventana deslizante en memoria del único proceso API)
    simular_por_minuto_ip: int = 20
    simular_por_hora_sesion: int = 60
    ingest_por_minuto_ip: int = 5
    lectura_por_minuto_ip: int = 120
    politica_por_minuto_ip: int = 20
    paquete_por_minuto: int = 2
    # Modo «factura falsificada»: cada intento cuesta una extracción LIVE (dinero y ~5 s)
    falsificar_por_minuto_ip: int = 6
    falsificar_por_hora_sesion: int = 10
    falsificar_por_minuto_global: int = 30


def desde_entorno() -> Ajustes:
    try:
        mb = int(os.environ.get("APP_MAX_UPLOAD_MB") or 10)
    except ValueError:
        mb = 10
    mb = max(1, min(mb, _TOPE_UPLOAD_MB))
    origenes = tuple(o.strip() for o in (os.environ.get("APP_CORS_ORIGINS") or
                                         "http://localhost:8501,http://127.0.0.1:8501").split(",") if o.strip())
    return Ajustes(
        max_upload_bytes=mb * 1024 * 1024,
        origenes_cors=origenes,
        extraccion_live=os.environ.get("ATTACK_LAB_EXTRACCION_LIVE") == "1",
        entrada=Path(os.environ.get("APP_ENTRADA_DIR") or "entrada"),
        confiar_en_proxy=os.environ.get("APP_CONFIAR_EN_PROXY") == "1",
        tokens={**_tokens("APP_APROBADOR_TOKENS", "aprobador"), **_tokens("APP_ADMIN_TOKENS", "admin")},
    )
