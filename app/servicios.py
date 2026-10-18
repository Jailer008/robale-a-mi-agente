"""Adaptador entre la API y el backend real (cerebro de Dev 2, extracción de Dev 1).

Reglas de este módulo:
- Toda decisión viene de cerebro.decidir_async / reanudar_async / reevaluar_async. Aquí no se decide nada.
- Las escrituras (decidir, aprobar, rechazar, reevaluar, reiniciar) pasan por un único candado: un solo
  proceso API y un solo escritor de SQLite (el aviso v2 pide procesamiento en serie).
- Las salidas son SIEMPRE vistas saneadas (cerebro.privacidad.vista_publica): cuentas enmascaradas, sin
  evidencia cruda. Los códigos visibles salen de la lista blanca cerebro.codigos.CODIGOS.
- El progreso por etapa registra transiciones REALES del flujo (recibido → extrayendo → evaluando →
  decidido). No se inventan tiempos, probabilidades ni eventos de agentes.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import cerebro
from app import VERSION
from app.config import Ajustes
from app.documentos import ETIQUETAS_FUENTE, extraer_documento, guardar, validar
from app.falsificar import CARPETA, ETIQUETA_FALSIFICADA, CasoFalsificado, base_aleatoria, dibujar
from app.sintetico import ETIQUETA_MODO, CasoSintetico, construir_factura
from cerebro import Cerebro, NoAprobable
from cerebro.codigos import CODIGOS
from cerebro.config import RAIZ
from cerebro.evidencia import responsable
from cerebro.privacidad import enmascarar, visible, vista_publica
from schemas import Decision, FacturaCanonica

JURADO = ("07", "08", "10", "11", "12", "14")
AGENTES_COMITE = ("duplicados", "contrato", "beneficiario", "seguridad", "presupuesto")
ADVERTENCIA = "Facturas 100 % ficticias. No hay pagos reales: PAGAR es una autorización simulada."
_MAX_PROGRESO = 500


class NoEncontrado(LookupError):
    pass


@dataclass
class Progreso:
    intento_id: str
    etapa: str
    factura_id: str | None
    actualizado: float


def origen_de(archivo: str) -> str:
    if archivo.startswith("sintetico/"):
        return ETIQUETA_MODO
    if f"/{CARPETA}/" in "/" + archivo.replace("\\", "/"):
        return ETIQUETA_FALSIFICADA
    if archivo.startswith("entrada/") or "/entrada/" in archivo.replace("\\", "/"):
        return "DOCUMENTO SUBIDO"
    if archivo.startswith("datos/facturas/"):
        return "PAQUETE DEL JURADO — SET FICTICIO (datos estructurados de Dev 1)"
    return "OTRO"


def codigo_seguro(codigo: str) -> str:
    return codigo if codigo in CODIGOS else "ERROR_TECNICO"


class Servicio:
    def __init__(self, ajustes: Ajustes, motor: Cerebro | None = None,
                 extractores: tuple[Any, Any] | None = None) -> None:
        self.ajustes = ajustes
        self.motor = motor or cerebro.construir_desde_entorno()
        self._extractores = extractores                          # solo pruebas: lectores sin modelos
        self._escritura = asyncio.Lock()
        self._progreso: OrderedDict[str, Progreso] = OrderedDict()
        self._fuentes: dict[str, str] = {}                     # factura_id → etiqueta de origen del documento
        self._candado = threading.Lock()
        self._metricas: dict[str, tuple[float, dict[str, Any]]] = {}

    # ---------- utilidades ----------

    def _etapa(self, intento_id: str, etapa: str, factura_id: str | None = None) -> None:
        with self._candado:
            previo = self._progreso.get(intento_id)
            self._progreso[intento_id] = Progreso(intento_id, etapa, factura_id or (previo.factura_id if previo
                                                                                      else None), time.time())
            self._progreso.move_to_end(intento_id)
            while len(self._progreso) > _MAX_PROGRESO:
                self._progreso.popitem(last=False)

    def progreso(self, intento_id: str) -> dict[str, Any]:
        with self._candado:
            p = self._progreso.get(intento_id)
        if p is None:
            raise NoEncontrado(intento_id)
        return {"intento_id": p.intento_id, "etapa": p.etapa, "factura_id": p.factura_id}

    def _publica(self, d: Decision) -> dict[str, Any]:
        vista = vista_publica(d, self.motor._cuentas())
        vista["codigo_principal"] = codigo_seguro(vista["codigo_principal"])
        for h in vista["hallazgos"]:
            h["codigo"] = codigo_seguro(h["codigo"])
        return vista

    def _regla_principal(self, d: Decision) -> dict[str, Any]:
        r = responsable(d)
        return {"tipo": r["tipo"], "nombre": r["nombre"], "severidad": r["severidad"],
                "codigo": codigo_seguro(d.hallazgos[0].codigo) if d.hallazgos else "OK"}

    @staticmethod
    def _resumen_factura(f: FacturaCanonica) -> dict[str, Any]:
        return {"proveedor": f.proveedor, "numero_factura": f.numero_factura,
                "fecha_emision": f.fecha_emision.isoformat(), "moneda": f.moneda,
                "cuenta_enmascarada": visible(f.cuenta_bancaria) or "",
                "lineas": [{"descripcion": li.descripcion, "cantidad": li.cantidad,
                            "precio_unitario": li.precio_unitario, "total": li.total} for li in f.lineas],
                "subtotal": f.subtotal, "impuestos": f.impuestos, "total": f.total}

    def _resultado(self, intento_id: str, d: Decision, f: FacturaCanonica, modo: str) -> dict[str, Any]:
        return {"intento_id": intento_id, "modo_analisis": modo, "advertencia": ADVERTENCIA,
                "decision": self._publica(d), "regla_principal": self._regla_principal(d),
                "factura": self._resumen_factura(f)}

    async def _decidir(self, intento_id: str, f: FacturaCanonica) -> Decision:
        self._etapa(intento_id, "evaluando", f.id_documento)
        async with self._escritura:
            d = await self.motor.decidir_async(f)
        self._etapa(intento_id, "decidido", d.factura_id)
        return d

    # ---------- ataques ----------

    async def simular(self, caso: CasoSintetico) -> dict[str, Any]:
        intento_id = uuid.uuid4().hex
        self._etapa(intento_id, "recibido")
        factura = construir_factura(caso)
        d = await self._decidir(intento_id, factura)
        self._fuentes[d.factura_id] = ETIQUETA_MODO
        return self._resultado(intento_id, d, factura, ETIQUETA_MODO)

    async def ingest(self, nombre: str | None, contenido: bytes, canal: str) -> dict[str, Any]:
        intento_id = uuid.uuid4().hex
        self._etapa(intento_id, "recibido")
        extension, sha = validar(nombre, contenido, self.ajustes.max_upload_bytes)
        ruta = guardar(contenido, extension, sha, self.ajustes.entrada)
        self._etapa(intento_id, "extrayendo", sha)
        factura, fuente = await asyncio.to_thread(extraer_documento, ruta, canal, live=self.ajustes.extraccion_live)
        etiqueta = ETIQUETAS_FUENTE[fuente]
        d = await self._decidir(intento_id, factura)
        self._fuentes[d.factura_id] = etiqueta
        return {**self._resultado(intento_id, d, factura, etiqueta), "fuente_extraccion": fuente}

    # ---------- modo «factura falsificada» (plan v2) ----------

    def base_aleatoria(self) -> dict[str, Any]:
        return base_aleatoria()

    def preview(self, base_id: str) -> bytes:
        from extraccion.render import listar_bases, preview_png

        if base_id not in listar_bases():
            raise NoEncontrado(base_id)
        return preview_png(base_id)

    async def falsificar(self, caso: CasoFalsificado) -> dict[str, Any]:
        """Dibuja la factura editada y la decide leyendo el PDF, nunca el formulario."""
        from extraccion.render import listar_bases

        if caso.base_id not in listar_bases():
            raise NoEncontrado(caso.base_id)
        intento_id = uuid.uuid4().hex
        self._etapa(intento_id, "recibido")
        ruta, cambiados = await asyncio.to_thread(dibujar, caso, intento_id[:8].upper(), self.ajustes.entrada)
        self._etapa(intento_id, "extrayendo")
        factura, fuente = await asyncio.to_thread(extraer_documento, ruta, "web", live=self.ajustes.extraccion_live,
                                                  extractores=self._extractores)
        d = await self._decidir(intento_id, factura)
        self._fuentes[d.factura_id] = ETIQUETA_FALSIFICADA
        return {**self._resultado(intento_id, d, factura, ETIQUETA_FALSIFICADA), "fuente_extraccion": fuente,
                "base_id": caso.base_id, "campos_cambiados": cambiados}

    async def paquete_jurado(self) -> list[dict[str, Any]]:
        """Las 6 facturas del paquete del jurado, desde los JSON canónicos (sin extracción ni red).
        Reproducible: si una ya se decidió, devuelve esa decisión y no crea otra. Ninguna es PAGAR."""
        salida = []
        for numero in JURADO:
            f = FacturaCanonica.model_validate_json(
                (RAIZ / "datos" / "facturas_json" / f"{numero}.json").read_text(encoding="utf-8"))
            existente = self._ultima(f.id_documento)
            if existente is None:
                intento_id = uuid.uuid4().hex
                self._etapa(intento_id, "recibido")
                existente = await self._decidir(intento_id, f)
            self._fuentes[existente.factura_id] = origen_de(f.archivo)
            salida.append({"numero": numero, "modo_analisis": origen_de(f.archivo),
                           "decision": self._publica(existente)})
        return salida

    # ---------- lectura ----------

    def _ultima(self, factura_id: str) -> Decision | None:
        with self.motor.db.lectura() as con:
            fila = con.execute("SELECT decision_json FROM decision_log WHERE factura_id = ? ORDER BY id DESC LIMIT 1",
                               (factura_id,)).fetchone()
        return Decision.model_validate_json(fila[0]) if fila else None

    def decisiones(self, limite: int, desplazamiento: int) -> dict[str, Any]:
        with self.motor.db.lectura() as con:
            total = con.execute("SELECT COUNT(DISTINCT factura_id) FROM decision_log").fetchone()[0]
            filas = con.execute(
                "SELECT d.decision_json, d.factura_json FROM decision_log d JOIN (SELECT factura_id, MAX(id) AS id"
                " FROM decision_log GROUP BY factura_id) u ON d.id = u.id ORDER BY d.id DESC LIMIT ? OFFSET ?",
                (limite, desplazamiento)).fetchall()
        items = []
        for decision_json, factura_json in filas:
            d = Decision.model_validate_json(decision_json)
            archivo = json.loads(factura_json).get("archivo", "")
            items.append({**self._publica(d), "origen": self._fuentes.get(d.factura_id, origen_de(archivo))})
        return {"total": total, "limite": limite, "desplazamiento": desplazamiento, "items": items}

    def eventos(self, factura_id: str) -> dict[str, Any]:
        with self.motor.db.lectura() as con:
            filas = con.execute("SELECT agente, severidad, probabilidad, latencia_ms, tipo, motivo, ts FROM eventos"
                                " WHERE factura_id = ? ORDER BY id", (factura_id,)).fetchall()
        with self._candado:
            etapas = [p.etapa for p in self._progreso.values() if p.factura_id == factura_id]
        if not filas:
            if not etapas and self._ultima(factura_id) is None:
                raise NoEncontrado(factura_id)
            return {"factura_id": factura_id, "estado": "procesando", "etapa": etapas[-1] if etapas else None,
                    "eventos": []}
        return {"factura_id": factura_id, "estado": "listo", "etapa": "decidido",
                "eventos": [{"agente": a, "severidad": s, "probabilidad": p, "latencia_ms": ms, "tipo": t,
                             "motivo": (m or "")[:200], "ts": ts} for a, s, p, ms, t, m, ts in filas]}

    def evidencia(self, factura_id: str, completa: bool) -> dict[str, Any]:
        try:
            paquete = self.motor.paquete_evidencia(factura_id)          # ya saneado por el cerebro
        except LookupError:
            raise NoEncontrado(factura_id) from None
        if completa:
            return {"acceso": "operador", **paquete}
        final = Decision.model_validate(paquete["decision_final"])
        factura = paquete["factura"]
        return {
            "acceso": "publico",
            "factura_id": factura_id,
            "origen": self._fuentes.get(factura_id, origen_de(factura.get("archivo", ""))),
            "advertencia": paquete["advertencia"],
            "decision": self._publica(final),
            "regla_principal": self._regla_principal(final),
            "factura": {k: factura.get(k) for k in ("proveedor", "numero_factura", "fecha_emision", "moneda",
                                                    "subtotal", "impuestos", "total", "referencia_contrato")}
            | {"cuenta_enmascarada": factura.get("cuenta_bancaria") or "",
               "lineas": factura.get("lineas", [])},
            "documento": {"sha256_esperado": paquete["documento_original"]["sha256_esperado"],
                          "coincide": paquete["documento_original"]["coincide"]},
            "cadena": {"integra": paquete["cadena"]["integra"], "firmada": paquete["cadena"]["firmada"]},
            "historial": [{"decision": x["decision"]["decision"], "estado": x["decision"]["estado"],
                           "codigo_principal": codigo_seguro(x["decision"].get("codigo_principal", "OK")),
                           "aprobado": x["decision"].get("aprobado"), "ts": x["decision"]["ts"]}
                          for x in paquete["decisiones"]],
        }

    def reglas(self) -> dict[str, Any]:
        r = self.motor._reglas_actuales()
        usd = lambda c: f"{c / 100:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")  # noqa: E731
        return {
            "version": r.version, "empresa": r.empresa, "solo_lectura": True,
            "limites": {"limite_pago_usd": usd(r.limite_pago_cents), "tope_duro_usd": usd(r.tope_duro_cents),
                        "limite_mensual_proveedor_usd": usd(r.limite_mes_proveedor_cents),
                        "limite_mensual_global_usd": usd(r.limite_mes_global_cents),
                        "saldo_inicial_mes_usd": usd(r.saldo_inicial_mes_cents),
                        "tolerancia_contrato": str(r.tolerancia_contrato), "tolerancia_fx": str(r.tolerancia_fx)},
            "en_palabras": [
                f"Se paga solo si el proveedor está aprobado, la cuenta coincide con la registrada y el monto es "
                f"≤ USD {usd(r.limite_pago_cents)}.",
                f"Entre USD {usd(r.limite_pago_cents)} y USD {usd(r.tope_duro_cents)}: decide una persona.",
                f"Por encima de USD {usd(r.tope_duro_cents)}: se frena siempre, ni con aprobación.",
                "Cuenta no registrada o proveedor no dado de alta: se frena; ni un humano puede aprobarlo.",
                "Texto oculto o instrucciones al sistema dentro de la factura: se frena.",
            ],
            "proveedores": [{"nombre": p["nombre"], "pais": p.get("pais"), "permitido": bool(p.get("permitido")),
                             "bloqueado": bool(p.get("bloqueado")),
                             "cuenta_enmascarada": enmascarar(str(p.get("cuenta_registrada") or ""))}
                            for p in self.motor.catalogo.proveedores],
        }

    def politica(self, factura_id: str, cambios: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.motor.simular_politica(factura_id, cambios)
        except LookupError:
            raise NoEncontrado(factura_id) from None

    def salud(self) -> dict[str, Any]:
        integra, _ = self.motor.verificar_cadena()
        return {"estado": "ok", "version": VERSION, "revision_dev3": "pendiente",
                "cadena_integra": integra, "capa_semantica": self.motor.modo_semantico,
                "modo_extraccion": "LIVE autorizado" if self.ajustes.extraccion_live else "solo caché (sin modelos)",
                "modo_falsificar": ("LIVE: el agente lee cada factura falsificada"
                                    if self.ajustes.extraccion_live or self._extractores
                                    else "sin extracción: activa ATTACK_LAB_EXTRACCION_LIVE=1 (todo escalará)")}

    def verificar(self) -> dict[str, Any]:
        integra, fila = self.motor.verificar_cadena()
        return {"integra": integra, "fila_rota": fila, "pagos_integros": not self.motor.verificar_pagos()}

    # ---------- operador ----------

    async def resolver(self, factura_id: str, aprobado: bool, identidad: str, clave: str | None) -> dict[str, Any]:
        ultima = self._ultima(factura_id)
        if ultima is None:
            raise NoEncontrado(factura_id)
        if aprobado and ultima.estado == "pendiente_humano" and not ultima.aprobable:
            # Doble control: la API no ofrece aprobar lo no aprobable y el cerebro lo vuelve a impedir.
            raise NoAprobable("La decisión no es aprobable: primero hay que volver a evaluarla",
                              codigo_seguro(ultima.codigo_principal), ultima.accion_requerida)
        async with self._escritura:
            d = await self.motor.reanudar_async(factura_id, aprobado, identidad,
                                                clave_idempotencia=f"{identidad}:{clave}" if clave else None)
        return self._publica(d)

    async def reevaluar(self, factura_id: str) -> dict[str, Any]:
        async with self._escritura:
            try:
                d = await self.motor.reevaluar_async(factura_id)
            except LookupError:
                raise NoEncontrado(factura_id) from None
        return self._publica(d)

    async def reiniciar(self, admin: str) -> dict[str, Any]:
        async with self._escritura:
            resumen = await asyncio.to_thread(self.motor.reiniciar_demo, admin)
        with self._candado:
            self._progreso.clear()
            self._fuentes.clear()
        return {k: resumen[k] for k in ("reiniciado_por", "ts", "decisiones", "pagos_historicos", "pagos_simulados",
                                        "saldo_inicial_usd", "cadena_integra")}

    # ---------- métricas (MOCK y CACHÉ; LIVE nunca desde la API) ----------

    def metricas(self, modo: str) -> dict[str, Any]:
        from cerebro.medir import medir

        if modo not in ("mock", "cache"):
            raise ValueError("Desde la API solo se miden los modos mock y cache (LIVE cuesta dinero).")
        en_cache = self._metricas.get(modo)
        if en_cache and time.time() - en_cache[0] < 600:
            return en_cache[1]
        resultado = medir(modo).model_dump(mode="json")
        resultado["facturas"] = [{k: f[k] for k in ("numero", "esperado", "obtenido", "correcto", "falso_pagar",
                                                    "autonoma", "estado", "codigo_principal", "codigo_esperado",
                                                    "aprobable", "fuente", "jurado")} for f in resultado["facturas"]]
        self._metricas[modo] = (time.time(), resultado)
        return resultado
