"""API FastAPI del Attack Lab. Arranque: uvicorn --factory app.api:crear_app --workers 1

UN solo proceso y un solo worker: es el único que abre DB_PATH y la clave de firma (SQLite con un
escritor). La UI de Streamlit habla con esta API por HTTP.

Autoría: Dev 2 (anticipo del alcance de Dev 3) · revisión de Dev 3 PENDIENTE.
"""


import asyncio
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Path, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from app import VERSION
from app.config import Ajustes, desde_entorno
from app.documentos import ArchivoInvalido
from app.falsificar import CasoFalsificado
from app.seguridad import Limitador, Operador, autenticar
from app.servicios import NoEncontrado, Servicio
from app.sintetico import ETIQUETA_MODO, PRESETS, CasoSintetico, preset
from cerebro import CadenaAlterada, NoAprobable, ReevaluacionNecesaria, ReinicioOcupado
from extraccion.render import CambiosInvalidos

FacturaId = Annotated[str, Path(pattern=r"^[A-Za-z0-9-]{8,80}$")]
BaseId = Annotated[str, Path(pattern=r"^base_\d{2}$")]
_MAX_JSON = 64 * 1024
_MAX_FALSIFICAR = 3 * 1024 * 1024          # admite un PNG de rayones de hasta 2 MB en base64
_MENSAJES_VALIDACION = {
    "extra_forbidden": "campo no permitido: este dato lo calcula el servidor",
    "missing": "falta este campo",
    "string_too_long": "texto demasiado largo",
    "string_too_short": "texto demasiado corto",
    "string_pattern_mismatch": "contiene caracteres no permitidos",
    "literal_error": "valor no permitido",
    "greater_than": "valor fuera de rango", "greater_than_equal": "valor fuera de rango",
    "less_than": "valor fuera de rango", "less_than_equal": "valor fuera de rango",
    "finite_number": "número inválido", "float_parsing": "número inválido", "date_from_datetime_parsing":
        "fecha inválida", "date_parsing": "fecha inválida", "too_short": "faltan elementos",
    "too_long": "demasiados elementos",
}


