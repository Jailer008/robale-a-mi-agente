"""Tres clases de Hallazgo, sin tocar schemas.py: se marcan con un prefijo en `evidencia`.

- riesgo         → evidencia real de un problema en la factura (por defecto).
- fallo_tecnico  → el detector no pudo correr (excepción, timeout, servicio caído).
- sin_evidencia  → el detector corrió pero faltan datos para concluir.

Los tres cuentan para el veto: fallo_tecnico y sin_evidencia son al menos ESCALAR.
"""

from __future__ import annotations

from typing import Literal

from schemas import Hallazgo

FALLO_TECNICO = "[fallo_tecnico]"
SIN_EVIDENCIA = "[sin_evidencia]"
TipoHallazgo = Literal["riesgo", "fallo_tecnico", "sin_evidencia"]
_MAX_CAUSA = 200


def tipo_de(h: Hallazgo) -> TipoHallazgo:
    if h.evidencia.startswith(FALLO_TECNICO):
        return "fallo_tecnico"
    if h.evidencia.startswith(SIN_EVIDENCIA):
        return "sin_evidencia"
    return "riesgo"


def causa(error: BaseException) -> str:
    return f"{type(error).__name__}: {error}"[:_MAX_CAUSA]


def fallo(agente: str, motivo: str, detalle: str = "") -> Hallazgo:
    return Hallazgo(agente=agente, severidad=1, motivo=motivo, evidencia=f"{FALLO_TECNICO} {detalle}".strip(),
                    codigo="ERROR_TECNICO")


def sin_evidencia(agente: str, motivo: str, campo: str | None = None, detalle: str = "") -> Hallazgo:
    return Hallazgo(agente=agente, severidad=1, motivo=motivo, campo=campo,
                    evidencia=f"{SIN_EVIDENCIA} {detalle}".strip(), codigo="EXTRACCION")
