"""Sistema de diseño: estructura «Cyber Fintech × Trust Engine» con la piel «Mosaic Lite» oscura (la del video).

Tokens: fondo #111827, superficie #1f2937, elevada #374151, texto #f3f4f6, secundario #9ca3af. El violeta es solo
marca (#8b5cf6; botones #7c3aed, texto #a78bfa). Semántica fija: esmeralda = PAGAR, ámbar = ESCALAR, rojo = FRENAR.
Sello de goma (PAGADO / ESCALADO / FRENADO), números monoespaciados, radios 8/12, foco visible y sin animaciones si
el sistema pide movimiento reducido. Fuentes del sistema (Inter si está; si no, Segoe UI / system-ui).

Todo HTML propio se arma SOLO con valores de lista blanca o escapados con html.escape: el texto que
viene del jurado o de la API nunca se inserta como HTML.
"""

from __future__ import annotations

import base64
import html

import streamlit as st

CSS = """
<style>
:root { --fondo:#111827; --superficie:#1f2937; --elevada:#374151; --borde:rgba(75,85,99,.65); --texto:#f3f4f6;
        --suave:#9ca3af; --acento:#a78bfa; --acento-fondo:#7c3aed; --acento-hover:#6d28d9; --marca:#8b5cf6;
        --pagar:#34d399; --pagar-base:#10b981; --escalar:#fbbf24; --escalar-base:#f59e0b;
        --frenar:#f87171; --frenar-base:#ef4444; --peligro:#dc2626; --peligro-hover:#b91c1c;
        --r1:8px; --r2:12px; --r3:14px; --sombra:0 1px 3px rgba(0,0,0,.30), 0 1px 2px rgba(0,0,0,.20);
        --fuente:'Inter','Segoe UI',system-ui,-apple-system,Roboto,sans-serif;
        --mono:ui-monospace,'JetBrains Mono',SFMono-Regular,Menlo,Consolas,monospace; }
.stApp { background: radial-gradient(1100px 520px at 12% -12%, rgba(139,92,246,.10) 0%, var(--fondo) 60%);
    color: var(--texto); }
html, body, [class*="css"] { font-size: 17px; }
.stApp, .stApp p, .stApp li, .stApp label, .stApp input, .stApp textarea, .stApp button { font-family: var(--fuente); }
[data-testid="stMainBlockContainer"] { max-width: 1240px; padding-top: 4.5rem; padding-bottom: 4rem; }
[data-testid="stMainBlockContainer"]:has(.st-key-pantalla_raiz) { max-width: none; padding-left: 3vw;
    padding-right: 3vw; }
[data-testid="stHeader"] { background: rgba(17,24,39,.92); border-bottom: 1px solid var(--borde); }
[data-testid="stSidebar"] { background: var(--superficie); border-right: 1px solid var(--borde); }
h1, h2, h3 { font-family: var(--fuente) !important; font-weight: 700 !important; letter-spacing: -0.015em; }
h1 { font-size: 2.25rem !important; }
p, li { line-height: 1.55; }
.stApp a { color: var(--acento); }
.stApp code { font-family: var(--mono) !important; }
*:focus-visible { outline: 2px solid var(--acento) !important; outline-offset: 2px; }

/* --- cabecera de página --- */
.al-hero { border:1px solid var(--borde); border-radius:var(--r2); padding:24px 24px 20px 28px; margin-bottom:16px;
           background: var(--superficie); box-shadow: var(--sombra); position:relative; overflow:hidden; }
.al-hero::after { content:""; position:absolute; inset:0 auto 0 0; width:4px; background:var(--marca); }
.al-hero .eyebrow { font-size:.75rem; font-weight:700; letter-spacing:.14em; text-transform:uppercase;
    color:var(--acento); margin-bottom:8px; font-family:var(--mono); }
.al-hero h1 { margin:0 0 8px 0; padding:0; line-height:1.15; }
.al-hero p { color: var(--suave); margin:0; font-size:1.05rem; }

/* --- chips / badges (pastillas) --- */
.al-chip { display:inline-block; padding:4px 12px; border-radius:999px; font-size:.75rem; font-weight:700;
           letter-spacing:.04em; border:1px solid var(--borde); color:var(--suave); background:var(--elevada);
    margin:0 8px 8px 0; }
.al-chip.acento { color:var(--acento); border-color:rgba(139,92,246,.5); background:rgba(139,92,246,.14); }
.al-chip.aviso { color:var(--escalar); border-color:rgba(251,191,36,.5); background:rgba(245,158,11,.14); }
.al-chip.PAGAR { color:var(--pagar); border-color:rgba(52,211,153,.5); background:rgba(16,185,129,.14); }
.al-chip.ESCALAR { color:var(--escalar); border-color:rgba(251,191,36,.5); background:rgba(245,158,11,.14); }
.al-chip.FRENAR { color:var(--frenar); border-color:rgba(248,113,113,.5); background:rgba(239,68,68,.14); }

/* --- paso del flujo --- */
.al-paso { display:flex; align-items:center; gap:12px; margin:24px 0 8px; }
.al-paso .n { width:32px; height:32px; flex:0 0 32px; border-radius:50%; display:grid; place-items:center;
    font-weight:800; font-family:var(--mono); color:#fff; background:var(--acento-fondo);
    box-shadow:0 0 0 4px rgba(139,92,246,.18); }
.al-paso .t { font-weight:700; font-size:1.15rem; }
.al-paso .s { color:var(--suave); font-size:.9rem; }

/* --- sello de goma (decisión) --- */
.al-sello { border-radius:var(--r2); padding:20px 24px; margin:8px 0 16px; border:1px solid var(--borde); display:flex;
    gap:24px; align-items:center; flex-wrap:wrap; background:var(--superficie); }
.al-sello .timbre { display:inline-block; font-family:var(--mono); font-weight:800; font-size:1.7rem;
    letter-spacing:.12em; line-height:1.15; padding:4px 16px; border:4px solid currentColor; border-radius:10px;
    transform:rotate(-5deg); background:rgba(17,24,39,.6); }
.al-sello .d { font-size:1.2rem; font-weight:800; letter-spacing:.02em; line-height:1.2; }
.al-sello .c { font-family: var(--mono); font-size:.92rem; color:var(--suave); margin-top:4px; word-break:break-word; }
.al-sello.grande { padding:26px 28px; gap:32px; }
.al-sello.grande .timbre { font-size:clamp(2rem, 4vw, 3.4rem); border-width:6px; padding:6px 22px; }
.al-sello.grande .d { font-size:clamp(1.15rem, 1.6vw, 1.6rem); }
.al-PAGAR { background:rgba(16,185,129,.08); border-color:rgba(52,211,153,.45); }
.al-PAGAR .timbre, .al-PAGAR .d { color: var(--pagar); }
.al-ESCALAR { background:rgba(245,158,11,.08); border-color:rgba(251,191,36,.45); }
.al-ESCALAR .timbre, .al-ESCALAR .d { color: var(--escalar); }
.al-FRENAR { background:rgba(239,68,68,.08); border-color:rgba(248,113,113,.5); }
.al-FRENAR .timbre, .al-FRENAR .d { color: var(--frenar); }
.al-sello.entra .timbre { animation: al-estampa 360ms cubic-bezier(.2,.9,.3,1.2) both; }
@keyframes al-estampa { from { opacity:0; transform:rotate(-12deg) scale(1.8); }
    to { opacity:1; transform:rotate(-5deg) scale(1); } }

/* --- tarjetas genéricas y KPIs --- */
.al-card { border:1px solid var(--borde); border-radius:var(--r2); padding:16px; background:var(--superficie);
    margin-bottom:12px; box-shadow:var(--sombra); }
.al-card .k { color:var(--suave); font-size:.8rem; text-transform:uppercase; letter-spacing:.08em; font-weight:700; }
.al-card .v { font-size:1.05rem; margin-top:4px; word-break:break-word; }
.al-ficha { border:1px solid var(--borde); border-radius:var(--r2); padding:8px 16px; background:var(--superficie);
    margin-bottom:12px; }
.al-ficha div { display:flex; justify-content:space-between; gap:16px; padding:8px 0;
    border-bottom:1px solid var(--borde); }
.al-ficha div:last-child { border-bottom:none; }
.al-ficha .k { color:var(--suave); font-size:.88rem; } .al-ficha .v { text-align:right; font-weight:600;
    word-break:break-word; }
.al-kpis { display:grid; grid-template-columns:repeat(auto-fit, minmax(160px, 1fr)); gap:12px; margin:8px 0 16px; }
.al-kpi { border:1px solid var(--borde); border-radius:var(--r2); padding:16px 20px; background:var(--superficie);
    box-shadow:var(--sombra); }
.al-kpi .k { color:var(--suave); font-size:.78rem; font-weight:600; text-transform:uppercase; letter-spacing:.05em; }
.al-kpi .v { font-size:2rem; font-weight:700; margin-top:4px; font-family:var(--mono);
    font-variant-numeric:tabular-nums; }
.al-kpi.PAGAR .v { color:var(--pagar); } .al-kpi.FRENAR .v { color:var(--frenar);
    } .al-kpi.ESCALAR .v { color:var(--escalar); }
.al-kpi.acento .v { color:var(--acento); }

/* --- comité: tablero de agentes (se encienden con el color de su señal) --- */
.al-tablero { display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:12px; margin:8px 0 16px; }
.al-agente { border:1px solid var(--borde); border-radius:var(--r2); padding:16px; background:var(--superficie);
    box-shadow:var(--sombra); }
.al-agente .t { font-weight:700; font-size:1.02rem; display:flex; gap:8px; align-items:center; color:var(--suave); }
.al-agente .e { margin:8px 0 4px; font-weight:700; font-size:.9rem; }
.al-agente .m { color:var(--suave); font-size:.88rem; word-break:break-word; }
.al-agente .l { color:var(--texto); font-family:var(--mono); font-size:.78rem; margin-top:8px; }
.al-s0 { border-color: var(--pagar-base); background:linear-gradient(180deg, rgba(16,185,129,.14), var(--superficie)); }
.al-s0 .t, .al-s0 .e { color: var(--pagar); }
.al-s1 { border-color: var(--escalar-base); background:linear-gradient(180deg, rgba(245,158,11,.14), var(--superficie)); }
.al-s1 .t, .al-s1 .e { color: var(--escalar); }
.al-s2 { border-color: var(--frenar-base); background:linear-gradient(180deg, rgba(239,68,68,.14), var(--superficie)); }
.al-s2 .t, .al-s2 .e { color: var(--frenar); }
.al-s0 .m, .al-s1 .m, .al-s2 .m { color: var(--texto); }
.al-sp { opacity:.7; }
.al-lema { text-align:center; font-weight:800; font-size:1.35rem; letter-spacing:-.01em; margin:8px 0 16px; }
.al-lema span { color:var(--acento); }

/* --- feed y matriz --- */
.al-feed { list-style:none; padding:0; margin:0; }
.al-feed li { border:1px solid var(--borde); border-radius:var(--r2); padding:12px 16px; margin-bottom:8px;
    background:var(--superficie); display:flex; flex-wrap:wrap; align-items:center; gap:6px 10px; }
.al-feed li .al-chip { margin:0; }
.al-feed .a { font-weight:600; font-size:.8rem; padding:3px 10px; border-radius:999px; color:var(--acento);
    background:rgba(139,92,246,.14); border:1px solid rgba(139,92,246,.5); }
.al-feed .x { color:var(--suave); font-size:.9rem; flex-basis:100%; }
.al-feed code, .al-mono { font-family:var(--mono); font-size:.88em; }
.al-feed code { color:var(--texto); }
.al-matriz { border-collapse:separate; border-spacing:6px; width:100%; max-width:560px; }
.al-matriz th { color:var(--suave); font-weight:600; font-size:.85rem; text-align:center; padding:4px; }
.al-matriz td { text-align:center; font-weight:700; font-size:1.3rem; border-radius:10px; padding:14px 8px;
                background:var(--superficie); border:1px solid var(--borde); font-family:var(--mono); }
.al-matriz td.ok { background:rgba(139,92,246,.16); border-color:rgba(139,92,246,.55); color:var(--acento); }
.al-matriz td.mal { background:rgba(239,68,68,.14); border-color:rgba(248,113,113,.55); color:var(--frenar); }
.al-barra { height:12px; border-radius:999px; background:var(--elevada); border:1px solid var(--borde);
    overflow:hidden; }
.al-barra > div { height:100%; background:linear-gradient(90deg, var(--acento-fondo), var(--marca)); }

/* --- tarjetas de ataque (radio) --- */
.st-key-ataque [role="radiogroup"] { display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:12px; }
.st-key-ataque [role="radiogroup"] > div { margin:0; padding:14px 16px; border:1px solid var(--borde);
    border-radius:var(--r2);
    background:var(--superficie); min-height:88px; transition: border-color .15s ease, background-color .15s ease; }
.st-key-ataque [role="radiogroup"] > div:hover { border-color:rgba(167,139,250,.6); background:#243042; }
.st-key-ataque [role="radiogroup"] > div[data-selected="true"] { border-color:var(--marca);
    background:rgba(139,92,246,.12);
    box-shadow: 0 0 0 1px var(--marca) inset; }
.st-key-ataque [role="radiogroup"] > div:has(input:focus-visible) { outline:2px solid var(--acento);
    outline-offset:2px; }
.st-key-ataque [data-testid="stRadioOption"] { width:100%; cursor:pointer; }
.st-key-ataque [data-testid="stRadioOption"] p { font-weight:700; }

/* --- vista previa de la factura --- */
.al-preview img { display:block; width:100%; border-radius:var(--r2); border:1px solid var(--borde);
    box-shadow:0 20px 50px rgba(0,0,0,.35); }

/* --- botones e inputs --- */
div.stButton > button, div.stFormSubmitButton > button, div.stDownloadButton > button {
    border-radius:var(--r1); font-weight:600; min-height:44px; transition: filter .15s ease, border-color .15s ease; }
div.stButton > button[kind="secondary"], div.stDownloadButton > button { background:var(--elevada); color:var(--texto);
    border:1px solid var(--borde); }
div.stButton > button[kind="primary"] { background: var(--acento-fondo); color:#fff; border:1px solid var(--acento-fondo); }
div.stButton > button[kind="primary"]:hover { background: var(--acento-hover); color:#fff; }
/* El CTA de ataque es la acción de «robar»: rojo de peligro, como «Enviar y robar». */
div.stFormSubmitButton > button { background: var(--peligro); color:#fff; border:1px solid var(--peligro); }
div.stFormSubmitButton > button:hover { background: var(--peligro-hover); color:#fff; }
div.stFormSubmitButton > button p, div.stButton > button[kind="primary"] p { font-size:1.05rem; }
[data-testid="stForm"] { border-color:var(--borde); border-radius:var(--r2); background:rgba(31,41,55,.55); }
[data-testid="stVerticalBlockBorderWrapper"] { border-radius:var(--r2); }
.stApp input, .stApp textarea { font-size:1rem !important; }
[data-testid="stMetric"] { background:var(--superficie); border:1px solid var(--borde); border-radius:var(--r2);
    padding:14px 18px; box-shadow:var(--sombra); }
[data-testid="stMetricLabel"] p { color:var(--suave); font-weight:600; text-transform:uppercase; letter-spacing:.05em;
    font-size:.8rem !important; }
[data-testid="stMetricValue"], [data-testid="stMetricValue"] * { font-family:var(--mono) !important;
    font-variant-numeric:tabular-nums; font-weight:700; }
[data-testid="stAlert"] { border-radius:var(--r2) !important; }

/* --- pantalla de proyección --- */
.stApp:has(.st-key-pantalla_raiz)::before { content:""; position:fixed; inset:0; z-index:0; pointer-events:none;
    background: radial-gradient(40% 35% at 20% 25%, rgba(139,92,246,.16), transparent 70%),
                radial-gradient(35% 30% at 80% 20%, rgba(16,185,129,.10), transparent 70%),
                radial-gradient(45% 40% at 60% 85%, rgba(56,189,248,.08), transparent 70%);
    background-size:120% 120%; animation: al-aurora 38s ease-in-out infinite alternate; }
@keyframes al-aurora { from { background-position:0% 0%; } to { background-position:100% 100%; } }
.st-key-pantalla_raiz { position:relative; z-index:1; }
.st-key-pantalla_raiz .al-hero h1 { font-size:clamp(2.2rem, 4.2vw, 4.4rem) !important; }
.st-key-pantalla_raiz .al-hero p { font-size:clamp(1rem, 1.5vw, 1.5rem); }
.st-key-pantalla_kpis [data-testid="stMetricValue"] { font-size:clamp(3rem, 6vw, 6rem); font-weight:700;
    line-height:1.05; }
.st-key-pantalla_kpis [data-testid="stMetricLabel"] p { font-size:clamp(.85rem, 1.1vw, 1.15rem) !important; }
.st-key-pantalla_kpis [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2) [data-testid="stMetric"] {
    border:2px solid var(--pagar-base); background:linear-gradient(180deg, rgba(16,185,129,.16), var(--superficie)); }
.st-key-pantalla_kpis [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2) [data-testid="stMetricValue"] {
    color:var(--pagar); }
.al-qr { background:#fff; border-radius:var(--r3); padding:8px; max-width:440px; margin:0 auto;
    box-shadow:0 20px 50px rgba(0,0,0,.4), 0 0 80px rgba(139,92,246,.18); }
.al-qr img { display:block; width:100% !important; max-width:100% !important; height:auto; border:none !important; }
.al-instruccion { font-size:clamp(1.05rem, 1.4vw, 1.5rem); font-weight:700; text-align:center; margin:12px 0 4px; }
.al-url { font-family:var(--mono); text-align:center; color:var(--acento); word-break:break-all; font-size:.95rem; }
.st-key-pantalla_qr { align-items:center; text-align:center; max-width:520px; margin:0 auto 8px; }
.st-key-pantalla_qr .al-qr { width:min(320px, 72vw); }
.st-key-pantalla_qr [data-testid="stCaptionContainer"] { text-align:center; }
.st-key-pantalla_qr label { justify-content:center; margin:0 auto; }

/* --- aprobación: botones grandes, rechazar en rojo y tarjeta bloqueada --- */
[class*="st-key-ok_"] button, [class*="st-key-peligro"] button { min-height:56px; }
[class*="st-key-ok_"] button { background:#047857 !important; color:#fff !important; border:none !important; }
[class*="st-key-peligro"] button { background:var(--peligro) !important; color:#fff !important; border:none !important; }
[class*="st-key-peligro"] button:hover, [class*="st-key-ok_"] button:hover { filter:brightness(1.1); }
[class*="st-key-bloq_"] { border:2px solid var(--frenar-base) !important; border-radius:var(--r2); }
.al-bloqueo { border:1px solid rgba(248,113,113,.55); background:rgba(239,68,68,.10); border-radius:var(--r2);
    padding:12px 16px; display:flex; gap:12px; align-items:flex-start; margin:4px 0 8px; }
.al-bloqueo .i { font-size:1.4rem; line-height:1; } .al-bloqueo .t { color:var(--frenar); font-weight:800; }
.al-bloqueo .a { color:var(--texto); margin-top:4px; font-size:.95rem; }
.stApp button:disabled { opacity:.45; cursor:not-allowed; filter:grayscale(.6); }

@media (max-width: 900px) { .st-key-ataque [role="radiogroup"] { grid-template-columns:repeat(2, minmax(0, 1fr)); } }
@media (max-width: 640px) {
  [data-testid="stMainBlockContainer"] { padding-left:16px; padding-right:16px; padding-top:3.5rem; }
  h1 { font-size:1.7rem !important; } .al-hero { padding:16px 16px 16px 20px; } .al-hero p { font-size:.98rem; }
  .al-sello { padding:16px; gap:16px; } .al-sello .timbre { font-size:1.4rem; }
  .al-sello.grande .timbre { font-size:1.9rem; } .al-sello.grande .d { font-size:1.1rem; }
  .st-key-ataque [role="radiogroup"] > div { padding:12px; min-height:0; }
  .al-kpis { grid-template-columns:repeat(auto-fit, minmax(96px, 1fr)); gap:8px; }
  .al-kpi { padding:12px; } .al-kpi .k { font-size:.7rem; } .al-kpi .v { font-size:1.5rem; }
  .al-preview img { max-height:240px; object-fit:cover; object-position:top; }
  /* En el celular los 3 contadores de la pantalla siguen en una fila compacta. */
  .st-key-pantalla_kpis [data-testid="stHorizontalBlock"] { flex-wrap:nowrap !important; gap:8px !important; }
  .st-key-pantalla_kpis [data-testid="stColumn"] { min-width:0 !important; width:auto !important;
      flex:1 1 0 !important; }
  .st-key-pantalla_kpis [data-testid="stMetric"] { padding:10px; min-height:118px; }
  .st-key-pantalla_kpis [data-testid="stMetricValue"] { font-size:2.2rem !important; }
  .st-key-pantalla_kpis [data-testid="stMetricLabel"] p { font-size:.68rem !important; white-space:normal !important;
      overflow:visible !important; text-overflow:clip !important; line-height:1.2; }
  .st-key-pantalla_kpis [data-testid="stMetricLabel"] div { overflow:visible !important;
      white-space:normal !important; }
}
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { transition:none !important;
    animation:none !important; } }
</style>
"""  # noqa: E501 - CSS legible en una línea por regla

