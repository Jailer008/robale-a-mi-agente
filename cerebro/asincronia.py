"""Puente sync ↔ async: la API pública es síncrona pero funciona también dentro de un event loop."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import Any

# Piscina propia para agentes síncronos: asyncio.run() no espera a sus hilos al terminar,
# así un agente colgado no retiene la respuesta una vez vencido su timeout.
PISCINA_AGENTES = ThreadPoolExecutor(max_workers=16, thread_name_prefix="agente")


def correr_sync[T](coro: Coroutine[Any, Any, T]) -> T:
    """Ejecuta la corrutina. Si ya hay un loop corriendo (FastAPI, Streamlit), usa otro hilo."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="cerebro-sync") as hilo:
        return hilo.submit(asyncio.run, coro).result()
