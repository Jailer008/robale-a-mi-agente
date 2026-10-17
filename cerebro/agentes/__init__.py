"""Los cinco agentes. Reciben (factura, contexto) y devuelven list[Hallazgo]; NUNCA una decisión ni un pago.

Orquestación (G3): los cinco dominios corren en paralelo con asyncio. Cada dominio tiene una
parte determinista (código) y, si hay capa semántica configurada, una parte semántica que
solo puede SUMAR hallazgos. Cada parte corre con su propio timeout y su propio manejo de
errores, así un fallo semántico nunca borra un veto determinista. Un agente que lanza, tarda
o devuelve algo que no es list[Hallazgo] produce un Hallazgo de tipo fallo_tecnico (ESCALAR).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from cerebro.agentes import beneficiario, contrato, duplicados, presupuesto, seguridad
from cerebro.asincronia import PISCINA_AGENTES, correr_sync
from cerebro.contexto import Contexto
from cerebro.tipos import causa, fallo, tipo_de
from schemas import FacturaCanonica, Hallazgo

log = logging.getLogger(__name__)
Agente = Callable[[FacturaCanonica, Contexto], "list[Hallazgo] | Awaitable[list[Hallazgo]]"]
AgenteSemantico = Callable[[FacturaCanonica, Contexto, Any], Awaitable[list[Hallazgo]]]
TIMEOUT_POR_DEFECTO_S = 3.0

AGENTES: tuple[tuple[str, Agente], ...] = (
    ("duplicados", duplicados.revisar),
    ("contrato", contrato.revisar),
    ("beneficiario", beneficiario.revisar),
    ("seguridad", seguridad.revisar),
    ("presupuesto", presupuesto.revisar),
)


@dataclass(frozen=True, slots=True)
class Evento:
    """Lo que el comité en vivo de Dev 3 muestra por agente (tabla `eventos`)."""
    agente: str
    severidad: int
    probabilidad: float | None
    latencia_ms: int
    motivo: str
    tipo: str = "sin_hallazgos"        # riesgo | fallo_tecnico | sin_evidencia | sin_hallazgos


def _validar(resultado: object) -> list[Hallazgo]:
    if not isinstance(resultado, list) or not all(isinstance(h, Hallazgo) for h in resultado):
        raise TypeError(f"devolvió {type(resultado).__name__} en lugar de list[Hallazgo]")
    return resultado


async def _correr(nombre: str, llamada: Callable[[], Any], es_async: bool, timeout_s: float,
                  etiqueta: str = "") -> list[Hallazgo]:
    """Ejecuta una parte de un agente con timeout. Nunca lanza: los errores son fallo_tecnico."""
    quien = f"{nombre}{etiqueta}"
    try:
        if es_async:
            tarea: asyncio.Future[Any] = asyncio.ensure_future(llamada())
        else:
            tarea = asyncio.get_running_loop().run_in_executor(PISCINA_AGENTES, llamada)
        # asyncio.wait distingue "no terminó a tiempo" de "terminó lanzando TimeoutError por su cuenta".
        terminadas, _ = await asyncio.wait({tarea}, timeout=timeout_s)
        if not terminadas:
            tarea.cancel()
            log.warning("Agente %s sin respuesta en %.1f s", quien, timeout_s)
            return [fallo(nombre, f"El agente {quien} no respondió en {timeout_s:g} s; se escala por seguridad.",
                          f"timeout={timeout_s:g}s")]
        return _validar(tarea.result())
    except Exception as error:
        log.exception("Agente %s falló", quien)
        return [fallo(nombre, f"No se pudo verificar con el agente {quien} ({causa(error)}).", causa(error))]


async def _dominio(nombre: str, agente: Agente, factura: FacturaCanonica, ctx: Contexto, timeout_s: float,
                   semantico: AgenteSemantico | None, capa: Any) -> tuple[list[Hallazgo], Evento]:
    inicio = time.perf_counter()
    partes = [_correr(nombre, lambda: agente(factura, ctx), inspect.iscoroutinefunction(agente), timeout_s)]
    if semantico is not None and capa is not None:
        partes.append(_correr(nombre, lambda: semantico(factura, ctx, capa), True, timeout_s, " (semántica)"))
    propios = [h for parte in await asyncio.gather(*partes) for h in parte]
    latencia = int((time.perf_counter() - inicio) * 1000)
    propios = [h.model_copy(update={"latencia_ms": latencia}) for h in propios]
    if propios:
        principal = max(propios, key=lambda h: h.severidad)
        severidad, motivo, tipo = principal.severidad, principal.motivo, tipo_de(principal)
    else:
        severidad, motivo, tipo = 0, "Sin hallazgos.", "sin_hallazgos"
    probabilidades = [h.probabilidad for h in propios if h.probabilidad is not None]
    return propios, Evento(nombre, severidad, max(probabilidades) if probabilidades else None, latencia, motivo, tipo)


async def ejecutar_agentes_async(factura: FacturaCanonica, ctx: Contexto,
                                 agentes: Sequence[tuple[str, Agente]] = AGENTES, *,
                                 capa: Any = None, semanticos: Mapping[str, AgenteSemantico] | None = None,
                                 timeout_s: float = TIMEOUT_POR_DEFECTO_S) -> tuple[list[Hallazgo], list[Evento]]:
    """Corre todos los dominios en paralelo. Devuelve hallazgos y eventos en el orden de `agentes`."""
    semanticos = semanticos or {}
    resultados = await asyncio.gather(*(
        _dominio(nombre, agente, factura, ctx, timeout_s, semanticos.get(nombre), capa) for nombre, agente in agentes
    ))
    hallazgos = [h for propios, _ in resultados for h in propios]
    return hallazgos, [evento for _, evento in resultados]


def ejecutar_agentes(factura: FacturaCanonica, ctx: Contexto, agentes: Sequence[tuple[str, Agente]] = AGENTES,
                     **kwargs: Any) -> tuple[list[Hallazgo], list[Evento]]:
    """Versión síncrona (compatibilidad G2)."""
    return correr_sync(ejecutar_agentes_async(factura, ctx, agentes, **kwargs))