DECISIONES = {"PAGAR": "PAGAR · autorización simulada", "ESCALAR": "ESCALAR · decide una persona",
              "FRENAR": "FRENAR"}
ICONOS = {"PAGAR": "✅", "ESCALAR": "✋", "FRENAR": "⛔"}
SELLOS = {"PAGAR": "PAGADO", "ESCALAR": "ESCALADO", "FRENAR": "FRENADO"}
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
ICONOS_AGENTE = {"duplicados": "🗂️", "contrato": "📑", "beneficiario": "🏦", "seguridad": "🛡️", "presupuesto": "💱",
                 "reglas": "⚖️"}
TONOS = {"acento", "aviso", "neutro", "PAGAR", "ESCALAR", "FRENAR"}


def aplicar() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def etiqueta_codigo(codigo: str) -> str:
    return CODIGOS.get(codigo, "Código no reconocido")


def _tono(tono: str) -> str:
    return tono if tono in TONOS else "neutro"


def hero(titulo: str, subtitulo: str, antetitulo: str = "") -> None:
    arriba = f'<div class="eyebrow">{html.escape(antetitulo)}</div>' if antetitulo else ""
    st.markdown(f'<div class="al-hero">{arriba}<h1>{html.escape(titulo)}</h1><p>{html.escape(subtitulo)}</p></div>',
                unsafe_allow_html=True)


