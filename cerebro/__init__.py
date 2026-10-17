"""Dev 2 · cerebro de decisión.

    from cerebro import decidir, reanudar, verificar_cadena
    decision = decidir(factura)                          # nunca lanza; ESCALAR queda pendiente_humano
    decision = reanudar(factura_id, aprobado, aprobador) # revalida bajo transacción
    ok, fila_rota = verificar_cadena()

Los modelos solo aportan Hallazgo; las reglas deciden; una persona firma las excepciones.
Todo PAGAR es una autorización SIMULADA: aquí no se mueve dinero. Contrato completo para
Dev 3 en cerebro/README.md.

Flujo de decidir (G3):
  1. reglas.yaml se relee (versión = SHA-256) y se toma una instantánea de LECTURA del contexto.
  2. Los cinco agentes corren en paralelo (asyncio), SIN ninguna transacción de escritura abierta.
  3. Transacción final BEGIN IMMEDIATE (sin esperas externas): se verifica que las reglas no
     cambiaron y que el registro de pagos es íntegro; se recalculan saldo, límites y duplicados;
     se agrega (veto monotónico), se sella la decisión y, si es PAGAR, se anota el pago simulado.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import threading
import time
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from cerebro.agentes import AGENTES, Agente, AgenteSemantico, Evento, ejecutar_agentes_async
from cerebro.agentes import duplicados as agente_duplicados
from cerebro.agregador import Resultado, agregar, explicar, resumen
from cerebro.asincronia import correr_sync
from cerebro.codigos import ACCIONES
from cerebro.config import RAIZ, Reglas, cargar_reglas, ref_date_configurada
from cerebro.contexto import Catalogo, Contexto, construir_contexto
from cerebro.contrafactual import contrafactual
from cerebro.db import BaseDatos, ahora, insertar_pago_simulado, leer_secreto, verificar_pagos
from cerebro.dinero import cents_a_decimal, usd_es
from cerebro.firma import Firmante
from cerebro.privacidad import enmascarar_texto, proteger_factura, sanear_decision
from cerebro.registro import sellar
from cerebro.registro import verificar_cadena as _verificar_cadena
from cerebro.reglas import Evaluacion, evaluar
from cerebro.reinicio import Puerta, ReinicioOcupado, reiniciar
from cerebro.tipos import causa, fallo, tipo_de
from schemas import Decision, FacturaCanonica, Hallazgo

__all__ = [
    "CadenaAlterada", "Cerebro", "NoAprobable", "ReevaluacionNecesaria", "decidir", "decidir_async",
    "ReinicioOcupado", "paquete_evidencia", "reanudar", "reevaluar", "reiniciar_demo", "simular_politica",
    "verificar_cadena",
]

log = logging.getLogger(__name__)
REGLAS_DE_ENTRADA = frozenset({"extraccion", "datos", "fx"})   # sin monto validado no hay excepción posible
_MAX_CLAVE_IDEMPOTENCIA = 200


class CadenaAlterada(RuntimeError):
    """El registro fue manipulado: no se aprueba nada hasta revisarlo."""


class NoAprobable(ValueError):
    """La decisión no admite aprobación humana (FRENAR: cuenta no registrada, proveedor no permitido,
    duplicado exacto, inyección, tope duro…). Lleva el código y la acción requerida."""

    def __init__(self, mensaje: str, codigo: str = "OK", accion_requerida: str | None = None) -> None:
        super().__init__(mensaje)
        self.codigo = codigo
        self.accion_requerida = accion_requerida


class ReevaluacionNecesaria(RuntimeError):
    """Un detector falló al revalidar: la factura sigue pendiente; reintente o reevalúe."""


def _factura_id(factura: FacturaCanonica) -> str:
    if factura.id_documento:
        return factura.id_documento
    return "sin-hash-" + hashlib.sha256(factura.model_dump_json().encode("utf-8")).hexdigest()


def _finito(valor: float) -> float:
    return float(valor) if isinstance(valor, int | float) and math.isfinite(valor) else 0.0


def _unir(*listas: Iterable[Hallazgo]) -> list[Hallazgo]:
    """Une hallazgos sin repetir (mismo agente, severidad y motivo). Solo suma: nunca quita."""
    vistos: dict[tuple[str, int, str], Hallazgo] = {}
    for lista in listas:
        for h in lista:
            vistos.setdefault((h.agente, h.severidad, h.motivo), h)
    return list(vistos.values())


def decision_de_emergencia(factura: FacturaCanonica, error: BaseException, version_reglas: str = "desconocida",
                           ) -> Decision:
    """Error técnico: ESCALAR con la causa visible, o FRENAR si ya se sabe que hay texto oculto."""
    hallazgos = [fallo("sistema", f"Error técnico al decidir ({causa(error)}); se escala por seguridad.",
                       causa(error))]
    if factura.texto_oculto:
        hallazgos.insert(0, Hallazgo(agente="seguridad", severidad=2, campo="texto_oculto", codigo="TEXTO_OCULTO",
                                     motivo=f"Texto oculto encontrado: '{' | '.join(factura.texto_oculto)[:160]}'.",
                                     evidencia="oculto=" + " | ".join(factura.texto_oculto)))
    frenar = hallazgos[0].severidad == 2
    return Decision(
        factura_id=_factura_id(factura), numero_factura=factura.numero_factura, proveedor=factura.proveedor,
        decision="FRENAR" if frenar else "ESCALAR", estado="final" if frenar else "pendiente_humano",
        explicacion=resumen(hallazgos), contrafactual=None, hallazgos=hallazgos, cedar="DENY",
        monto_original=_finito(factura.total), moneda=factura.moneda, monto_usd=0.0, fx_rate=0.0,
        fx_source="no evaluado", version_reglas=version_reglas, ts=datetime.now(UTC), hash_prev="", hash="",
        codigo_principal=hallazgos[0].codigo, aprobable=False,
        accion_requerida=None if frenar else ACCIONES["ERROR_TECNICO"],
    )


def _ms(inicio: float) -> int:
    return int((time.perf_counter() - inicio) * 1000)


class Cerebro:
    def __init__(self, *, db_path: Path, datos: Path = RAIZ / "datos", reglas_path: Path = RAIZ / "reglas.yaml",
                 ref_date: date | None = None, agentes: Sequence[tuple[str, Agente]] = AGENTES,
                 aprobadores: frozenset[str] | None = None, exigir_aprobadores: bool = False,
                 capa: Any = None, semanticos: Mapping[str, AgenteSemantico] | None = None,
                 timeout_agente_s: float | None = None, firmante: Firmante | None = None,
                 administradores: frozenset[str] | None = None, db_base_path: Path | None = None) -> None:
        self.datos = Path(datos)
        self.reglas_path = Path(reglas_path)
        self.reglas = cargar_reglas(self.reglas_path)
        self.catalogo = Catalogo.cargar(self.datos)
        self.ref_date = ref_date or ref_date_configurada()
        self.agentes = tuple(agentes)
        self.aprobadores = aprobadores
        self.exigir_aprobadores = exigir_aprobadores
        self.capa = capa
        if semanticos is None and capa is not None:
            from cerebro.semantica import SEMANTICOS
            semanticos = SEMANTICOS
        self.semanticos = dict(semanticos or {})
        self.timeout_agente_s = timeout_agente_s if timeout_agente_s is not None else float(
            os.environ.get("CEREBRO_TIMEOUT_AGENTE_S") or 3.0)
        self.firmante = firmante
        self.administradores = administradores
        self._puerta = Puerta()
        self.db = BaseDatos(db_path)
        self.ruta_base = Path(db_base_path) if db_base_path else self.db.ruta.with_name(
            f"{self.db.ruta.stem}_base{self.db.ruta.suffix}")
        self.db.inicializar(self.historico_csv, self.reglas)
        self._cargar_secreto()

    def _cargar_secreto(self) -> None:
        with self.db.lectura() as con:
            self.secreto = leer_secreto(con)

    # ---------- privacidad: ninguna cuenta completa sale del cerebro ----------

    def _cuentas(self, factura: FacturaCanonica | None = None) -> list[str]:
        registradas = [str(p.get("cuenta_registrada")) for p in self.catalogo.proveedores if p.get("cuenta_registrada")]
        return ([factura.cuenta_bancaria] if factura and factura.cuenta_bancaria else []) + registradas

    def _factura_json(self, factura: FacturaCanonica) -> str:
        """La factura que se guarda en el registro: cuenta como token HMAC, textos enmascarados."""
        return proteger_factura(factura, self.secreto, self._cuentas(factura)).model_dump_json()

    def _sellar(self, con, decision: Decision, factura_json: str, factura: FacturaCanonica | None = None,
                clave_idempotencia: str | None = None) -> tuple[Decision, int]:
        return sellar(con, sanear_decision(decision, self._cuentas(factura)), factura_json, self.firmante,
                      clave_idempotencia)

    @property
    def historico_csv(self) -> Path:
        return self.datos / "historico_pagos.csv"

    @property
    def modo_semantico(self) -> str:
        return getattr(self.capa, "modo", "determinista") if self.capa is not None else "determinista"

    # ---------- lectura ----------

    def contexto(self, factura: FacturaCanonica) -> Contexto:
        with self.db.lectura() as con:
            return construir_contexto(factura, con, self.catalogo, self.reglas, self.ref_date, self.secreto)

    def verificar_cadena(self) -> tuple[bool, int | None]:
        with self.db.lectura() as con:
            return _verificar_cadena(con, self.firmante)

    def verificar_pagos(self) -> list[str]:
        with self.db.lectura() as con:
            return verificar_pagos(con, self.historico_csv)

    def _reglas_actuales(self) -> Reglas:
        self.reglas = cargar_reglas(self.reglas_path)
        return self.reglas

    async def _agentes(self, factura: FacturaCanonica, reglas: Reglas) -> tuple[list[Hallazgo], list[Evento]]:
        with self.db.lectura() as con:
            ctx = construir_contexto(factura, con, self.catalogo, reglas, self.ref_date, self.secreto)
        return await ejecutar_agentes_async(factura, ctx, self.agentes, capa=self.capa, semanticos=self.semanticos,
                                            timeout_s=self.timeout_agente_s)

    def _revalidar(self, con, factura: FacturaCanonica,
                   reglas: Reglas) -> tuple[Contexto, Evaluacion, list[Hallazgo], list[Hallazgo]]:
        """Dentro de la transacción final: nada externo, solo código y la base."""
        fallos: list[Hallazgo] = []
        actuales = cargar_reglas(self.reglas_path)
        for version in (reglas, actuales):
            con.execute("INSERT OR IGNORE INTO reglas_versiones (version, contenido, cargada_en) VALUES (?, ?, ?)",
                        (version.version, version.contenido, ahora()))
        if actuales.version != reglas.version:
            fallos.append(fallo("reglas", f"Las reglas cambiaron durante la evaluación ({reglas.version[:12]} → "
                                          f"{actuales.version[:12]}); hay que reevaluar antes de pagar.",
                                "reglas_versiones"))
        integra, fila_rota = _verificar_cadena(con, self.firmante)
        if not integra:
            fallos.append(fallo("registro", f"El registro de decisiones está alterado (fila {fila_rota}): no se "
                                            "autoriza ningún pago hasta revisarlo.", "decision_log"))
        problemas = verificar_pagos(con, self.historico_csv)
        if problemas:
            fallos.append(fallo("registro", "El registro de pagos no es íntegro (" + "; ".join(problemas[:3])
                                + "): no se autoriza ningún pago.", "pagos"))
        ctx = construir_contexto(factura, con, self.catalogo, reglas, self.ref_date, self.secreto)
        evaluacion = evaluar(ctx)
        try:
            revalidados = agente_duplicados.revisar(factura, ctx)
        except Exception as error:
            revalidados = [fallo("duplicados", f"No se pudo revalidar duplicados ({causa(error)}).", causa(error))]
        return ctx, evaluacion, revalidados, fallos

    # ---------- decidir ----------

    def decidir(self, factura: FacturaCanonica) -> Decision:
        """Nunca lanza. Ante cualquier error devuelve ESCALAR (o FRENAR si hay texto oculto) con la causa."""
        try:
            return correr_sync(self.decidir_async(factura))
        except Exception as error:
            log.exception("Error técnico decidiendo")
            return self._emergencia(factura, error)

    async def decidir_async(self, factura: FacturaCanonica) -> Decision:
        with self._puerta.operacion():                       # un reinicio de la demo espera a que termine
            return (await self._decidir_con_traza(factura))[0]

    async def _con_puerta_traza(self, factura: FacturaCanonica) -> tuple[Decision, dict[str, int]]:
        with self._puerta.operacion():
            return await self._decidir_con_traza(factura)

    def decidir_con_traza(self, factura: FacturaCanonica) -> tuple[Decision, dict[str, int]]:
        """Como decidir(), más la latencia por etapa (para cerebro.medir)."""
        try:
            return correr_sync(self._con_puerta_traza(factura))
        except Exception as error:
            return self._emergencia(factura, error), {}

    async def _decidir_con_traza(self, factura: FacturaCanonica) -> tuple[Decision, dict[str, int]]:
        traza: dict[str, int] = {}
        inicio = time.perf_counter()
        try:
            reglas = self._reglas_actuales()
            hallazgos, eventos = await self._agentes(factura, reglas)
            traza["agentes_ms"] = _ms(inicio)
            traza.update({f"agente.{e.agente}_ms": e.latencia_ms for e in eventos})
            inicio_final = time.perf_counter()
            with self.db.transaccion() as con:
                ctx, evaluacion, revalidados, fallos = self._revalidar(con, factura, reglas)
                todos = _unir(hallazgos, revalidados)
                resultado = agregar(extraccion_ok=ctx.extraccion_ok, cedar=evaluacion.cedar,
                                    fallas=evaluacion.fallas, hallazgos=todos, fallos=fallos)
                decision = self._armar(
                    factura, ctx, resultado, evaluacion.cedar, explicar(resultado, ctx),
                    None if resultado.decision == "PAGAR" else contrafactual(ctx, evaluacion.fallas, todos + fallos),
                    version_reglas=reglas.version,
                )
                sellada, fila = self._sellar(con, decision, self._factura_json(factura), factura)
                if sellada.decision == "PAGAR":
                    self._pagar_simulado(con, sellada, ctx, fila)
                self._guardar_eventos(con, sellada.factura_id, fila, eventos, evaluacion, fallos,
                                      _ms(inicio_final), self._cuentas(factura))
            traza["revalidacion_ms"] = _ms(inicio_final)
            traza["total_ms"] = _ms(inicio)
            return sellada, traza
        except Exception as error:
            log.exception("Error técnico decidiendo %s", factura.id_documento[:12])
            traza["total_ms"] = _ms(inicio)
            return self._emergencia(factura, error), traza

    def _armar(self, factura: FacturaCanonica, ctx: Contexto, resultado: Resultado, cedar: str, explicacion: str,
               contrafactual_texto: str | None, **extra: Any) -> Decision:
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
            version_reglas=ctx.reglas.version, ts=datetime.now(UTC), hash_prev="", hash="",
            codigo_principal=resultado.codigo_principal, aprobable=resultado.aprobable,
            accion_requerida=resultado.accion_requerida,
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
                         fallos: list[Hallazgo], latencia_final_ms: int, cuentas: list[str] = ()) -> None:
        severidad_reglas = max((f.severidad for f in evaluacion.fallas), default=0)
        motivo_reglas = evaluacion.fallas[0].motivo if evaluacion.fallas else "ALLOW: todas las reglas se cumplen."
        filas = [(e.agente, e.severidad, e.probabilidad, e.latencia_ms, e.motivo, e.tipo) for e in eventos]
        filas.append(("reglas", severidad_reglas, None, latencia_final_ms, motivo_reglas,
                      "riesgo" if evaluacion.fallas else "sin_hallazgos"))
        if fallos:
            filas.append(("revalidacion", 1, None, latencia_final_ms, fallos[0].motivo, "fallo_tecnico"))
        con.executemany(
            "INSERT INTO eventos (factura_id, decision_id, agente, severidad, probabilidad, latencia_ms, motivo, tipo,"
            " ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(factura_id, fila, a, s, p, ms, enmascarar_texto(m, cuentas), t, ahora()) for a, s, p, ms, m, t in filas],
        )

    def _emergencia(self, factura: FacturaCanonica, error: BaseException) -> Decision:
        decision = decision_de_emergencia(factura, error, self.reglas.version)
        try:
            with self.db.transaccion() as con:
                return self._sellar(con, decision, self._factura_json(factura), factura)[0]
        except Exception:
            log.exception("Tampoco se pudo registrar la decisión de emergencia")
            decision = sanear_decision(decision, self._cuentas(factura))
            return decision.model_copy(update={"explicacion": decision.explicacion + " No se pudo registrar."})

    # ---------- aprobación humana ----------

    def _autorizar(self, aprobador: object, aprobado: object, clave_idempotencia: object) -> str:
        if not isinstance(aprobador, str) or not aprobador.strip():
            raise ValueError("Falta el aprobador")
        if not isinstance(aprobado, bool):
            raise ValueError("aprobado debe ser True o False")
        if clave_idempotencia is not None and (not isinstance(clave_idempotencia, str) or not clave_idempotencia
                                               or len(clave_idempotencia) > _MAX_CLAVE_IDEMPOTENCIA):
            raise ValueError("clave_idempotencia inválida")
        aprobador = aprobador.strip()
        if self.aprobadores:
            if aprobador not in self.aprobadores:
                raise PermissionError(f"'{aprobador}' no es un aprobador autorizado")
        elif self.exigir_aprobadores and aprobado:
            raise PermissionError("No hay aprobadores configurados (CEREBRO_APROBADORES): no se aprueba nada")
        return aprobador

    @staticmethod
    def _repetida(con, clave: str | None, factura_id: str, aprobado: bool, aprobador: str) -> Decision | None:
        """Idempotencia: la misma clave con los mismos datos devuelve la resolución ya registrada."""
        if clave is None:
            return None
        fila = con.execute("SELECT factura_id, decision_json FROM decision_log WHERE clave_idempotencia = ?"
                           " ORDER BY id LIMIT 1", (clave,)).fetchone()
        if fila is None:
            return None
        previa = Decision.model_validate_json(fila[1])
        if fila[0] != factura_id or previa.aprobador != aprobador or previa.aprobado is not aprobado:
            raise ValueError("La clave de idempotencia ya se usó con otra factura u otra resolución")
        return previa

    @staticmethod
    def _pendiente(con, factura_id: str) -> tuple[int, Decision, str]:
        fila = con.execute("SELECT id, decision, estado, decision_json, factura_json FROM decision_log"
                           " WHERE factura_id = ? ORDER BY id DESC LIMIT 1", (factura_id,)).fetchone()
        if fila is None:
            raise LookupError(f"No hay decisiones para {factura_id}")
        decision = Decision.model_validate_json(fila[3])
        if fila[1] == "FRENAR" and decision.aprobador is None:
            raise NoAprobable(f"La factura {factura_id} quedó en FRENAR ({decision.codigo_principal}): no admite "
                              "aprobación humana", decision.codigo_principal, decision.accion_requerida)
        if fila[1] != "ESCALAR" or fila[2] != "pendiente_humano":
            raise ValueError(f"La factura {factura_id} no está pendiente de aprobación ({fila[1]}, {fila[2]})")
        return int(fila[0]), decision, fila[4]

    def _verificar_o_fallar(self, con) -> None:
        integra, fila_rota = _verificar_cadena(con, self.firmante)
        if not integra:
            raise CadenaAlterada(f"La cadena de decisiones está alterada en la fila {fila_rota}: no se aprueba nada")

    def reanudar(self, factura_id: str, aprobado: bool, aprobador: str, *,
                 clave_idempotencia: str | None = None) -> Decision:
        return correr_sync(self.reanudar_async(factura_id, aprobado, aprobador,
                                               clave_idempotencia=clave_idempotencia))

    async def reanudar_async(self, factura_id: str, aprobado: bool, aprobador: str, *,
                             clave_idempotencia: str | None = None) -> Decision:
        with self._puerta.operacion():
            return await self._reanudar(factura_id, aprobado, aprobador, clave_idempotencia=clave_idempotencia)

    async def _reanudar(self, factura_id: str, aprobado: bool, aprobador: str, *,
                        clave_idempotencia: str | None = None) -> Decision:
        """Resuelve un ESCALAR pendiente.

        - Rechazar → FRENAR firmado por el humano.
        - Aprobar → se revalida todo: un FRENAR (inyección, tope duro, saldo, duplicado exacto…) o una
          extracción/FX/datos no validados terminan en FRENAR ("corrija la entrada"); un fallo técnico
          lanza ReevaluacionNecesaria y la factura sigue pendiente. Solo sin nada de eso → PAGAR simulado.
        - Doble aprobación: solo la primera resuelve; con la misma clave_idempotencia se devuelve la misma
          resolución, sin otra la segunda falla con ValueError.
        """
        aprobador = self._autorizar(aprobador, aprobado, clave_idempotencia)
        with self.db.lectura() as con:
            self._verificar_o_fallar(con)
            repetida = self._repetida(con, clave_idempotencia, factura_id, aprobado, aprobador)
            if repetida is not None:
                return repetida
            fila_pendiente, previa, factura_json = self._pendiente(con, factura_id)
        try:
            factura: FacturaCanonica | None = FacturaCanonica.model_validate_json(factura_json)
        except ValidationError:
            factura = None

        reglas = self._reglas_actuales()
        hallazgos: list[Hallazgo] = []
        if aprobado and factura is not None:      # las llamadas externas, fuera de la transacción
            hallazgos, _ = await self._agentes(factura, reglas)

        with self.db.transaccion() as con:
            self._verificar_o_fallar(con)
            repetida = self._repetida(con, clave_idempotencia, factura_id, aprobado, aprobador)
            if repetida is not None:
                return repetida
            if self._pendiente(con, factura_id)[0] != fila_pendiente:
                raise ValueError(f"La factura {factura_id} ya fue resuelta por otra solicitud")
            humano = {"aprobador": aprobador, "aprobado": aprobado, "estado": "final", "ts": datetime.now(UTC),
                      "hash_prev": "", "hash": "", "contrafactual": None, "aprobable": False,
                      "accion_requerida": None}

            # Filas anteriores a v2 pueden tener la factura en claro: se vuelve a guardar protegida.
            guardar = self._factura_json(factura) if factura is not None else factura_json

            def registrar(decision: Decision) -> Decision:
                return self._sellar(con, decision, guardar, factura, clave_idempotencia)[0]

            if not aprobado:
                return registrar(previa.model_copy(update={
                    **humano, "decision": "FRENAR", "explicacion": f"Rechazada por {aprobador}: {previa.explicacion}"}))
            if factura is None:
                return registrar(previa.model_copy(update={
                    **humano, "decision": "FRENAR",
                    "explicacion": "No se puede aprobar: la factura registrada no es válida."}))

            ctx, evaluacion, revalidados, fallos = self._revalidar(con, factura, reglas)
            todos = _unir(hallazgos, revalidados)
            resultado = agregar(extraccion_ok=ctx.extraccion_ok, cedar=evaluacion.cedar, fallas=evaluacion.fallas,
                                hallazgos=todos, fallos=fallos)
            # La autorización se RECALCULA aquí, en el servidor; nunca se confía en un `aprobable` externo.
            vetos = [h for h in resultado.hallazgos if h.severidad == 2]
            entrada = [f.como_hallazgo() for f in evaluacion.fallas if f.regla in REGLAS_DE_ENTRADA]
            entrada += [h for h in resultado.hallazgos if h.codigo == "EXTRACCION" or tipo_de(h) == "sin_evidencia"]
            tecnicos = [h for h in resultado.hallazgos if h.codigo == "ERROR_TECNICO" or tipo_de(h) == "fallo_tecnico"]
            if vetos:
                return registrar(self._armar(factura, ctx, resultado, evaluacion.cedar,
                                             f"No se puede aprobar: {resumen(vetos)}", None,
                                             decision="FRENAR", version_reglas=reglas.version, **humano))
            if entrada:
                return registrar(self._armar(factura, ctx, resultado, evaluacion.cedar,
                                             f"No se puede aprobar: {resumen(entrada)} Corrija la entrada y vuelva "
                                             "a enviarla.", None,
                                             decision="FRENAR", version_reglas=reglas.version, **humano))
            if tecnicos or not resultado.aprobable:
                tecnicos = tecnicos or resultado.hallazgos
                raise ReevaluacionNecesaria(f"No se aprueba todavía: {resumen(tecnicos)} La factura sigue pendiente.")

            if not previa.aprobable:
                # El aprobador vio una evaluación incompleta (datos dudosos o un detector caído): aunque la
                # revalidación salga limpia, esta aprobación no paga. Hay que reevaluar y aprobar de nuevo.
                raise ReevaluacionNecesaria(
                    f"La decisión registrada no era aprobable ({previa.codigo_principal}). Use reevaluar() para "
                    "que el aprobador vea la evaluación completa y vuelva a decidir.")
            escalado = resultado.hallazgos[0].motivo if resultado.hallazgos else "sin motivo pendiente"
            explicacion = (f"Pago autorizado (simulado) por {aprobador} como excepción: {ctx.nombre_factura}, "
                           f"{usd_es(ctx.monto_usd_cents or 0)}. Se había escalado por: {escalado}")
            sellada, fila = self._sellar(con, self._armar(factura, ctx, resultado, evaluacion.cedar, explicacion,
                                                          None, decision="PAGAR", version_reglas=reglas.version,
                                                          **humano),
                                         guardar, factura, clave_idempotencia)
            self._pagar_simulado(con, sellada, ctx, fila)
            return sellada

    def reevaluar(self, factura_id: str) -> Decision:
        return correr_sync(self.reevaluar_async(factura_id))

    async def reevaluar_async(self, factura_id: str) -> Decision:
        """Nueva validación completa de un ESCALAR pendiente (por ejemplo, tras un fallo de Jev). No paga
        nada: produce una decisión nueva en el registro, que vuelve a pasar por la aprobación humana."""
        with self._puerta.operacion():
            with self.db.lectura() as con:
                self._verificar_o_fallar(con)
                _, _, factura_json = self._pendiente(con, factura_id)
            return (await self._decidir_con_traza(FacturaCanonica.model_validate_json(factura_json)))[0]

    # ---------- demo ----------

    def reiniciar_demo(self, admin: str, *, timeout_s: float = 30.0, respaldar: bool = True) -> dict[str, Any]:
        """Vuelve la base de la demo al estado inicial (ver cerebro/reinicio.py). Solo administradores."""
        return reiniciar(self, admin, timeout_s=timeout_s, respaldar=respaldar)

    # ---------- evidencia y sandbox ----------

    def paquete_evidencia(self, factura_id: str) -> dict[str, Any]:
        from cerebro.evidencia import paquete_evidencia
        return paquete_evidencia(self, factura_id)

    def simular_politica(self, factura: FacturaCanonica | str, cambios: Mapping[str, Any]) -> dict[str, Any]:
        from cerebro.sandbox import simular
        return simular(self, factura, cambios)


# ---------- interfaz pública del módulo (00_COMUN §4) ----------

_por_defecto: Cerebro | None = None
_candado = threading.Lock()


def _lista_entorno(*nombres: str) -> frozenset[str] | None:
    for nombre in nombres:
        valor = os.environ.get(nombre, "")
        elementos = frozenset(e.strip() for e in valor.split(",") if e.strip())
        if elementos:
            return elementos
    return None


def construir_desde_entorno() -> Cerebro:
    """DB_PATH, REF_DATE, CEREBRO_APROBADORES (o TELEGRAM_APROBADORES), SIGNING_KEY_PATH,
    CEREBRO_SEMANTICA y CEREBRO_TIMEOUT_AGENTE_S. Ver cerebro/README.md."""
    from cerebro.semantica import capa_desde_entorno

    ruta_firma = os.environ.get("SIGNING_KEY_PATH", "").strip()
    return Cerebro(
        db_path=Path(os.environ.get("DB_PATH") or "blinka.db"),
        aprobadores=_lista_entorno("CEREBRO_APROBADORES", "TELEGRAM_APROBADORES"),
        exigir_aprobadores=True,
        capa=capa_desde_entorno(),
        firmante=Firmante.desde_archivo(Path(ruta_firma)) if ruta_firma else None,
        administradores=_lista_entorno("CEREBRO_ADMINS"),
        db_base_path=Path(os.environ["DB_BASE_PATH"]) if os.environ.get("DB_BASE_PATH") else None,
    )


def _cerebro() -> Cerebro:
    global _por_defecto
    with _candado:
        if _por_defecto is None:
            _por_defecto = construir_desde_entorno()
        return _por_defecto


def decidir(factura: FacturaCanonica) -> Decision:
    try:
        cerebro = _cerebro()
    except Exception as error:      # ni siquiera se pudo iniciar: igual se responde, sin pagar
        log.exception("No se pudo iniciar el cerebro")
        return decision_de_emergencia(factura, error)
    return cerebro.decidir(factura)


async def decidir_async(factura: FacturaCanonica) -> Decision:
    try:
        cerebro = _cerebro()
    except Exception as error:
        log.exception("No se pudo iniciar el cerebro")
        return decision_de_emergencia(factura, error)
    try:
        return await cerebro.decidir_async(factura)
    except Exception as error:
        return cerebro._emergencia(factura, error)


def reanudar(factura_id: str, aprobado: bool, aprobador: str, *, clave_idempotencia: str | None = None) -> Decision:
    return _cerebro().reanudar(factura_id, aprobado, aprobador, clave_idempotencia=clave_idempotencia)


def reiniciar_demo(admin: str, *, timeout_s: float = 30.0) -> dict[str, Any]:
    return _cerebro().reiniciar_demo(admin, timeout_s=timeout_s)


def reevaluar(factura_id: str) -> Decision:
    return _cerebro().reevaluar(factura_id)


def verificar_cadena() -> tuple[bool, int | None]:
    return _cerebro().verificar_cadena()


def paquete_evidencia(factura_id: str) -> dict[str, Any]:
    return _cerebro().paquete_evidencia(factura_id)


def simular_politica(factura: FacturaCanonica | str, cambios: Mapping[str, Any]) -> dict[str, Any]:
    return _cerebro().simular_politica(factura, cambios)
