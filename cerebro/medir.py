"""Medición del cerebro contra el ground truth v2 → resultados.json (contrato estable para Dev 3).

Por defecto compara con cerebro/ground_truth_v2.csv (matriz v2 del aviso: 09 y 10 FRENAR). El v1 de
Dev 1 (datos/ground_truth.csv) sigue disponible con --ground-truth v1 mientras se coordina su cambio.

    uv run python -m cerebro.medir                       # MOCK: JSON canónicos, sin extracción
    uv run python -m cerebro.medir --modo cache          # CACHÉ: originales → extraer() solo desde cache/
    uv run python -m cerebro.medir --modo live --confirmar-costo   # LIVE: modelos reales (cuesta dinero)

Cada corrida usa una base y una clave de firma NUEVAS en un directorio temporal: no toca
blinka.db y es reproducible. El código de salida es 1 si hubo algún PAGAR indebido.
Nunca se reporta costo 0 si no se midió: queda en null con el motivo.
"""

from __future__ import annotations

import argparse
import csv
import os
import statistics
import sys
import tempfile
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from cerebro import Cerebro
from cerebro.config import RAIZ
from cerebro.evidencia import responsable
from cerebro.firma import Firmante
from schemas import FacturaCanonica

VERSION_CONTRATO = "1.0"
ETIQUETAS = ["PAGAR", "ESCALAR", "FRENAR"]
GROUND_TRUTH = {
    "v2": lambda raiz: raiz / "cerebro" / "ground_truth_v2.csv",
    "v1": lambda raiz: raiz / "datos" / "ground_truth.csv",
}
Modo = Literal["MOCK", "CACHÉ", "LIVE"]
_ALIAS: dict[str, Modo] = {"mock": "MOCK", "cache": "CACHÉ", "caché": "CACHÉ", "live": "LIVE"}
DESCRIPCION = {
    "MOCK": "MOCK: los 15 JSON canónicos escritos a mano (datos/facturas_json) entran directo al cerebro; "
            "no hay extracción ni llamadas a modelos.",
    "CACHÉ": "CACHÉ: los 15 documentos originales pasan por extraer() con las respuestas grabadas en cache/; "
             "ningún modelo se llama (un fallo de caché se marca como cache_miss y escala).",
    "LIVE": "LIVE: extracción con los modelos reales configurados en el entorno.",
}
MOTIVO_COSTO = {
    "MOCK": "MOCK: sin llamadas a modelos; el costo de producción no se midió (no es 0).",
    "CACHÉ": "CACHÉ: la extracción sale de cache/; el costo de las llamadas originales no se registró.",
    "LIVE": "LIVE: los extractores no reportan tokens ni costo; no medido.",
}


# ---------- contrato de resultados.json ----------

class Matriz(BaseModel):
    etiquetas: list[str]
    filas: dict[str, dict[str, int]]          # esperado → obtenido → cantidad


class LatenciaEtapa(BaseModel):
    n: int
    promedio_ms: float
    p50_ms: float
    max_ms: int


class Costo(BaseModel):
    medido: bool
    usd_total: float | None
    usd_por_factura: float | None
    motivo: str
    semantica_usd: float | None = None       # usage.cost real de la capa semántica (Jev), si corrió
    semantica_llamadas: int | None = None


class Integridad(BaseModel):
    cadena_integra: bool
    fila_rota: int | None
    firmada: bool
    pagos_integros: bool
    problemas_pagos: list[str]


class Resumen(BaseModel):
    total: int
    aciertos: int
    exactitud: float
    falsos_pagar: int
    autonomas: int
    autonomia: float                          # correctas y finales sin humano / total
    pendientes_humano: int
    jurado_aciertos: int
    jurado_total: int
    codigos_aciertos: int | None = None       # v2: código principal igual al esperado