def chip(texto: str, tono: str = "acento") -> None:
    st.markdown(f'<span class="al-chip {_tono(tono)}">{html.escape(texto)}</span>', unsafe_allow_html=True)


def paso(numero: int, titulo: str, subtitulo: str = "") -> None:
    st.markdown(f'<div class="al-paso"><div class="n">{int(numero)}</div><div><div class="t">{html.escape(titulo)}'
                f'</div><div class="s">{html.escape(subtitulo)}</div></div></div>', unsafe_allow_html=True)


def sello(decision: str, codigo: str, grande: bool = False, animar: bool = False) -> None:
    """Sello de goma inclinado (PAGADO / ESCALADO / FRENADO) + la decisión y su código. `animar` lo hace caer."""
    if decision not in DECISIONES:                     # nunca se muestra algo fuera de la lista blanca
        decision, codigo = "FRENAR", "ERROR_TECNICO"
    codigo = codigo if codigo in CODIGOS else "ERROR_TECNICO"
    clases = f'al-sello al-{decision}{" grande" if grande else ""}{" entra" if animar else ""}'
    st.markdown(
        f'<div class="{clases}" role="status">'
        f'<div class="timbre" aria-hidden="true">{SELLOS[decision]}</div><div>'
        f'<div class="d">{html.escape(DECISIONES[decision])}</div>'
        f'<div class="c">{html.escape(codigo)} · {html.escape(etiqueta_codigo(codigo))}</div></div></div>',
        unsafe_allow_html=True)


