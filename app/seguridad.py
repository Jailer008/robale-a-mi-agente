"""Autenticación de operadores (aprobadores y administradores) y límites de tasa.

- Identidad SOLO desde un token Bearer configurado en el servidor (APP_*_TOKENS); nunca desde una
  cabecera libre del cliente. Los tokens se guardan como SHA-256 y se comparan en tiempo constante.
- Tokens Bearer (no cookies): no hay CSRF que proteger en la API. La UI guarda el token en la sesión
  del servidor de Streamlit, no en el navegador.
- Límite por IP y por sesión con ventana deslizante en memoria (un solo proceso API, ver HANDOFF).
"""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Operador:
    identidad: str
    rol: Literal["aprobador", "admin"]


def autenticar(cabecera: str | None, tokens: dict[str, tuple[str, str]]) -> Operador | None:
    if not cabecera or not cabecera.startswith("Bearer "):
        return None
    token = cabecera[len("Bearer "):].strip()
    if not token or len(token) > 512:
        return None
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    encontrado = None
    for guardado, (identidad, rol) in tokens.items():      # recorre todo: sin atajos dependientes del token
        if hmac.compare_digest(guardado, digest):
            encontrado = Operador(identidad, rol)  # type: ignore[arg-type]
    return encontrado


class Limitador:
    def __init__(self) -> None:
        self._eventos: dict[str, deque[float]] = {}
        self._candado = threading.Lock()

    def permitir(self, clave: str, limite: int, ventana_s: float) -> bool:
        ahora = time.monotonic()
        with self._candado:
            cola = self._eventos.setdefault(clave, deque())
            while cola and ahora - cola[0] > ventana_s:
                cola.popleft()
            if len(cola) >= limite:
                return False
            cola.append(ahora)
            if len(self._eventos) > 10_000:                 # acota memoria ante muchas IPs distintas
                for vieja in [k for k, v in self._eventos.items() if not v][:5_000]:
                    del self._eventos[vieja]
            return True

    def reiniciar(self) -> None:
        with self._candado:
            self._eventos.clear()
