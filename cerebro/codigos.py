"""Códigos estables v2 (AVISO_DEV2_cambios.md). La pantalla grande usa SOLO estos, nunca texto libre.

Los asigna el código del cerebro en el momento de crear cada Hallazgo. Nunca se derivan del
texto de una factura ni de la respuesta de un modelo: un código desconocido, vacío u "OK" en
un hallazgo se reemplaza por uno inferido de campos estructurados (agente, severidad, tipo).

Código principal = el del hallazgo de mayor severidad; empate → el primero en PRIORIDAD.
"""

from __future__ import annotations

from schemas import Hallazgo

CODIGOS = ("OK", "TOPE_DURO", "LIMITE_PAGO", "LIMITE_MES", "SALDO", "CUENTA_NO_REGISTRADA",
           "PROVEEDOR_NO_PERMITIDO", "PROVEEDOR_BLOQUEADO", "CONTRATO", "DUPLICADO_EXACTO",
           "DUPLICADO_DIFUSO", "INYECCION", "TEXTO_OCULTO", "EXTRACCION", "ERROR_TECNICO")

# Desempate entre hallazgos de igual severidad (el primero gana): señales de fraude, luego datos
# no confiables (que invalidan lo demás), identidad del beneficiario, dinero y, al final, lo aprobable.
PRIORIDAD = ("TEXTO_OCULTO", "INYECCION", "ERROR_TECNICO", "EXTRACCION", "PROVEEDOR_BLOQUEADO",
             "CUENTA_NO_REGISTRADA", "PROVEEDOR_NO_PERMITIDO", "DUPLICADO_EXACTO", "TOPE_DURO", "LIMITE_MES",
             "SALDO", "DUPLICADO_DIFUSO", "CONTRATO", "LIMITE_PAGO")
_ORDEN = {codigo: i for i, codigo in enumerate(PRIORIDAD)}

# Bloquean cualquier aprobación aunque la decisión sea ESCALAR: primero hay que recuperar evidencia
# confiable y volver a evaluar. (Más estricto que el aviso v2, que los marca aprobables.)
NO_APROBABLES = frozenset({"EXTRACCION", "ERROR_TECNICO"})

ACCIONES = {
    "CUENTA_NO_REGISTRADA": ("Verificar por teléfono con el contacto conocido del proveedor y actualizar el "
                             "maestro de proveedores."),
    "PROVEEDOR_NO_PERMITIDO": "Dar de alta al proveedor (contrato + cuenta verificada) antes de pagar.",
    "EXTRACCION": "Reenviar un documento legible y volver a evaluar: no se aprueba con datos no verificados.",
    "ERROR_TECNICO": "Volver a evaluar cuando el servicio se recupere (cerebro.reevaluar): no se aprueba sin "
                     "una validación completa.",
}

POR_REGLA = {
    "tope_duro": "TOPE_DURO", "limite_pago": "LIMITE_PAGO", "mensual_proveedor": "LIMITE_MES",
    "mensual_global": "LIMITE_MES", "saldo": "SALDO", "cuenta": "CUENTA_NO_REGISTRADA",
    "beneficiario_no_permitido": "PROVEEDOR_NO_PERMITIDO", "beneficiario_bloqueado": "PROVEEDOR_BLOQUEADO",
    "extraccion": "EXTRACCION", "datos": "EXTRACCION", "fx": "ERROR_TECNICO",
}


def inferir(h: Hallazgo) -> str:
    """Código a partir de campos estructurados (nunca del texto del motivo ni de la evidencia)."""
    from cerebro.tipos import tipo_de

    tipo = tipo_de(h)
    if tipo == "fallo_tecnico":
        return "ERROR_TECNICO"
    if tipo == "sin_evidencia":
        return "EXTRACCION"
    if h.agente == "duplicados":
        return "DUPLICADO_EXACTO" if h.severidad == 2 else "DUPLICADO_DIFUSO"
    if h.agente in ("contrato", "presupuesto"):
        return "CONTRATO"
    if h.agente == "beneficiario":
        return "PROVEEDOR_NO_PERMITIDO" if h.campo == "id_fiscal" else "CUENTA_NO_REGISTRADA"
    if h.agente == "seguridad":
        return "TEXTO_OCULTO" if h.campo == "texto_oculto" else "INYECCION"
    return "ERROR_TECNICO"            # agente desconocido: se trata como algo que no se pudo verificar


def normalizar(h: Hallazgo) -> Hallazgo:
    if h.codigo in CODIGOS and h.codigo != "OK":
        return h
    return h.model_copy(update={"codigo": inferir(h)})


def clave_orden(h: Hallazgo) -> tuple[int, int]:
    return -h.severidad, _ORDEN.get(h.codigo, len(_ORDEN))