def tarjetas(pares: list[tuple[str, str]]) -> None:
    """Tarjetas clave → valor (los valores se escapan)."""
    st.markdown("".join(f'<div class="al-card"><div class="k">{html.escape(k)}</div>'
                        f'<div class="v">{html.escape(str(v))}</div></div>' for k, v in pares),
                unsafe_allow_html=True)


def ficha(pares: list[tuple[str, str]]) -> None:
    """Una sola tarjeta con filas clave → valor (los valores se escapan)."""
    st.markdown('<div class="al-ficha">' + "".join(
        f'<div><span class="k">{html.escape(k)}</span><span class="v">{html.escape(str(v))}</span></div>'
        for k, v in pares) + "</div>", unsafe_allow_html=True)


def kpis(items: list[tuple[str, object, str]]) -> None:
    """Fila de KPIs: (etiqueta, valor tal como lo dio la API, tono)."""
    st.markdown('<div class="al-kpis">' + "".join(
        f'<div class="al-kpi {_tono(tono)}"><div class="k">{html.escape(k)}</div><div class="v">{html.escape(str(v))}'
        f'</div></div>' for k, v, tono in items) + "</div>", unsafe_allow_html=True)


def _estado_agente(evento: dict | None) -> tuple[str, str, str]:
    if evento is None:
        return "al-sp", "⏳ procesando…", "Esperando el evento real del agente."
    sev = int(evento.get("severidad", 0))
    tipo = {"riesgo": "riesgo", "fallo_tecnico": "fallo técnico", "sin_evidencia": "sin evidencia",
            "sin_hallazgos": "sin hallazgos"}.get(evento.get("tipo", ""), "—")
    estado = {0: "✓ sin objeciones", 1: "● pide escalar", 2: "■ pide frenar"}.get(sev, "● pide escalar")
    extra = f" · p={float(evento['probabilidad']):.2f}" if evento.get("probabilidad") is not None else ""
    return f"al-s{sev if sev in (0, 1, 2) else 1}", f"{estado} · {tipo}{extra}", str(evento.get("motivo") or "—")