class FacturaMedida(BaseModel):
    numero: str
    archivo: str
    jurado: bool
    esperado: str
    obtenido: str
    correcto: bool
    falso_pagar: bool
    autonoma: bool
    estado: str
    explicacion: str
    contrafactual: str | None
    responsable: dict[str, Any]
    fuente: Literal["json", "cache", "cache_miss", "live"]
    factura_id: str
    latencia_ms: dict[str, int]
    codigo_principal: str = "OK"
    codigo_esperado: str | None = None
    aprobable: bool = False


class Resultados(BaseModel):
    version_contrato: str
    generado: datetime
    modo: Modo
    descripcion_modo: str
    capa_semantica: str
    capa_semantica_nombre: str | None = None
    ref_date: date
    version_reglas: str
    ground_truth: str = "v2"
    resumen: Resumen
    matriz: Matriz
    latencia: dict[str, LatenciaEtapa]
    costo: Costo
    integridad: Integridad
    facturas: list[FacturaMedida]


# ---------- extracción en modo CACHÉ ----------

class _SoloCache:
    """Extractor que nunca llama a un modelo: si la caché no tiene la respuesta, falla y se anota."""

    def __init__(self, nombre: str) -> None:
        self.nombre = nombre
        self.llamadas = 0

    def __call__(self, doc: Any) -> Any:
        self.llamadas += 1
        raise RuntimeError(f"{self.nombre}: sin respuesta en cache/ (modo CACHÉ no llama a modelos)")


def _extraer_cache(raiz: Path, archivo: str, canal: str) -> tuple[FacturaCanonica, bool]:
    from extraccion import extraer
    from extraccion.cache import CacheExtracciones
    from extraccion.extractor_b import MODELO as MODELO_B
    from extraccion.extractor_openai import MODELO_POR_DEFECTO as MODELO_A

    class _CacheSoloLectura(CacheExtracciones):
        def escribir(self, *args: Any, **kwargs: Any) -> None:
            return None

    a = _SoloCache(f"A:{os.environ.get('OPENAI_MODEL') or MODELO_A}")
    b = _SoloCache(f"B:{MODELO_B}")
    factura = extraer(raiz / archivo, canal, extractor_a=a, extractor_b=b,
                      cache=_CacheSoloLectura(raiz / "cache"), timeout_s=30)
    return factura, bool(a.llamadas or b.llamadas)


# ---------- medición ----------

def _modo(valor: str) -> Modo:
    if valor in ("MOCK", "CACHÉ", "LIVE"):
        return valor  # type: ignore[return-value]
    modo = _ALIAS.get(valor.strip().lower())
    if modo is None:
        raise ValueError(f"Modo desconocido: {valor!r} (mock, cache o live)")
    return modo


def _latencias(trazas: list[dict[str, int]]) -> dict[str, LatenciaEtapa]:
    etapas: dict[str, list[int]] = {}
    for traza in trazas:
        for etapa, ms in traza.items():
            etapas.setdefault(etapa, []).append(ms)
    return {etapa: LatenciaEtapa(n=len(v), promedio_ms=round(statistics.fmean(v), 1),
                                 p50_ms=float(statistics.median(v)), max_ms=max(v))
            for etapa, v in sorted(etapas.items())}


def _costo(modo: Modo, capa: Any) -> Costo:
    """El costo total solo se da si TODO se midió; la extracción nunca informa costo, así que queda null."""
    llamadas = getattr(capa, "llamadas", None)
    semantica = getattr(capa, "costo_usd", None)
    motivo = MOTIVO_COSTO[modo]
    if llamadas:
        detalle = f"USD {semantica:.6f}" if semantica is not None else "sin costo informado"
        motivo += f" Capa semántica {capa.nombre}: {llamadas} llamadas, {detalle} (usage.cost de OpenRouter)."
    return Costo(medido=False, usd_total=None, usd_por_factura=None, motivo=motivo,
                 semantica_usd=semantica if llamadas else None, semantica_llamadas=llamadas if llamadas else None)


