"""Estética fintech/seguridad: fondo profundo, verde lima sobrio, alta legibilidad y contraste.

Todo HTML propio se arma SOLO con valores de lista blanca o escapados con html.escape: el texto que
viene del jurado o de la API nunca se inserta como HTML.
"""

from __future__ import annotations

import base64
import html

import streamlit as st

CSS = """
<style>
:root { --fondo:#0A0F1C; --tarjeta:#111A2C; --borde:#22304A; --texto:#E8EEF7; --suave:#9AA8BD;
        --lima:#A3E635; --ambar:#FBBF24; --rojo:#F87171; --verde:#4ADE80; }
.stApp { background: radial-gradient(1200px 600px at 10% -10%, #14203A 0%, var(--fondo) 55%); color: var(--texto); }
html, body, [class*="css"] { font-size: 17px; }
h1, h2, h3 { letter-spacing: -0.01em; }
h1 { font-size: 2.2rem !important; }
.al-hero { border:1px solid var(--borde); border-radius:18px; padding:22px 24px; margin-bottom:14px;
           background: linear-gradient(135deg, rgba(163,230,53,0.08), rgba(17,26,44,0.9)); }
.al-hero h1 { margin:0 0 6px 0; }
.al-hero p { color: var(--suave); margin:0; font-size:1.05rem; }
.al-chip { display:inline-block; padding:4px 10px; border-radius:999px; font-size:.78rem; font-weight:600;
           letter-spacing:.02em; border:1px solid var(--borde); color:var(--lima); background:rgba(163,230,53,.08); }
.al-sello { border-radius:16px; padding:18px 20px; margin:10px 0; border:1px solid var(--borde); }
.al-sello .d { font-size:2.1rem; font-weight:800; letter-spacing:.02em; }
.al-sello .c { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:1rem; opacity:.9; }
.al-PAGAR { background:rgba(74,222,128,.10); border-color:rgba(74,222,128,.45); }
.al-PAGAR .d { color: var(--verde); }
.al-ESCALAR { background:rgba(251,191,36,.10); border-color:rgba(251,191,36,.45); }
.al-ESCALAR .d { color: var(--ambar); }
.al-FRENAR { background:rgba(248,113,113,.10); border-color:rgba(248,113,113,.45); }
.al-FRENAR .d { color: var(--rojo); }
.al-agente { border:1px solid var(--borde); border-radius:14px; padding:14px; background:var(--tarjeta);
             min-height:120px; }
.al-agente .t { font-weight:700; font-size:1.02rem; }
.al-agente .s { font-size:.95rem; margin-top:6px; }
.al-s0 { border-color: rgba(74,222,128,.5); } .al-s1 { border-color: rgba(251,191,36,.6); }
.al-s2 { border-color: rgba(248,113,113,.7); } .al-sp { opacity:.65; }
div.stButton > button, div.stFormSubmitButton > button { border-radius:12px; font-weight:700; }
div.stFormSubmitButton > button { background: var(--lima); color:#0A0F1C; border:none; }
@media (max-width: 640px) { h1 { font-size:1.7rem !important; } .al-sello .d { font-size:1.7rem; } }
</style>
"""

DECISIONES = {"PAGAR": "PAGAR · autorización simulada", "ESCALAR": "ESCALAR · decide una persona",
              "FRENAR": "FRENAR"}
CODIGOS = {
    "OK": "En regla", "TOPE_DURO": "Supera el tope duro", "LIMITE_PAGO": "Supera el límite por pago",
    "LIMITE_MES": "Supera el límite mensual", "SALDO": "Saldo insuficiente",
    "CUENTA_NO_REGISTRADA": "Cuenta bancaria no registrada", "PROVEEDOR_NO_PERMITIDO": "Proveedor no dado de alta",
    "PROVEEDOR_BLOQUEADO": "Proveedor bloqueado", "CONTRATO": "No cuadra con el contrato",
    "DUPLICADO_EXACTO": "Factura ya pagada", "DUPLICADO_DIFUSO": "Posible duplicado",
    "INYECCION": "Instrucciones al sistema", "TEXTO_OCULTO": "Texto oculto",
    "EXTRACCION": "Lectura no confiable", "ERROR_TECNICO": "Error técnico: se revalida",
}
AGENTES = {"duplicados": "Duplicados", "contrato": "Contrato", "beneficiario": "Beneficiario / cuenta",
           "seguridad": "Seguridad", "presupuesto": "Presupuesto / FX"}


def aplicar() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def etiqueta_codigo(codigo: str) -> str:
    return CODIGOS.get(codigo, "Código no reconocido")


def hero(titulo: str, subtitulo: str) -> None:
    st.markdown(f'<div class="al-hero"><h1>{html.escape(titulo)}</h1><p>{html.escape(subtitulo)}</p></div>',
                unsafe_allow_html=True)


def chip(texto: str) -> None:
    st.markdown(f'<span class="al-chip">{html.escape(texto)}</span>', unsafe_allow_html=True)


def sello(decision: str, codigo: str) -> None:
    if decision not in DECISIONES:                     # nunca se muestra algo fuera de la lista blanca
        decision, codigo = "FRENAR", "ERROR_TECNICO"
    st.markdown(
        f'<div class="al-sello al-{decision}"><div class="d">{html.escape(DECISIONES[decision])}</div>'
        f'<div class="c">{html.escape(codigo if codigo in CODIGOS else "ERROR_TECNICO")} · '
        f'{html.escape(etiqueta_codigo(codigo))}</div></div>', unsafe_allow_html=True)


def tarjeta_agente(nombre: str, evento: dict | None) -> None:
    titulo = AGENTES.get(nombre, nombre)
    if evento is None:
        cuerpo, clase = "procesando…", "al-sp"
    else:
        sev = int(evento.get("severidad", 0))
        tipo = {"riesgo": "riesgo", "fallo_tecnico": "fallo técnico", "sin_evidencia": "sin evidencia",
                "sin_hallazgos": "sin hallazgos"}.get(evento.get("tipo", ""), "—")
        estado = {0: "✓ sin objeciones", 1: "● escalar", 2: "■ frenar"}.get(sev, "—")
        extra = f" · p={float(evento['probabilidad']):.2f}" if evento.get("probabilidad") is not None else ""
        cuerpo = f"{estado} · {tipo} · {int(evento.get('latencia_ms', 0))} ms{extra}"
        clase = f"al-s{sev if sev in (0, 1, 2) else 1}"
    st.markdown(f'<div class="al-agente {clase}"><div class="t">{html.escape(titulo)}</div>'
                f'<div class="s">{html.escape(cuerpo)}</div></div>', unsafe_allow_html=True)


def monto(valor: float, moneda: str) -> str:
    texto = f"{valor:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{moneda} {texto}"


def imagen_png(datos: bytes, alt: str) -> None:
    """PNG con texto alternativo (st.image no admite alt). El alt se escapa: lo arma el servidor."""
    codificada = base64.b64encode(datos).decode("ascii")
    st.markdown(f'<img src="data:image/png;base64,{codificada}" alt="{html.escape(alt, quote=True)}" '
                f'style="width:100%;border-radius:12px">', unsafe_allow_html=True)