def tarjeta_agente_html(nombre: str, evento: dict | None, titulo: str | None = None) -> str:
    clase, estado, motivo = _estado_agente(evento)
    latencia = f"severidad {int(evento.get('severidad', 0))} · {int(evento.get('latencia_ms', 0))} ms" if evento else ""
    return (f'<div class="al-agente {clase}"><div class="t"><span aria-hidden="true">'
            f'{ICONOS_AGENTE.get(nombre, "•")}</span>{html.escape(titulo or AGENTES.get(nombre, nombre))}</div>'
            f'<div class="e">{html.escape(estado)}</div><div class="m">{html.escape(motivo)}</div>'
            f'<div class="l">{html.escape(latencia)}</div></div>')


def tablero_agentes(por_agente: dict[str, dict]) -> None:
    """Los cinco agentes en una rejilla que se adapta al ancho (nunca cinco columnas diminutas en móvil)."""
    st.markdown('<div class="al-tablero">' + "".join(tarjeta_agente_html(n, por_agente.get(n)) for n in AGENTES)
                + "</div>", unsafe_allow_html=True)


def tarjeta_agente(nombre: str, evento: dict | None) -> None:
    st.markdown(tarjeta_agente_html(nombre, evento), unsafe_allow_html=True)


def bloqueo(titulo: str, accion: str) -> None:
    """Tarjeta roja con candado: lo que ni una persona puede aprobar y qué hay que hacer."""
    st.markdown(f'<div class="al-bloqueo" role="alert"><div class="i" aria-hidden="true">🔒</div><div>'
                f'<div class="t">{html.escape(titulo)}</div><div class="a">{html.escape(accion)}</div></div></div>',
                unsafe_allow_html=True)