class Politica(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    factura_id: str = Field(pattern=r"^[A-Za-z0-9-]{8,80}$")
    cambios: dict[str, float] = Field(min_length=1, max_length=10)


def _error(status: int, tipo: str, mensaje: str, **extra: Any) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": tipo, "mensaje": mensaje, **extra})


def crear_app(servicio: Servicio | None = None, ajustes: Ajustes | None = None) -> FastAPI:
    ajustes = ajustes or (servicio.ajustes if servicio else desde_entorno())
    svc = servicio or Servicio(ajustes)
    limitador = Limitador()
    app = FastAPI(title="Attack Lab · Róbale a mi agente", version=VERSION, docs_url=None, redoc_url=None,
                  openapi_url=None)
    app.state.servicio = svc
    app.state.limitador = limitador
    app.add_middleware(CORSMiddleware, allow_origins=list(ajustes.origenes_cors), allow_credentials=False,
                       allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type",
                                                                     "Idempotency-Key"])

    @app.middleware("http")
    async def cabeceras_y_tamano(request: Request, call_next):  # noqa: ANN001, ANN202
        largo = request.headers.get("content-length")
        if largo is not None and not largo.isdigit():
            return _error(400, "solicitud_invalida", "Content-Length inválido.")
        maximo = _MAX_FALSIFICAR if request.url.path == "/falsificar" else _MAX_JSON
        if largo and request.url.path != "/ingest" and int(largo) > maximo:
            return _error(413, "demasiado_grande", "La solicitud es demasiado grande.")
        respuesta = await call_next(request)
        respuesta.headers["X-Content-Type-Options"] = "nosniff"
        respuesta.headers["X-Frame-Options"] = "DENY"
        respuesta.headers["Referrer-Policy"] = "no-referrer"
        respuesta.headers["Cache-Control"] = "no-store"
        respuesta.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        return respuesta

    # ---------- errores en español ----------

    @app.exception_handler(RequestValidationError)
    async def _validacion(request: Request, error: RequestValidationError) -> JSONResponse:
        detalle = [{"campo": ".".join(str(x) for x in e.get("loc", ()) if x != "body"),
                    "problema": _MENSAJES_VALIDACION.get(e.get("type", ""), "valor inválido")} for e in error.errors()]
        return _error(422, "datos_invalidos", "Revisa los datos: hay campos inválidos o no permitidos.",
                      detalle=detalle[:20])

    @app.exception_handler(NoAprobable)
    async def _no_aprobable(request: Request, error: NoAprobable) -> JSONResponse:
        return _error(409, "no_aprobable", "Esta decisión no admite aprobación humana.",
                      codigo=error.codigo, accion_requerida=error.accion_requerida)

    @app.exception_handler(ReevaluacionNecesaria)
    async def _reevaluar(request: Request, error: ReevaluacionNecesaria) -> JSONResponse:
        return _error(503, "reevaluacion_necesaria",
                      "No se puede aprobar todavía: hay que volver a evaluar la factura.")

    @app.exception_handler(CadenaAlterada)
    async def _cadena(request: Request, error: CadenaAlterada) -> JSONResponse:
        return _error(423, "registro_alterado", "El registro de decisiones fue alterado: no se aprueba nada.")

    @app.exception_handler(ReinicioOcupado)
    async def _ocupado(request: Request, error: ReinicioOcupado) -> JSONResponse:
        return _error(409, "reinicio_ocupado", "Hay solicitudes en curso; reintenta el reinicio en unos segundos.")

    @app.exception_handler(NoEncontrado)
    async def _no_encontrado(request: Request, error: NoEncontrado) -> JSONResponse:
        return _error(404, "no_encontrado", "No existe esa factura o intento.")

    @app.exception_handler(CambiosInvalidos)
    async def _cambios(request: Request, error: CambiosInvalidos) -> JSONResponse:
        # Mensajes propios de extraccion.render (nunca eco del texto del jurado).
        return _error(422, "datos_invalidos", str(error)[:200])

    @app.exception_handler(ArchivoInvalido)
    async def _archivo(request: Request, error: ArchivoInvalido) -> JSONResponse:
        return _error(error.status, "archivo_invalido", str(error))

    @app.exception_handler(PermissionError)
    async def _permiso(request: Request, error: PermissionError) -> JSONResponse:
        return _error(403, "sin_permiso", "Tu identidad no está autorizada para esta acción.")

    @app.exception_handler(ValueError)
    async def _valor(request: Request, error: ValueError) -> JSONResponse:
        return _error(409, "conflicto", "La operación no es válida en el estado actual de la factura.")

    # ---------- dependencias ----------

    def ip(request: Request) -> str:
        if ajustes.confiar_en_proxy and request.headers.get("x-forwarded-for"):
            return request.headers["x-forwarded-for"].split(",")[0].strip()[:64]
        return request.client.host if request.client else "desconocida"

    def cuota(clave: str, limite: int, ventana_s: float) -> None:
        if not limitador.permitir(clave, limite, ventana_s):
            raise HTTPException(429, detail="Demasiados intentos: espera un momento y vuelve a probar.")

    def operador_opcional(authorization: Annotated[str | None, Header()] = None) -> Operador | None:
        return autenticar(authorization, ajustes.tokens)

    def exigir(*roles: str):  # noqa: ANN202
        def dependencia(authorization: Annotated[str | None, Header()] = None) -> Operador:
            op = autenticar(authorization, ajustes.tokens)
            if op is None:
                raise HTTPException(401, detail="Falta un token de operador válido.")
            if op.rol not in roles:
                raise HTTPException(403, detail="Tu rol no permite esta acción.")
            return op
        return dependencia

    @app.exception_handler(HTTPException)
    async def _http(request: Request, error: HTTPException) -> JSONResponse:
        codigos = {401: "no_autenticado", 403: "sin_permiso", 429: "demasiados_intentos", 404: "no_encontrado"}
        return _error(error.status_code, codigos.get(error.status_code, "error"), str(error.detail))

    # ---------- públicos ----------

    @app.get("/health")
    def health() -> dict[str, Any]:
        return svc.salud()

    @app.get("/presets")
    def presets() -> dict[str, Any]:
        return {"etiqueta_modo": ETIQUETA_MODO, "presets": list(PRESETS)}

    @app.get("/presets/{nombre}")
    def un_preset(nombre: Literal["limpia", "cuenta_cambiada", "proveedor_nuevo", "monto_inflado", "duplicado",
                                  "instruccion_maliciosa"]) -> dict[str, Any]:
        return preset(nombre)

    @app.post("/simular")
    async def simular(caso: CasoSintetico, request: Request) -> dict[str, Any]:
        cuota(f"simular:ip:{ip(request)}", ajustes.simular_por_minuto_ip, 60)
        cuota(f"simular:sesion:{caso.sesion_id}", ajustes.simular_por_hora_sesion, 3600)
        return await svc.simular(caso)

    @app.post("/ingest")
    async def ingest(request: Request, archivo: Annotated[UploadFile, File()],
                     canal: Annotated[Literal["telegram", "web", "email", "chat"], Form()] = "web") -> dict[str, Any]:
        cuota(f"ingest:ip:{ip(request)}", ajustes.ingest_por_minuto_ip, 60)
        contenido = await archivo.read(ajustes.max_upload_bytes + 1)          # nunca más que el máximo + 1
        return await svc.ingest(archivo.filename, contenido, canal)

    # ---------- modo «factura falsificada» (plan v2): el agente lee el documento ----------

    @app.get("/falsificar/base")
    def base_aleatoria(request: Request) -> dict[str, Any]:
        cuota(f"lectura:ip:{ip(request)}", ajustes.lectura_por_minuto_ip, 60)
        return svc.base_aleatoria()

    @app.get("/falsificar/base/{base_id}/preview.png")
    async def preview(base_id: BaseId, request: Request) -> Response:
        cuota(f"lectura:ip:{ip(request)}", ajustes.lectura_por_minuto_ip, 60)
        return Response(content=await asyncio.to_thread(svc.preview, base_id), media_type="image/png")

    @app.post("/falsificar")
    async def falsificar(caso: CasoFalsificado, request: Request) -> dict[str, Any]:
        cuota("falsificar:global", ajustes.falsificar_por_minuto_global, 60)
        cuota(f"falsificar:ip:{ip(request)}", ajustes.falsificar_por_minuto_ip, 60)
        cuota(f"falsificar:sesion:{caso.sesion_id}", ajustes.falsificar_por_hora_sesion, 3600)
        return await svc.falsificar(caso)

    @app.get("/intentos/{intento_id}")
    def intento(intento_id: Annotated[str, Path(pattern=r"^[a-f0-9]{32}$")]) -> dict[str, Any]:
        return svc.progreso(intento_id)

    @app.get("/decisiones")
    def decisiones(request: Request, limite: Annotated[int, Query(ge=1, le=100)] = 30,
                   desplazamiento: Annotated[int, Query(ge=0, le=100_000)] = 0) -> dict[str, Any]:
        cuota(f"lectura:ip:{ip(request)}", ajustes.lectura_por_minuto_ip, 60)
        return svc.decisiones(limite, desplazamiento)

    @app.get("/eventos/{factura_id}")
    def eventos(factura_id: FacturaId) -> dict[str, Any]:
        return svc.eventos(factura_id)

    @app.get("/evidencia/{factura_id}")
    def evidencia(factura_id: FacturaId, op: Annotated[Operador | None, Depends(operador_opcional)]) -> dict[str, Any]:
        return svc.evidencia(factura_id, completa=op is not None)

    @app.get("/reglas")
    def reglas() -> dict[str, Any]:
        return svc.reglas()

    @app.post("/politica/simular")
    def politica(cuerpo: Politica, request: Request) -> dict[str, Any]:
        cuota(f"politica:ip:{ip(request)}", ajustes.politica_por_minuto_ip, 60)
        try:
            return svc.politica(cuerpo.factura_id, cuerpo.cambios)
        except NoEncontrado:
            raise
        except ValueError as error:
            raise HTTPException(400, detail=f"Cambio de política inválido: {str(error)[:120]}") from None

    @app.get("/metricas")
    async def metricas(modo: Annotated[Literal["mock", "cache"], Query()] = "mock") -> dict[str, Any]:
        return await asyncio.to_thread(svc.metricas, modo)

    @app.get("/verificar")
    def verificar() -> dict[str, Any]:
        return svc.verificar()

    # ---------- operadores (token en el servidor) ----------

    def _clave(idempotency_key: str | None) -> str | None:
        if idempotency_key is None:
            return None
        if not idempotency_key or len(idempotency_key) > 100 or not idempotency_key.replace("-", "").replace(
                "_", "").isalnum():
            raise HTTPException(400, detail="Idempotency-Key inválida.")
        return idempotency_key

    @app.post("/aprobar/{factura_id}")
    async def aprobar(factura_id: FacturaId, op: Annotated[Operador, Depends(exigir("aprobador"))],
                      idempotency_key: Annotated[str | None, Header()] = None) -> dict[str, Any]:
        return await svc.resolver(factura_id, True, op.identidad, _clave(idempotency_key))

    @app.post("/rechazar/{factura_id}")
    async def rechazar(factura_id: FacturaId, op: Annotated[Operador, Depends(exigir("aprobador"))],
                       idempotency_key: Annotated[str | None, Header()] = None) -> dict[str, Any]:
        return await svc.resolver(factura_id, False, op.identidad, _clave(idempotency_key))

    @app.post("/reevaluar/{factura_id}")
    async def reevaluar(factura_id: FacturaId,
                        op: Annotated[Operador, Depends(exigir("aprobador", "admin"))]) -> dict[str, Any]:
        return await svc.reevaluar(factura_id)

    @app.post("/paquete-jurado")
    async def paquete(op: Annotated[Operador, Depends(exigir("aprobador", "admin"))]) -> dict[str, Any]:
        cuota("paquete:global", ajustes.paquete_por_minuto, 60)
        return {"advertencia": "Plan B: las 6 facturas del paquete del jurado desde datos estructurados del set "
                               "ficticio (sin extracción ni red). No crea pagos ni duplica decisiones, pero el "
                               "resultado depende del saldo y los límites actuales: úsalo justo después de "
                               "reiniciar la demo para obtener la matriz del set.",
                "resultados": await svc.paquete_jurado()}

    @app.post("/admin/reiniciar-demo")
    async def reiniciar(op: Annotated[Operador, Depends(exigir("admin"))]) -> dict[str, Any]:
        limitador.reiniciar()
        return await svc.reiniciar(op.identidad)

    return app