def medir(modo: str = "MOCK", *, directorio: Path | None = None, raiz: Path = RAIZ, confirmar_costo: bool = False,
          capa: Any = None, ground_truth: str = "v2") -> Resultados:
    if ground_truth not in GROUND_TRUTH:
        raise ValueError(f"ground_truth desconocido: {ground_truth!r} (v2 o v1)")
    modo_norm = _modo(modo)
    if capa is not None and getattr(capa, "modo", "") == "live" and not confirmar_costo:
        raise PermissionError("La capa semántica en vivo (Jev) consume créditos: confirme con --confirmar-costo")
    if modo_norm == "LIVE":
        if not confirmar_costo:
            raise PermissionError("El modo LIVE llama a modelos de pago: confirme con --confirmar-costo")
        if os.environ.get("DEMO_CACHE") == "1":
            raise ValueError("DEMO_CACHE=1 haría que LIVE responda desde caché: desactívelo para medir en vivo")
    directorio = Path(directorio or tempfile.mkdtemp(prefix="cerebro-medir-"))
    directorio.mkdir(parents=True, exist_ok=True)
    firmante = Firmante.desde_archivo(directorio / "firma_medicion.pem")
    cerebro = Cerebro(db_path=directorio / "medicion.db", datos=raiz / "datos", reglas_path=raiz / "reglas.yaml",
                      firmante=firmante, capa=capa)

    archivo_esperado = GROUND_TRUTH[ground_truth](raiz)
    with archivo_esperado.open(encoding="utf-8", newline="") as archivo_gt:
        filas = sorted(csv.DictReader(archivo_gt), key=lambda f: Path(f["archivo"]).name)

    facturas: list[FacturaMedida] = []
    trazas: list[dict[str, int]] = []
    for fila in filas:
        numero = Path(fila["archivo"]).name[:2]
        canon = FacturaCanonica.model_validate_json(
            (raiz / "datos" / "facturas_json" / f"{numero}.json").read_text(encoding="utf-8"))
        traza: dict[str, int] = {}
        fuente: Literal["json", "cache", "cache_miss", "live"] = "json"
        factura = canon
        if modo_norm != "MOCK":
            inicio = time.perf_counter()
            if modo_norm == "CACHÉ":
                factura, fallo_cache = _extraer_cache(raiz, fila["archivo"], fila["canal"])
                fuente = "cache_miss" if fallo_cache else "cache"
            else:
                from extraccion import extraer
                factura, fuente = extraer(raiz / fila["archivo"], fila["canal"]), "live"
            traza["extraccion_ms"] = int((time.perf_counter() - inicio) * 1000)
        decision, traza_cerebro = cerebro.decidir_con_traza(factura)
        traza.update(traza_cerebro)
        trazas.append(traza)
        esperado = fila["decision_esperada"]
        correcto = decision.decision == esperado
        facturas.append(FacturaMedida(
            numero=numero, archivo=fila["archivo"], jurado=fila.get("jurado") == "1", esperado=esperado,
            obtenido=decision.decision, correcto=correcto,
            falso_pagar=decision.decision == "PAGAR" and esperado != "PAGAR",
            autonoma=correcto and decision.estado == "final" and decision.aprobador is None,
            estado=decision.estado, explicacion=decision.explicacion, contrafactual=decision.contrafactual,
            responsable=responsable(decision), fuente=fuente, factura_id=decision.factura_id, latencia_ms=traza,
            codigo_principal=decision.codigo_principal, codigo_esperado=fila.get("codigo_esperado") or None,
            aprobable=decision.aprobable,
        ))

    matriz = {e: dict.fromkeys(ETIQUETAS, 0) for e in ETIQUETAS}
    for f in facturas:
        matriz[f.esperado][f.obtenido] += 1
    total = len(facturas)
    aciertos = sum(f.correcto for f in facturas)
    autonomas = sum(f.autonoma for f in facturas)
    jurado = [f for f in facturas if f.jurado]
    integra, fila_rota = cerebro.verificar_cadena()
    problemas = cerebro.verificar_pagos()
    return Resultados(
        version_contrato=VERSION_CONTRATO, generado=datetime.now(UTC), modo=modo_norm,
        descripcion_modo=DESCRIPCION[modo_norm], capa_semantica=cerebro.modo_semantico,
        capa_semantica_nombre=getattr(capa, "nombre", None), ref_date=cerebro.ref_date,
        version_reglas=cerebro.reglas.version, ground_truth=ground_truth,
        resumen=Resumen(total=total, aciertos=aciertos, exactitud=round(aciertos / total, 4) if total else 0.0,
                        falsos_pagar=sum(f.falso_pagar for f in facturas), autonomas=autonomas,
                        autonomia=round(autonomas / total, 4) if total else 0.0,
                        pendientes_humano=sum(f.estado == "pendiente_humano" for f in facturas),
                        jurado_aciertos=sum(f.correcto for f in jurado), jurado_total=len(jurado),
                        codigos_aciertos=sum(f.codigo_principal == f.codigo_esperado for f in facturas)
                        if all(f.codigo_esperado for f in facturas) else None),
        matriz=Matriz(etiquetas=ETIQUETAS, filas=matriz),
        latencia=_latencias(trazas),
        costo=_costo(modo_norm, capa),
        integridad=Integridad(cadena_integra=integra, fila_rota=fila_rota, firmada=True,
                              pagos_integros=not problemas, problemas_pagos=problemas),
        facturas=facturas,
    )