def lema() -> None:
    st.markdown('<div class="al-lema">Los agentes detectan. <span>Las reglas deciden.</span></div>',
                unsafe_allow_html=True)


def feed(items: list[dict]) -> None:
    """Últimos intentos: solo alias, campos cambiados, monto, cuenta YA enmascarada por la API y la decisión."""
    filas = []
    for x in items:
        decision = x.get("decision") if x.get("decision") in DECISIONES else "FRENAR"
        codigo = x.get("codigo") if x.get("codigo") in CODIGOS else "ERROR_TECNICO"
        cambios = ", ".join(str(c) for c in x.get("campos_cambiados") or []) or "la envió tal cual"
        filas.append(
            f'<li><span class="al-chip {decision}">{ICONOS[decision]} {decision}</span>'
            f'<span class="a">{html.escape(str(x.get("alias", "")))}</span> · cambió {html.escape(cambios)}'
            f'<div class="x">{html.escape(monto(float(x.get("monto") or 0), str(x.get("moneda") or "")))} · cuenta '
            f'<code>{html.escape(str(x.get("cuenta_enmascarada", "")))}</code> · <code>{codigo}</code> '
            f'({html.escape(etiqueta_codigo(codigo))})</div></li>')
    st.markdown(f'<ul class="al-feed">{"".join(filas)}</ul>', unsafe_allow_html=True)


