from __future__ import annotations
from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, Field

Canal = Literal["telegram", "web", "email", "chat"]
Severidad = Literal[0, 1, 2]                       # 0 PAGAR, 1 ESCALAR, 2 FRENAR
DecisionTipo = Literal["PAGAR", "ESCALAR", "FRENAR"]


class Linea(BaseModel):
    descripcion: str
    cantidad: float
    precio_unitario: float
    total: float


class FacturaCanonica(BaseModel):
    id_documento: str                              # SHA-256 del archivo original
    archivo: str                                   # ruta relativa al original
    canal: Canal
    proveedor: str
    id_fiscal: str | None = None
    cuenta_bancaria: str | None = None
    numero_factura: str
    fecha_emision: date
    fecha_vencimiento: date | None = None
    moneda: str                                    # ISO 4217: COP, MXN, ARS, PEN, USD
    lineas: list[Linea]
    subtotal: float
    impuestos: float = 0.0
    total: float
    referencia_contrato: str | None = None
    texto_libre: str = ""                          # cuerpo del correo o mensaje de chat
    texto_oculto: list[str] = Field(default_factory=list)   # del escáner
    extraccion_ok: bool = True
    diferencias: list[str] = Field(default_factory=list)    # A vs B, aritmética


class Hallazgo(BaseModel):
    agente: str                                    # "duplicados", "contrato", ...
    severidad: Severidad
    probabilidad: float | None = None              # de Jev, si aplica
    motivo: str                                    # frase en español, legible
    evidencia: str = ""
    campo: str | None = None
    latencia_ms: int = 0


class Decision(BaseModel):
    factura_id: str
    numero_factura: str
    proveedor: str
    decision: DecisionTipo
    estado: Literal["final", "pendiente_humano"] = "final"
    explicacion: str
    contrafactual: str | None = None
    hallazgos: list[Hallazgo]
    cedar: Literal["ALLOW", "DENY"]
    monto_original: float
    moneda: str
    monto_usd: float
    fx_rate: float
    fx_source: str
    version_reglas: str
    aprobador: str | None = None
    aprobado: bool | None = None
    ts: datetime
    hash_prev: str
    hash: str