def _imprimir(r: Resultados) -> None:
    print(f"Modo {r.modo} · capa semántica: {r.capa_semantica} · reglas {r.version_reglas[:12]} · "
          f"REF_DATE {r.ref_date}")
    print(r.descripcion_modo)
    for f in r.facturas:
        marca = "OK " if f.correcto else "MAL"
        print(f"  {f.numero} {f.esperado:<7} → {f.obtenido:<7} {marca} {'auto ' if f.autonoma else 'humano'} "
              f"[{f.fuente}] {f.explicacion[:110]}")
    s = r.resumen
    print(f"Pagos indebidos: {s.falsos_pagar}")
    print(f"Exactitud: {s.aciertos}/{s.total} · Autonomía: {s.autonomia:.0%} ({s.autonomas}/{s.total}) · "
          f"Paquete del jurado: {s.jurado_aciertos}/{s.jurado_total}")
    print(f"Latencia total p50: {r.latencia['total_ms'].p50_ms:.0f} ms · Costo: no medido ({r.costo.motivo})")
    print(f"Cadena íntegra: {r.integridad.cadena_integra} · Pagos íntegros: {r.integridad.pagos_integros}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m cerebro.medir", description=__doc__.splitlines()[0])
    parser.add_argument("--modo", default="mock", help="mock (por defecto), cache o live")
    parser.add_argument("--salida", default="resultados.json", help="ruta del resultados.json")
    parser.add_argument("--confirmar-costo", action="store_true",
                        help="requerido para --modo live y para --semantica jev")
    parser.add_argument("--ground-truth", default="v2", choices=sorted(GROUND_TRUTH),
                        help="v2 (por defecto, matriz del aviso) o v1 (datos/ground_truth.csv de Dev 1)")
    parser.add_argument("--semantica", default="ninguna", choices=["ninguna", "jev"],
                        help="capa semántica: ninguna (determinista) o jev (typesafe/jev-1.13 vía OpenRouter)")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    capa = None
    if args.semantica == "jev":
        from cerebro.semantica import CapaNoDisponible, capa_jev_desde_entorno

        capa = capa_jev_desde_entorno()
        if isinstance(capa, CapaNoDisponible):
            print(f"No se puede usar la capa semántica: {capa.motivo}")
            return 2
        if not args.confirmar_costo:
            print("--semantica jev consume créditos de OpenRouter: agregue --confirmar-costo para ejecutarlo.")
            return 2
    resultados = medir(args.modo, confirmar_costo=args.confirmar_costo, capa=capa, ground_truth=args.ground_truth)
    Path(args.salida).write_bytes(resultados.model_dump_json(indent=2).encode("utf-8") + b"\n")  # LF siempre
    _imprimir(resultados)
    print(f"Escrito {args.salida}")
    return 1 if resultados.resumen.falsos_pagar else 0


if __name__ == "__main__":
    raise SystemExit(main())