def matriz(etiquetas: list[str], filas: dict[str, dict]) -> None:
    """Matriz de confusión con los números de /metricas (filas = esperado, columnas = obtenido)."""
    cab = "".join(f"<th scope='col'>{html.escape(e)}</th>" for e in etiquetas)
    cuerpo = ""
    for esperado in etiquetas:
        celdas = ""
        for obtenido in etiquetas:
            n = int(filas.get(esperado, {}).get(obtenido, 0))
            clase = "ok" if esperado == obtenido and n else ("mal" if n and obtenido == "PAGAR" else "")
            celdas += f"<td class='{clase}'>{n}</td>"
        cuerpo += f"<tr><th scope='row'>{html.escape(esperado)}</th>{celdas}</tr>"
    st.markdown(f"<table class='al-matriz' aria-label='Matriz de confusión'><tr><th>esperado ↓ / obtenido →</th>"
                f"{cab}</tr>{cuerpo}</table>", unsafe_allow_html=True)


def barra(fraccion: float, etiqueta: str) -> None:
    ancho = max(0.0, min(1.0, float(fraccion))) * 100
    st.markdown(f'<div class="al-barra" role="img" aria-label="{html.escape(etiqueta, quote=True)}">'
                f'<div style="width:{ancho:.1f}%"></div></div>', unsafe_allow_html=True)


def monto(valor: float, moneda: str) -> str:
    texto = f"{valor:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{moneda} {texto}"


def imagen_png(datos: bytes, alt: str, clase: str = "al-preview") -> None:
    """PNG con texto alternativo (st.image no admite alt). El alt se escapa: lo arma el servidor."""
    codificada = base64.b64encode(datos).decode("ascii")
    st.markdown(f'<div class="{html.escape(clase, quote=True)}"><img src="data:image/png;base64,{codificada}" '
                f'alt="{html.escape(alt, quote=True)}" style="width:100%"></div>', unsafe_allow_html=True)


def qr(url: str, alt: str) -> None:
    """Código QR (PNG, con alt) hacia `url`. segno genera el PNG sin dependencias."""
    import io

    import segno

    salida = io.BytesIO()
    segno.make(url, error="m").save(salida, kind="png", scale=10, border=2, dark="#111827", light="#FFFFFF")
    imagen_png(salida.getvalue(), alt, clase="al-qr")
