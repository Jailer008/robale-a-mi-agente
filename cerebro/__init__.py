"""Dev 2 · cerebro de decisión.

    from cerebro import decidir, reanudar, verificar_cadena
    decision = decidir(factura)                          # nunca lanza; ESCALAR queda pendiente_humano
    decision = reanudar(factura_id, aprobado, aprobador) # revalida bajo transacción
    ok, fila_rota = verificar_cadena()

Los modelos solo aportan Hallazgo; las reglas deciden; una persona firma las excepciones.
Todo PAGAR es una autorización SIMULADA: aquí no se mueve dinero.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import threading
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import ValidationError

from cerebro.agentes import AGENTES, Agente, Evento, ejecutar_agentes
from cerebro.agregador import Resultado, agregar, explicar, resumen
from cerebro.config import RAIZ, cargar_reglas, ref_date_configurada
from cerebro.contexto import Catalogo, Contexto, construir_contexto
from cerebro.contrafactual import contrafactual
from cerebro.db import BaseDatos, ahora, insertar_pago_simulado
from cerebro.dinero import cents_a_decimal, usd_es
from cerebro.registro import sellar
from cerebro.registro import verificar_cadena as _verificar_cadena
from cerebro.reglas import Evaluacion, evaluar
from schemas import Decision, FacturaCanonica, Hallazgo

__all__ = ["Cerebro", "decidir", "reanudar", "verificar_cadena"]

log = logging.getLogger(__name__)
NO_APROBABLES = frozenset({"extraccion", "datos", "fx"})   # sin monto validado no hay excepción posible
_MAX_ERROR = 200


def _factura_id(factura: FacturaCanonica) -> str:
    if factura.id_documento:
        return factura.id_documento
    return "sin-hash-" + hashlib.sha256(factura.model_dump_json().encode("utf-8")).hexdigest()


def _finito(valor: float) -> float:
    return float(valor) if isinstance(valor, int | float) and math.isfinite(valor) else 0.0


def decision_de_emergencia(factura: FacturaCanonica, error: BaseException, version_reglas: str = "desconocida",
                           ) -> Decision:
    """Error técnico: ESCALAR con la causa visible, o FRENAR si ya se sabe que hay texto oculto."""
    causa = f"{type(error).__name__}: {error}"[:_MAX_ERROR]
    hallazgos = [Hallazgo(agente="sistema", severidad=1, evidencia="error técnico",
                          motivo=f"Error técnico al decidir ({causa}); se escala por seguridad.")]
    if factura.texto_oculto:
        hallazgos.insert(0, Hallazgo(agente="seguridad", severidad=2, campo="texto_oculto",
                                     motivo=f"Texto oculto encontrado: '{' | '.join(factura.texto_oculto)[:160]}'.",
                                     evidencia=" | ".join(factura.texto_oculto)))
    frenar = hallazgos[0].severidad == 2
    return Decision(
        factura_id=_factura_id(factura), numero_factura=factura.numero_factura, proveedor=factura.proveedor,
        decision="FRENAR" if frenar else "ESCALAR", estado="final" if frenar else "pendiente_humano",
        explicacion=resumen(hallazgos), contrafactual=None, hallazgos=hallazgos, cedar="DENY",
        monto_original=_finito(factura.total), moneda=factura.moneda, monto_usd=0.0, fx_rate=0.0,
        fx_source="no evaluado", version_reglas=version_reglas, ts=datetime.now(UTC), hash_prev="", hash="",
    )


class Cerebro:
    def __init__(self, *, db_path: Path, datos: Path = RAIZ / "datos", reglas_path: Path = RAIZ / "reglas.yaml",
                 ref_date: date | None = None, agentes: Sequence[tuple[str, Agente]] = AGENTES,
                 aprobadores: frozenset[str] | None = None) -> None:
        self.datos = Path(datos)
        self.reglas = cargar_reglas(reglas_path)
        self.catalogo = Catalogo.cargar(self.datos)
        self.ref_date = ref_date or ref_date_configurada()
        self.agentes = tuple(agentes)
        self.aprobadores = aprobadores
        self.db = BaseDatos(db_path)
        self.db.inicializar(self.datos / "historico_pagos.csv", self.reglas)

    # ---------- lectura ----------

    def contexto(self, factura: FacturaCanonica) -> Contexto:
        with self.db.transaccion() as con:
            return construir_contexto(factura, con, self.catalogo, self.reglas, self.ref_date)

    def verificar_cadena(self) -> tuple[bool, int | None]:
        with self.db.transaccion() as con:
            return _verificar_cadena(con)

    # ---------- decidir ----------

    def decidir(self, factura: FacturaCanonica) -> Decision:
        """Nunca lanza. Ante cualquier error devuelve ESCALAR (o FRENAR si hay texto oculto) con la causa."""
        try:
            return self._decidir(factura)
        except Exception as error:
            log.exception("Error técnico decidiendo %s", factura.id_documento[:12])
            return self._emergencia(factura, error)

    def _evaluar(self, factura: FacturaCanonica, con) -> tuple[Contexto, Evaluacion, list[Hallazgo], list[Evento]]:
        ctx = construir_contexto(factura, con, self.catalogo, self.reglas, self.ref_date)
        evaluacion = evaluar(ctx)
        hallazgos, eventos = ejecutar_agentes(factura, ctx, self.agentes)
        return ctx, evaluacion, hallazgos, eventos

    def _decidir(self, factura: FacturaCanonica) -> Decision:
        # Una sola transacción de escritura: contexto, reglas, pago simulado y registro son atómicos,
        # así dos solicitudes simultáneas no ven el mismo saldo ni pagan dos veces.
        with self.db.transaccion() as con:
            inicio = datetime.now(UTC)
            ctx, evaluacion, hallazgos, eventos = self._evaluar(factura, con)
            resultado = agregar(extraccion_ok=ctx.extraccion_ok, cedar=evaluacion.cedar,
                                fallas=evaluacion.fallas, hallazgos=hallazgos)
            decision = self._armar(
                factura, ctx, resultado, evaluacion.cedar, explicar(resultado, ctx),
                None if resultado.decision == "PAGAR" else contrafactual(ctx, evaluacion.fallas, hallazgos),
            )
            sellada, fila = sellar(con, decision, factura.model_dump_json())
            if sellada.decision == "PAGAR":
                self._pagar_simulado(con, sellada, ctx, fila)
            self._guardar_eventos(con, sellada.factura_id, fila, eventos, evaluacion, inicio)
            return sellada

    def _armar(self, factura: FacturaCanonica, ctx: Contexto, resultado: Resultado, cedar: str, explicacion: str,
               contrafactual_texto: str | None, **extra) -> Decision:
        fx = ctx.fx
        campos = dict(
            factura_id=_factura_id(factura), numero_factura=factura.numero_factura, proveedor=factura.proveedor,
            decision=resultado.decision,
            estado="pendiente_humano" if resultado.decision == "ESCALAR" else "final",
            explicacion=explicacion, contrafactual=contrafactual_texto, hallazgos=resultado.hallazgos, cedar=cedar,
            monto_original=float(ctx.monto_original) if ctx.monto_original is not None else 0.0,
            moneda=ctx.moneda,
            monto_usd=float(cents_a_decimal(ctx.monto_usd_cents)) if ctx.monto_usd_cents is not None else 0.0,
            fx_rate=float(fx.unidades_por_usd) if fx else 0.0,
            fx_source=f"{fx.fuente} · {fx.fecha}" if fx else "sin tasa FX confiable",
            version_reglas=self.reglas.version, ts=datetime.now(UTC), hash_prev="", hash="",
        )
        campos.update(extra)
        return Decision(**campos)

    def _pagar_simulado(self, con, decision: Decision, ctx: Contexto, fila: int) -> None:
        if ctx.monto_original is None or ctx.monto_usd_cents is None:
            raise RuntimeError("PAGAR sin monto validado: invariante rota")
        insertar_pago_simulado(con, factura_id=decision.factura_id, proveedor=decision.proveedor,
                               numero_factura=decision.numero_factura, monto=str(ctx.monto_original),
                               moneda=ctx.moneda, monto_usd_cents=ctx.monto_usd_cents, fecha_pago=self.ref_date,
                               decision_id=fila)

    def _guardar_eventos(self, con, factura_id: str, fila: int, eventos: list[Evento], evaluacion: Evaluacion,
                         inicio: datetime) -> None:
        latencia_reglas = int((datetime.now(UTC) - inicio).total_seconds() * 1000)
        severidad_reglas = max((f.severidad for f in evaluacion.fallas), default=0)
        motivo_reglas = evaluacion.fallas[0].motivo if evaluacion.fallas else "ALLOW: todas las reglas se cumplen."
        filas = [(e.agente, e.severidad, e.probabilidad, e.latencia_ms, e.motivo) for e in eventos]
        filas.append(("reglas", severidad_reglas, None, latencia_reglas, motivo_reglas))
        con.executemany(
            "INSERT INTO eventos (factura_id, decision_id, agente, severidad, probabilidad, latencia_ms, motivo, ts)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(factura_id, fila, *f, ahora()) for f in filas],
        )

    def _emergencia(self, factura: FacturaCanonica, error: BaseException) -> Decision:
        decision = decision_de_emergencia(factura, error, self.reglas.version)
        try:
            with self.db.transaccion() as con:
                return sellar(con, decision, factura.model_dump_json())[0]
        except Exception:
            log.exception("Tampoco se pudo registrar la decisión de emergencia")
            return decision.model_copy(update={"explicacion": decision.explicacion + " No se pudo registrar."})

    # ---------- aprobación humana ----------

    def reanudar(self, factura_id: str, aprobado: bool, aprobador: str) -> Decision:
        """Resuelve un ESCALAR pendiente. Aprobar revalida todo bajo transacción: un FRENAR,
        una extracción no validada o un fallo técnico impiden pagar."""
        if not isinstance(aprobador, str) or not aprobador.strip():
            raise ValueError("Falta el aprobador")
        aprobador = aprobador.strip()
        if self.aprobadores is not None and aprobador not in self.aprobadores:
            raise PermissionError(f"'{aprobador}' no es un aprobador autorizado")
        if not isinstance(aprobado, bool):
            raise ValueError("aprobado debe ser True o False")

        with self.db.transaccion() as con:
            integra, fila_rota = _verificar_cadena(con)
            if not integra:
                raise RuntimeError(f"La cadena de decisiones está alterada en la fila {fila_rota}: no se aprueba nada")
            fila = con.execute("SELECT decision, estado, decision_json, factura_json FROM decision_log"
                               " WHERE factura_id = ? ORDER BY id DESC LIMIT 1", (factura_id,)).fetchone()
            if fila is None:
                raise LookupError(f"No hay decisiones para {factura_id}")
            if fila[0] != "ESCALAR" or fila[1] != "pendiente_humano":
                raise ValueError(f"La factura {factura_id} no está pendiente de aprobación ({fila[0]}, {fila[1]})")
            previa = Decision.model_validate_json(fila[2])
            humano = {"aprobador": aprobador, "aprobado": aprobado, "estado": "final", "ts": datetime.now(UTC),
                      "hash_prev": "", "hash": "", "contrafactual": None}

            if not aprobado:
                decision = previa.model_copy(update={**humano, "decision": "FRENAR",
                                                     "explicacion": f"Rechazada por {aprobador}: {previa.explicacion}"})
                return sellar(con, decision, fila[3])[0]

            try:
                factura = FacturaCanonica.model_validate_json(fila[3])
            except ValidationError:
                decision = previa.model_copy(update={**humano, "decision": "FRENAR", "explicacion":
                                                     "No se puede aprobar: la factura registrada no es válida."})
                return sellar(con, decision, fila[3])[0]

            ctx, evaluacion, hallazgos, _ = self._evaluar(factura, con)
            resultado = agregar(extraccion_ok=ctx.extraccion_ok, cedar=evaluacion.cedar,
                                fallas=evaluacion.fallas, hallazgos=hallazgos)
            bloqueos = [h for h in resultado.hallazgos if h.severidad == 2]
            bloqueos += [f.como_hallazgo() for f in evaluacion.fallas if f.regla in NO_APROBABLES]
            bloqueos += [h for h in hallazgos if h.evidencia == "error técnico"]
            if bloqueos:
                decision = self._armar(factura, ctx, resultado, evaluacion.cedar,
                                       f"No se puede aprobar: {resumen(bloqueos)}", None,
                                       decision="FRENAR", **humano)
                return sellar(con, decision, fila[3])[0]

            escalado = resultado.hallazgos[0].motivo if resultado.hallazgos else "sin motivo pendiente"
            explicacion = (f"Pago autorizado (simulado) por {aprobador} como excepción: {ctx.nombre_factura}, "
                           f"{usd_es(ctx.monto_usd_cents or 0)}. Se había escalado por: {escalado}")
            decision = self._armar(factura, ctx, resultado, evaluacion.cedar, explicacion, None,
                                   decision="PAGAR", **humano)
            sellada, fila_id = sellar(con, decision, fila[3])
            self._pagar_simulado(con, sellada, ctx, fila_id)
            return sellada


# ---------- interfaz pública del módulo (00_COMUN §4) ----------

_por_defecto: Cerebro | None = None
_candado = threading.Lock()


def _cerebro() -> Cerebro:
    """Instancia compartida: DB_PATH (por defecto ./blinka.db) y REF_DATE del entorno."""
    global _por_defecto
    with _candado:
        if _por_defecto is None:
            _por_defecto = Cerebro(db_path=Path(os.environ.get("DB_PATH") or "blinka.db"))
        return _por_defecto


def decidir(factura: FacturaCanonica) -> Decision:
    try:
        cerebro = _cerebro()
    except Exception as error:      # ni siquiera se pudo iniciar: igual se responde, sin pagar
        log.exception("No se pudo iniciar el cerebro")
        return decision_de_emergencia(factura, error)
    return cerebro.decidir(factura)


def reanudar(factura_id: str, aprobado: bool, aprobador: str) -> Decision:
    return _cerebro().reanudar(factura_id, aprobado, aprobador)


def verificar_cadena() -> tuple[bool, int | None]:
    return _cerebro().verificar_cadena()
