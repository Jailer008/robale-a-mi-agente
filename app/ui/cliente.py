"""Cliente HTTP de la API del Attack Lab. La UI nunca abre la base ni importa el cerebro.

API_URL (por defecto http://127.0.0.1:8000). El token de operador vive solo en la sesión del servidor
de Streamlit y se envía como Bearer; nunca se imprime ni se guarda en el navegador.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import httpx

API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000").rstrip("/")
TRANSPORTE: httpx.BaseTransport | None = None        # los tests inyectan un httpx.MockTransport


class ErrorApi(Exception):
    def __init__(self, status: int, cuerpo: dict[str, Any]) -> None:
        super().__init__(cuerpo.get("mensaje") or f"Error {status}")
        self.status = status
        self.cuerpo = cuerpo


def _cliente() -> httpx.Client:
    return httpx.Client(base_url=API_URL, timeout=60.0, transport=TRANSPORTE)


def _cabeceras(token: str | None, idempotencia: str | None = None) -> dict[str, str]:
    cabeceras = {"Authorization": f"Bearer {token}"} if token else {}
    if idempotencia:
        cabeceras["Idempotency-Key"] = idempotencia
    return cabeceras


def _respuesta(r: httpx.Response) -> Any:
    try:
        cuerpo = r.json()
    except ValueError:
        cuerpo = {"mensaje": "Respuesta no válida de la API."}
    if r.status_code >= 400:
        raise ErrorApi(r.status_code, cuerpo if isinstance(cuerpo, dict) else {})
    return cuerpo


def get(ruta: str, token: str | None = None, **params: Any) -> Any:
    with _cliente() as c:
        return _respuesta(c.get(ruta, params=params or None, headers=_cabeceras(token)))


def post(ruta: str, token: str | None = None, json: Any = None, idempotencia: str | None = None) -> Any:
    with _cliente() as c:
        return _respuesta(c.post(ruta, json=json, headers=_cabeceras(token, idempotencia)))


def imagen(ruta: str) -> bytes:
    """PNG servido por la API (vista previa de una factura base)."""
    with _cliente() as c:
        r = c.get(ruta)
    if r.status_code >= 400 or r.headers.get("content-type", "").split(";")[0] != "image/png":
        raise ErrorApi(r.status_code, {"mensaje": "No se pudo cargar la vista previa."})
    return r.content


def subir(nombre: str, contenido: bytes, canal: str) -> Any:
    with _cliente() as c:
        return _respuesta(c.post("/ingest", files={"archivo": (nombre, contenido)}, data={"canal": canal}))


def nueva_clave() -> str:
    return uuid.uuid4().hex
