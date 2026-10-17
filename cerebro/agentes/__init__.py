"""Los cinco agentes. Reciben (factura, contexto) y devuelven list[Hallazgo]; NUNCA una decisión.

G2: detectores 100 % deterministas. G3 añade Jev/LLM, que solo podrán sumar hallazgos.
Un agente que lanza, tarda o devuelve algo que no es list[Hallazgo] produce un
Hallazgo de severidad 1 con la causa visible (fail-closed).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from cerebro.agentes import beneficiario, contrato, duplicados, presupuesto, seguridad
from cerebro.contexto import Contexto
from schemas import FacturaCanonica, Hallazgo

log = logging.getLogger(__name__)
Agente = Callable[[FacturaCanonica, Contexto], list[Hallazgo]]
_MAX_ERROR = 200

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


def _ejecutar_uno(nombre: str, agente: Agente, factura: FacturaCanonica, ctx: Contexto) -> list[Hallazgo]:
    try:
        resultado = agente(factura, ctx)
        if not isinstance(resultado, list) or not all(isinstance(h, Hallazgo) for h in resultado):
            raise TypeError(f"devolvió {type(resultado).__name__} en lugar de list[Hallazgo]")
        return resultado
    except Exception as error:   # fail-closed: la causa queda visible en el motivo
        log.exception("Agente %s falló", nombre)
        causa = f"{type(error).__name__}: {error}"[:_MAX_ERROR]
        return [Hallazgo(agente=nombre, severidad=1, motivo=f"No se pudo verificar con el agente {nombre} ({causa}).",
                         evidencia="error técnico")]


def ejecutar_agentes(factura: FacturaCanonica, ctx: Contexto,
                     agentes: Sequence[tuple[str, Agente]] = AGENTES) -> tuple[list[Hallazgo], list[Evento]]:
    hallazgos: list[Hallazgo] = []
    eventos: list[Evento] = []
    for nombre, agente in agentes:
        inicio = time.perf_counter()
        propios = _ejecutar_uno(nombre, agente, factura, ctx)
        latencia = int((time.perf_counter() - inicio) * 1000)
        propios = [h.model_copy(update={"latencia_ms": latencia}) for h in propios]
        hallazgos += propios
        severidad = max((h.severidad for h in propios), default=0)
        principal = max(propios, key=lambda h: h.severidad).motivo if propios else "Sin hallazgos."
        probabilidades = [h.probabilidad for h in propios if h.probabilidad is not None]
        eventos.append(Evento(nombre, severidad, max(probabilidades) if probabilidades else None, latencia, principal))
    return hallazgos, eventos
