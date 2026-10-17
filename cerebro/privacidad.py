"""Privacidad de identificadores bancarios (v2). Ninguna cuenta completa sale del cerebro.

- `enmascarar(cuenta)` → "****NNNN" (últimos 4 caracteres alfanuméricos). Dev 1 no tiene una
  utilidad equivalente; esta es la de referencia hasta coordinar una común.
- En el registro, la cuenta de la factura se guarda como TOKEN: "****NNNN#hmac:<32 hex>", con
  HMAC-SHA256 y un secreto aleatorio propio de cada base (tabla `metadatos`). Así `reanudar` y el
  sandbox pueden comparar contra la cuenta registrada sin guardar el número completo, y un token no
  revela la cuenta aunque se lea la base (no basta con probar números: hace falta el secreto).
- `enmascarar_texto` limpia texto libre, motivos y evidencias: cuentas conocidas (con cualquier
  separador), formato IBAN, formato de cuenta del set (XX-BANCO-NNNN) y secuencias de 10+ dígitos.
  No toca montos, números de factura ni hashes hexadecimales.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Iterable
from typing import Any

from cerebro.normalizar import clave
from schemas import Decision, FacturaCanonica, Hallazgo

MASCARA = "****"
_TOKEN = re.compile(r"\*{4}[A-Z0-9]{0,4}#hmac:([0-9a-f]{32})")
_PATRONES = (
    re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),            # IBAN
    re.compile(r"\b[A-Z]{2}-BANCO-\d{3,}\b", re.IGNORECASE),    # formato de cuenta del set ficticio
    re.compile(r"\b\d{10,}\b"),                                 # números de cuenta largos
)
_MIN_CUENTA = 5
# Para texto que controla quien envía la factura (texto libre, oculto, evidencia): cualquier token con
# guiones y 4+ dígitos seguidos, o letras pegadas a 4+ dígitos, se trata como posible cuenta. Más
# agresivo: también enmascara números de factura citados allí; nunca se aplica a motivos del cerebro.
_PATRONES_LIBRES = (
    re.compile(r"\b[A-Z0-9]+(?:-[A-Z0-9]+)*-[A-Z]*\d{4,}[A-Z0-9]*\b", re.IGNORECASE),
    re.compile(r"\b[A-Z]{2,}\d{4,}[A-Z0-9]*\b", re.IGNORECASE),
)


def enmascarar(cuenta: str | None) -> str:
    if not cuenta:
        return ""
    base = clave(cuenta)
    return MASCARA if len(base) <= 4 else MASCARA + base[-4:]


def huella(cuenta: str | None, secreto: bytes) -> str:
    return hmac.new(secreto, clave(cuenta).encode("ascii"), hashlib.sha256).hexdigest()[:32]


def token_cuenta(cuenta: str | None, secreto: bytes) -> str | None:
    if not cuenta:
        return None
    if es_token(cuenta):
        return cuenta
    return f"{enmascarar(cuenta)}#hmac:{huella(cuenta, secreto)}"


def es_token(valor: str | None) -> bool:
    return bool(valor) and _TOKEN.fullmatch(valor) is not None


def visible(cuenta: str | None) -> str | None:
    """Forma mostrable: la parte enmascarada de un token, o la máscara de una cuenta en claro."""
    if not cuenta:
        return cuenta
    return cuenta.split("#hmac:")[0] if es_token(cuenta) else enmascarar(cuenta)


def coincide(cuenta: str | None, registrada: str | None, secreto: bytes | None) -> bool:
    """¿La cuenta de la factura (en claro o token) es la registrada? Comparación en tiempo constante."""
    if not cuenta or not registrada or not clave(registrada):
        return False
    if es_token(cuenta):
        if secreto is None:
            return False
        digest = _TOKEN.fullmatch(cuenta).group(1)
        return hmac.compare_digest(digest, huella(registrada, secreto))
    return bool(clave(cuenta)) and hmac.compare_digest(clave(cuenta), clave(registrada))


def _patron_cuenta(cuenta: str) -> re.Pattern[str] | None:
    base = clave(cuenta)
    if len(base) < _MIN_CUENTA:
        return None
    return re.compile(r"[\s\-./]*".join(re.escape(c) for c in base), re.IGNORECASE)


def enmascarar_texto(texto: str | None, cuentas: Iterable[str | None] = ()) -> str:
    if not texto:
        return texto or ""
    salida = texto
    for cuenta in cuentas:
        if not cuenta or es_token(cuenta):
            continue
        patron = _patron_cuenta(cuenta)
        if patron is not None:
            salida = patron.sub(enmascarar(cuenta), salida)
    for patron in _PATRONES:
        salida = patron.sub(lambda m: enmascarar(m.group(0)), salida)
    return salida


def enmascarar_libre(texto: str | None, cuentas: Iterable[str | None] = ()) -> str:
    """Para texto aportado por quien envía la factura: enmascarar_texto + patrones de posible cuenta."""
    salida = enmascarar_texto(texto, cuentas)
    for patron in _PATRONES_LIBRES:
        salida = patron.sub(lambda m: enmascarar(m.group(0)), salida)
    return salida


def sanear_hallazgo(h: Hallazgo, cuentas: Iterable[str | None] = ()) -> Hallazgo:
    cuentas = list(cuentas)
    return h.model_copy(update={"motivo": enmascarar_texto(h.motivo, cuentas),
                                "evidencia": enmascarar_libre(h.evidencia, cuentas)})


def sanear_decision(d: Decision, cuentas: Iterable[str | None] = ()) -> Decision:
    cuentas = list(cuentas)
    return d.model_copy(update={
        "explicacion": enmascarar_texto(d.explicacion, cuentas),
        "contrafactual": enmascarar_texto(d.contrafactual, cuentas) if d.contrafactual else d.contrafactual,
        "hallazgos": [sanear_hallazgo(h, cuentas) for h in d.hallazgos],
    })


def proteger_factura(f: FacturaCanonica, secreto: bytes, cuentas: Iterable[str | None] = ()) -> FacturaCanonica:
    """Versión que se guarda en el registro: cuenta como token HMAC y textos sin cuentas completas."""
    cuentas = [f.cuenta_bancaria, *cuentas]
    return f.model_copy(update={
        "cuenta_bancaria": token_cuenta(f.cuenta_bancaria, secreto),
        "texto_libre": enmascarar_libre(f.texto_libre, cuentas),
        "texto_oculto": [enmascarar_libre(t, cuentas) for t in f.texto_oculto],
        "diferencias": [enmascarar_texto(t, cuentas) for t in f.diferencias],
        "lineas": [linea.model_copy(update={"descripcion": enmascarar_texto(linea.descripcion, cuentas)})
                   for linea in f.lineas],
    })


def sanear(valor: Any, cuentas: Iterable[str | None] = ()) -> Any:
    """Enmascara recursivamente todas las cadenas de una estructura (para paquetes descargables)."""
    cuentas = list(cuentas)
    if isinstance(valor, str):
        return visible(valor) if es_token(valor) else enmascarar_texto(valor, cuentas)
    if isinstance(valor, dict):
        return {k: sanear(v, cuentas) for k, v in valor.items()}
    if isinstance(valor, list):
        return [sanear(v, cuentas) for v in valor]
    return valor


CAMPOS_PUBLICOS = ("factura_id", "numero_factura", "proveedor", "decision", "estado", "codigo_principal",
                   "aprobable", "accion_requerida", "explicacion", "contrafactual", "cedar", "monto_original",
                   "moneda", "monto_usd", "fx_rate", "fx_source", "version_reglas", "aprobador", "aprobado", "ts",
                   "hash_prev", "hash")


def vista_publica(d: Decision, cuentas: Iterable[str | None] = ()) -> dict[str, Any]:
    """Lo que la UI y la pantalla del jurado pueden mostrar. Sin evidencia cruda ni cuentas completas.
    La pantalla grande debe usar `codigo_principal`, nunca texto de la factura."""
    d = sanear_decision(d, cuentas)
    datos = d.model_dump(mode="json")
    vista = {campo: datos[campo] for campo in CAMPOS_PUBLICOS}
    vista["hallazgos"] = [{"agente": h.agente, "severidad": h.severidad, "codigo": h.codigo, "motivo": h.motivo,
                           "probabilidad": h.probabilidad, "campo": h.campo} for h in d.hallazgos]
    return vista
