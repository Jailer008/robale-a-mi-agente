"""Pantallas del Attack Lab. Todo dato viene de la API (que usa el cerebro real); nada se inventa aquí.

Autoría: Dev 2 (anticipo del alcance de Dev 3) · revisión de Dev 3 PENDIENTE.
"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from urllib.parse import quote

import cliente
import estilo
import streamlit as st

PRESETS = {"limpia": "Factura limpia", "cuenta_cambiada": "Cuenta bancaria cambiada",
           "proveedor_nuevo": "Proveedor nuevo", "monto_inflado": "Monto inflado",
           "duplicado": "Factura duplicada", "instruccion_maliciosa": "Instrucción maliciosa"}
MONEDAS = ["USD", "COP", "MXN", "ARS", "PEN", "EUR"]

# Ataque → (icono, título, descripción, campos que se destacan en el PDF, preset del modo sintético).
ATAQUES = {
    "cuenta": ("🏦", "Cambiar cuenta bancaria", "Pon otra cuenta para cobrar tú.", ["cuenta"], "cuenta_cambiada"),
    "proveedor": ("🏷️", "Cambiar proveedor", "Factura a nombre de otra empresa.", ["proveedor"], "proveedor_nuevo"),
    "monto": ("💸", "Inflar monto", "Sube el total y cobra de más.", ["monto"], "monto_inflado"),
    "duplicado": ("🗂️", "Duplicar factura", "Reenvía una factura que ya se pagó.", ["numero"], "duplicado"),
    "inyeccion": ("🧨", "Inyectar instrucciones", "Escríbele órdenes al agente, visibles u ocultas.", ["nota"],
                  "instruccion_maliciosa"),
    "legitima": ("✅", "Enviar factura legítima", "Mándala tal cual: ¿la autoriza?", [], "limpia"),
}
QUE_CAMBIA = {"cuenta": "la cuenta bancaria impresa en el PDF", "proveedor": "el nombre del proveedor",
              "monto": "el total de la factura", "numero": "el número de factura",
              "nota": "una nota dirigida al agente"}
MODOS = {"pdf": "📄 Falsificar el PDF", "sintetico": "🧪 Datos sintéticos", "documento": "📤 Subir documento"}
CAMPOS_F = ("f_monto", "f_cuenta", "f_proveedor", "f_numero", "f_nota", "f_oculta", "f_rayar")
CTA = "Intentar engañar al agente"


def _token() -> str | None:
    return st.session_state.get("token") or None


def _error(error: cliente.ErrorApi) -> None:
    st.error(f"{error}")
    detalle = error.cuerpo.get("detalle")
    if detalle:
        st.caption("; ".join(f"{d.get('campo')}: {d.get('problema')}" for d in detalle[:6]))
    if error.cuerpo.get("accion_requerida"):
        st.info(f"Acción requerida: {error.cuerpo['accion_requerida']}")


def _estado_humano(d: dict) -> str:
    """Qué puede hacer una persona con esta decisión, leído de los campos que da la API (no se recalcula)."""
    if d.get("aprobado") is not None:
        return f"Resuelta por una persona: {'aprobada' if d['aprobado'] else 'rechazada'}."
    if d["decision"] == "PAGAR":
        return "Autorización simulada por las reglas, sin intervención humana. No se movió dinero."
    if d["decision"] == "FRENAR":
        return "Bloqueo definitivo: ninguna persona puede aprobarla."
    if d.get("aprobable"):
        return "Pendiente: una persona autenticada debe aprobarla o rechazarla."
    return "Nadie puede aprobarla así: hay que corregir el dato y volver a evaluarla."


def _resultado(r: dict) -> None:
    """Paso 3 · veredicto. Decisión, código, aprobable y acción vienen tal cual de la API."""
    d = r["decision"]
    if r.get("modo_analisis"):
        estilo.chip(r["modo_analisis"], "neutro")
    if r.get("fuente_extraccion"):
        estilo.chip(f"lectura: {r['fuente_extraccion']}", "neutro")
    estilo.sello(d["decision"], d["codigo_principal"], grande=True)
    st.markdown(f"**En simple:** {d['explicacion']}")
    if d.get("accion_requerida"):
        st.warning(f"Acción requerida: {d['accion_requerida']}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Monto", estilo.monto(d["monto_original"], d["moneda"]))
    c2.metric("Monto USD", estilo.monto(d["monto_usd"], "USD"))
    c3.metric("¿Aprobable por una persona?", "Sí" if d["aprobable"] else "No")
    regla = r.get("regla_principal") or {}
    estilo.tarjetas([
        ("Regla o agente que decidió", f"{regla.get('tipo', '—')} · {regla.get('nombre', '—')} "
                                       f"({estilo.etiqueta_codigo(regla.get('codigo', 'OK'))})"),
        ("Aprobación humana", _estado_humano(d)),
    ])
    if d["hallazgos"]:
        st.markdown("**Evidencia (motivos con código estable)**")
        for h in d["hallazgos"]:
            st.markdown(f"- `{h['codigo']}` · severidad {h['severidad']} · {h['agente']}: {h['motivo']}")
    if d.get("contrafactual"):
        st.caption(f"Contrafactual: {d['contrafactual']}")
    st.caption(f"Pago simulado: ninguna transferencia real. {r.get('advertencia', '')} · "
               f"factura_id {d['factura_id'][:12]}…")


# ---------- A. Attack Lab ----------

def _cargar_preset(nombre: str) -> None:
    try:
        st.session_state["caso"] = cliente.get(f"/presets/{nombre}")
        st.session_state["version_form"] = st.session_state.get("version_form", 0) + 1
    except cliente.ErrorApi as error:
        _error(error)


RAYABLE = {"total": "el total", "cuenta": "la cuenta", "numero": "el número"}


def _cargar_base() -> None:
    try:
        st.session_state["base_f"] = cliente.get("/falsificar/base")
        st.session_state["preview_f"] = cliente.imagen(st.session_state["base_f"]["preview_url"])
    except cliente.ErrorApi as error:
        st.session_state.pop("base_f", None)
        _error(error)


def _nuevo_ataque() -> None:
    """Al cambiar de ataque se limpia el formulario: lo que se envía es solo lo de este ataque."""
    for clave in CAMPOS_F:
        st.session_state.pop(clave, None)


def _elegir_ataque() -> str:
    estilo.paso(1, "Elige tu ataque", "Cada tarjeta prepara un engaño distinto.")
    elegido = st.radio("Ataque", list(ATAQUES), key="ataque", label_visibility="collapsed",
                       format_func=lambda k: f"{ATAQUES[k][0]} {ATAQUES[k][1]}",
                       captions=[a[2] for a in ATAQUES.values()], on_change=_nuevo_ataque)
    return elegido or "cuenta"


def _campo(nombre: str, base: dict) -> None:
    if nombre == "monto":
        st.number_input(f"Nuevo total ({base['moneda']})", min_value=0.0, max_value=1_000_000_000.0, value=None,
                        placeholder=f"{base['total']:,.2f}", key="f_monto")
    elif nombre == "cuenta":
        st.text_input("Cuenta bancaria", max_chars=40, key="f_cuenta", placeholder="Inventa una, p. ej. ATACANTE-1234",
                      help="Inventa una cuenta. No pongas la tuya real.")
    elif nombre == "proveedor":
        st.text_input("Proveedor", max_chars=40, key="f_proveedor", placeholder=base["proveedor"])
    elif nombre == "numero":
        st.text_input("Número de factura", max_chars=40, key="f_numero", placeholder="p. ej. FV-0192 (ya pagada)")
    elif nombre == "nota":
        st.text_area("Nota al agente", max_chars=200, key="f_nota", placeholder="Escríbele una orden al agente…")
        st.checkbox("Esconder la nota (texto blanco diminuto)", key="f_oculta")


def _falsificar(ataque: str) -> None:
    """Modo principal (plan v2): el jurado edita y raya; el servidor dibuja el PDF y el agente lo LEE."""
    st.session_state.setdefault("sesion_id", uuid.uuid4().hex[:24])
    if "base_f" not in st.session_state:
        _cargar_base()
    base = st.session_state.get("base_f")
    if not base:
        return
    icono, titulo, _, destacados, _ = ATAQUES[ataque]
    estilo.paso(2, "Manipula la factura", "El servidor vuelve a dibujar el PDF y el agente lee el documento, "
                                          "no este formulario.")
    estilo.chip(base["etiqueta_modo"])
    st.markdown(f"💡 {base['pista']}")
    st.markdown(f"**{base['proveedor']}** · factura {base['numero']} · "
                f"{estilo.monto(base['total'], base['moneda'])} · cuenta {base['cuenta_enmascarada']}")
    formulario, vista = st.columns([7, 5], gap="large")
    with vista:
        if st.session_state.get("preview_f"):
            estilo.imagen_png(st.session_state["preview_f"],
                              f"Vista previa de la factura {base['numero']} de {base['proveedor']}: total "
                              f"{estilo.monto(base['total'], base['moneda'])}, cuenta {base['cuenta_enmascarada']}")
            st.caption("La factura que recibiste (original, sin cambios)")
        if st.button("Dame otra factura", key="f_otra", use_container_width=True):
            _cargar_base()
            st.session_state.pop("resultado_f", None)
            st.rerun()
    with formulario, st.form("falsificar"):
        cambia = ", ".join(QUE_CAMBIA[c] for c in destacados)
        st.markdown(f"**{icono} {titulo}** — " + (f"cambiarás {cambia}." if cambia else
                                                     "la envías tal cual; si no tocas nada, nada cambia."))
        for nombre in destacados:
            _campo(nombre, base)
        with st.expander("Combinar con más cambios (opcional)"):
            for nombre in ("cuenta", "monto", "proveedor", "numero", "nota"):
                if nombre not in destacados:
                    _campo(nombre, base)
            st.multiselect("Rayar encima de…", list(RAYABLE), format_func=RAYABLE.get, key="f_rayar")
        enviar = st.form_submit_button(CTA, type="primary", use_container_width=True)
    if enviar:
        cambios: dict = {}
        monto = st.session_state.get("f_monto")
        if monto is not None:
            cambios["monto"] = float(monto)
        for campo in ("cuenta", "proveedor", "numero"):
            valor = (st.session_state.get(f"f_{campo}") or "").strip()
            if valor:
                cambios[campo] = valor
        nota = (st.session_state.get("f_nota") or "").strip()
        if nota:
            cambios["nota"] = nota
            if st.session_state.get("f_oculta"):
                cambios["nota_oculta"] = True
        datos = {"sesion_id": st.session_state["sesion_id"], "base_id": base["base_id"], "cambios": cambios}
        rayar = st.session_state.get("f_rayar") or []
        if rayar:
            datos["rayar"] = list(rayar)
        try:
            with st.spinner("El agente está leyendo tu factura…"):
                r = cliente.post("/falsificar", json=datos)
            st.session_state["resultado_f"] = r
            st.session_state["ultimo_id"] = r["decision"]["factura_id"]
        except cliente.ErrorApi as error:
            _error(error)
    r = st.session_state.get("resultado_f")
    if r:
        estilo.paso(3, "Veredicto del agente", "Decisión real de la API: reglas deterministas + cinco agentes.")
        cambiados = ", ".join(r.get("campos_cambiados") or []) or "nada (la enviaste tal cual)"
        st.markdown(f"**Lo que cambiaste:** {cambiados} · lectura: {r.get('fuente_extraccion', '—')}")
        _resultado(r)


def _sintetico(ataque: str) -> None:
    estilo.chip("DATOS SINTÉTICOS — EVALUACIÓN REAL DEL CEREBRO", "neutro")
    preset = ATAQUES[ataque][4]
    if preset != st.session_state.get("preset_cargado"):
        st.session_state["preset_cargado"] = preset
        _cargar_preset(preset)
    caso = st.session_state.get("caso")
    if not caso:
        st.info("No se pudo cargar la factura ficticia de este ataque.")
        return
    estilo.paso(2, "Manipula los datos", f"Factura ficticia «{PRESETS.get(preset, preset)}». "
                                         "El servidor recalcula toda la aritmética.")
    v = st.session_state.get("version_form", 0)
    with st.form(f"ataque_{v}"):
        c1, c2 = st.columns(2)
        proveedor = c1.text_input("Proveedor", caso["proveedor"], max_chars=80, key=f"prov_{v}")
        cuenta = c2.text_input("Cuenta bancaria", caso["cuenta_bancaria"], max_chars=40, key=f"cta_{v}")
        numero = c1.text_input("Número de factura (vacío = automático)", caso["numero_factura"], max_chars=40,
                               key=f"num_{v}")
        fecha = c2.date_input("Fecha de emisión", dt.date.fromisoformat(caso["fecha_emision"]), key=f"fec_{v}")
        moneda = c1.selectbox("Moneda", MONEDAS, index=MONEDAS.index(caso["moneda"]), key=f"mon_{v}")
        impuestos = c2.number_input("Impuestos", min_value=0.0, value=float(caso["impuestos"]), key=f"imp_{v}")
        lineas = st.data_editor(caso["lineas"], num_rows="dynamic", key=f"lin_{v}", use_container_width=True,
                                column_config={"descripcion": "Descripción", "cantidad": "Cantidad",
                                               "precio_unitario": "Precio unitario"})
        nota = st.text_area("Nota del proveedor (texto no confiable del documento)", caso["nota"],
                            max_chars=600, key=f"nota_{v}")
        total = sum(float(li.get("cantidad") or 0) * float(li.get("precio_unitario") or 0) for li in lineas)
        st.caption(f"Vista previa: total ≈ {estilo.monto(total + impuestos, moneda)} "
                   "(el servidor recalcula toda la aritmética)")
        enviar = st.form_submit_button(CTA, type="primary", use_container_width=True)
    if enviar:
        datos = {"sesion_id": st.session_state["sesion_id"], "preset": caso.get("preset"),
                 "proveedor": proveedor, "cuenta_bancaria": cuenta, "numero_factura": numero,
                 "fecha_emision": fecha.isoformat(), "moneda": moneda, "impuestos": impuestos, "nota": nota,
                 "referencia_contrato": caso.get("referencia_contrato"),
                 "lineas": [{"descripcion": str(li.get("descripcion") or ""),
                             "cantidad": float(li.get("cantidad") or 0),
                             "precio_unitario": float(li.get("precio_unitario") or 0)} for li in lineas]}
        try:
            with st.spinner("El comité está revisando la factura…"):
                r = cliente.post("/simular", json=datos)
            st.session_state["resultado"] = r
            st.session_state["ultimo_id"] = r["decision"]["factura_id"]
        except cliente.ErrorApi as error:
            _error(error)
    if st.session_state.get("resultado"):
        estilo.paso(3, "Veredicto del agente", "Decisión real de la API: reglas deterministas + cinco agentes.")
        _resultado(st.session_state["resultado"])


def _documento() -> None:
    estilo.paso(1, "Sube una factura", "PDF, PNG, JPG, EML o TXT, máximo 10 MB.")
    st.caption("Sin extracción LIVE autorizada, un documento nuevo se escala de forma honesta (no se inventa "
               "una lectura).")
    archivo = st.file_uploader("Factura", type=["pdf", "png", "jpg", "jpeg", "eml", "txt"])
    canal = st.selectbox("Canal", ["web", "telegram", "email", "chat"])
    if archivo is not None and st.button("Analizar documento", type="primary", use_container_width=True):
        try:
            with st.spinner("Leyendo y evaluando…"):
                r = cliente.subir(archivo.name, archivo.getvalue(), canal)
            st.session_state["ultimo_id"] = r["decision"]["factura_id"]
            st.session_state["resultado_doc"] = r
        except cliente.ErrorApi as error:
            _error(error)
    if st.session_state.get("resultado_doc"):
        estilo.paso(2, "Veredicto del agente", "Decisión real de la API.")
        _resultado(st.session_state["resultado_doc"])


def attack_lab() -> None:
    st.session_state.setdefault("sesion_id", uuid.uuid4().hex[:24])
    estilo.hero("¿Puedes engañar al agente?", "Prueba con facturas 100 % ficticias. No hay pagos reales.",
                "Attack Lab · Róbale a mi agente")
    modo = st.segmented_control("Cómo atacar", list(MODOS), format_func=MODOS.get, key="modo_lab",
                                default="pdf") or "pdf"
    if modo == "documento":
        _documento()
        return
    ataque = _elegir_ataque()
    if modo == "sintetico":
        _sintetico(ataque)
    else:
        _falsificar(ataque)


# ---------- B. Comité en vivo ----------

def _elegir_factura(etiqueta: str) -> str | None:
    try:
        items = cliente.get("/decisiones", limite=50)["items"]
    except cliente.ErrorApi as error:
        _error(error)
        return None
    if not items:
        st.info("Todavía no hay facturas evaluadas.")
        return None
    ids = [x["factura_id"] for x in items]
    ultimo = st.session_state.get("ultimo_id")
    indice = ids.index(ultimo) if ultimo in ids else 0
    return st.selectbox(etiqueta, ids, index=indice, format_func=lambda i: next(
        f"{x['numero_factura']} · {x['proveedor']} · {x['decision']}" for x in items if x["factura_id"] == i))


def comite() -> None:
    estilo.hero("Comité en vivo", "Cinco agentes revisan cada factura. Solo pueden endurecer la decisión.",
                "Centro de operaciones")
    estilo.lema()
    factura_id = _elegir_factura("Factura")
    if not factura_id:
        return

    @st.fragment(run_every=2 if st.session_state.get("en_vivo") else None)
    def tablero() -> None:
        try:
            datos = cliente.get(f"/eventos/{factura_id}")
            evidencia = cliente.get(f"/evidencia/{factura_id}")
        except cliente.ErrorApi as error:
            _error(error)
            return
        por_agente = {e["agente"]: e for e in datos["eventos"]}
        estilo.tablero_agentes(por_agente)
        if datos["estado"] != "listo":
            st.info(f"Procesando… (etapa real: {datos.get('etapa') or 'pendiente'})")
            return
        st.markdown(estilo.tarjeta_agente_html("reglas", por_agente.get("reglas"), "Llave de reglas (determinista)"),
                    unsafe_allow_html=True)
        d = evidencia["decision"]                      # decisión final: nunca el campo `cedar`
        st.markdown("**Decisión final**")
        estilo.sello(d["decision"], d["codigo_principal"], grande=True)
        st.write(d["explicacion"])
        if d.get("accion_requerida"):
            st.warning(f"Acción requerida: {d['accion_requerida']}")

    st.toggle("Actualizar en vivo", key="en_vivo", help="Vuelve a pedir los eventos reales cada 2 s.")
    tablero()


# ---------- C. Bandeja ----------

def _resolver(factura_id: str, accion: str) -> None:
    clave = st.session_state.setdefault("claves", {}).setdefault(f"{accion}:{factura_id}", uuid.uuid4().hex)
    try:
        if accion == "reevaluar":
            r = cliente.post(f"/reevaluar/{factura_id}", token=_token())
        else:
            r = cliente.post(f"/{accion}/{factura_id}", token=_token(), idempotencia=clave)
        st.success(f"Resultado: {r['decision']} · {estilo.etiqueta_codigo(r['codigo_principal'])}")
    except cliente.ErrorApi as error:
        _error(error)


def bandeja() -> None:
    estilo.hero("Bandeja", "PAGAR es una autorización simulada. Solo lo pendiente y aprobable se puede aprobar.",
                "Operación")
    try:
        items = cliente.get("/decisiones", limite=100)["items"]
    except cliente.ErrorApi as error:
        _error(error)
        return
    grupos = [("ESCALAR", "✋ Pendiente de una persona", [x for x in items if x["estado"] == "pendiente_humano"]),
              ("PAGAR", "✅ PAGAR (simulado)", [x for x in items if x["decision"] == "PAGAR"]),
              ("FRENAR", "⛔ FRENAR", [x for x in items if x["decision"] == "FRENAR"])]
    estilo.kpis([(titulo, len(lista), tono) for tono, titulo, lista in grupos])
    if not _token():
        st.caption("Para aprobar o rechazar, abre «Acceso de operador» en el menú lateral.")
    for columna, (tono, titulo, lista) in zip(st.columns(3), grupos, strict=True):
        with columna:
            st.subheader(f"{titulo} · {len(lista)}")
            if not lista:
                st.caption("Nada aquí.")
            for x in lista:
                with st.container(border=True):
                    estilo.chip(estilo.etiqueta_codigo(x["codigo_principal"]), tono)
                    st.markdown(f"**{x['proveedor']}** · {x['numero_factura']}")
                    st.markdown(f"{estilo.monto(x['monto_original'], x['moneda'])}")
                    st.caption(x.get("origen", ""))
                    if x["estado"] != "pendiente_humano":
                        continue
                    if not _token():
                        st.caption("Inicia sesión de operador para resolver.")
                    elif x["aprobable"]:
                        a, b = st.columns(2)
                        if a.button("Aprobar", key=f"ap_{x['factura_id']}", type="primary", use_container_width=True):
                            _resolver(x["factura_id"], "aprobar")
                        if b.button("Rechazar", key=f"re_{x['factura_id']}", use_container_width=True):
                            _resolver(x["factura_id"], "rechazar")
                    else:
                        st.warning(x.get("accion_requerida") or "No aprobable: hay que volver a evaluar.")
                        if st.button("Volver a evaluar", key=f"ev_{x['factura_id']}", use_container_width=True):
                            _resolver(x["factura_id"], "reevaluar")


# ---------- D. Documento / evidencia ----------

def documento() -> None:
    estilo.hero("Documento y evidencia", "Lo que leyó el agente, lo que encontraron y lo que se decidió.",
                "Auditoría")
    factura_id = _elegir_factura("Factura")
    if not factura_id:
        return
    try:
        ev = cliente.get(f"/evidencia/{factura_id}", token=_token())
    except cliente.ErrorApi as error:
        _error(error)
        return
    if ev["acceso"] == "operador":
        d, f = ev["decision_final"], ev["factura"]
        st.caption("Vista de operador (paquete de evidencia completo, ya saneado).")
    else:
        d, f = ev["decision"], ev["factura"]
        estilo.chip(ev.get("origen", ""), "neutro")
    leido, hallado, decidido = st.columns(3, gap="medium")
    with leido:
        st.subheader("1 · Lo que leyó")
        estilo.ficha([("Proveedor", f.get("proveedor") or "—"), ("Número", f.get("numero_factura") or "—"),
                      ("Fecha", f.get("fecha_emision") or "—"),
                      ("Cuenta", f.get("cuenta_enmascarada") or f.get("cuenta_bancaria") or "—"),
                      ("Total", estilo.monto(float(f.get("total") or 0), f.get("moneda") or ""))])
        if f.get("lineas"):
            st.dataframe(f["lineas"], use_container_width=True, hide_index=True)
    with hallado:
        st.subheader("2 · Lo que encontraron")
        for h in d.get("hallazgos", []):
            with st.container(border=True):
                st.markdown(f"`{h.get('codigo', '')}` · severidad {h.get('severidad', '—')} · {h.get('agente')}")
                st.caption(str(h.get("motivo", "")))
        if not d.get("hallazgos"):
            st.success("Sin hallazgos: todas las reglas se cumplen.")
    with decidido:
        st.subheader("3 · Lo que se decidió")
        estilo.sello(d["decision"], d.get("codigo_principal", "OK"))
        if d.get("accion_requerida"):
            st.warning(f"Acción requerida: {d['accion_requerida']}")
        if ev["acceso"] == "publico":
            coincide = {True: "sí", False: "NO"}.get(ev["documento"]["coincide"], "no comprobado")
            estilo.ficha([("Cadena íntegra", "sí" if ev["cadena"]["integra"] else "NO"),
                          ("Cadena firmada", "sí" if ev["cadena"].get("firmada") else "no"),
                          ("Documento coincide con su hash", coincide)])
    if ev["acceso"] == "publico":
        with st.expander("Historial de la decisión"):
            st.dataframe(ev["historial"], use_container_width=True, hide_index=True)
    if ev["acceso"] == "operador":
        with st.expander("Paquete de evidencia completo"):
            st.json(ev)


# ---------- F. Reglas (solo lectura) ----------

def reglas() -> None:
    estilo.hero("Política de la empresa", "Solo lectura. El jurado no puede modificar límites ni el catálogo.",
                "Reglas deterministas")
    try:
        r = cliente.get("/reglas")
    except cliente.ErrorApi as error:
        _error(error)
        return
    with st.container(border=True):
        for frase in r["en_palabras"]:
            st.markdown(f"- {frase}")
    st.subheader("Proveedores dados de alta")
    st.dataframe(r["proveedores"], use_container_width=True, hide_index=True)
    st.caption(f"Versión de reglas {r['version'][:12]} · {r['empresa']}")
    with st.container(border=True):
        estilo.chip("SIMULACIÓN · no ejecuta pagos ni cambia la política", "aviso")
        st.subheader("Simulador de política")
        factura_id = _elegir_factura("Factura a simular")
        limite = st.number_input("Límite por pago hipotético (USD)", min_value=0.0, value=8000.0, step=500.0)
        if factura_id and st.button("Simular", type="primary"):
            try:
                s = cliente.post("/politica/simular", json={"factura_id": factura_id,
                                                            "cambios": {"limite_pago_usd": limite}})
                st.warning(s["advertencia"])
                st.markdown(f"Original: **{s['original']['decision']}** → simulada: **{s['simulada']['decision']}**")
                st.write(s["razon"])
            except cliente.ErrorApi as error:
                _error(error)


# ---------- E. Métricas y prueba del jurado ----------

def metricas() -> None:
    estilo.hero("Métricas y prueba del jurado", "Solo lo medido en el modo indicado. Sin garantías universales.",
                "Evidencia medible")
    modo = st.radio("Modo de medición", ["mock", "cache"], horizontal=True,
                    format_func={"mock": "MOCK (JSON canónicos)", "cache": "CACHÉ (documentos + caché)"}.get)
    try:
        with st.spinner("Midiendo con el cerebro real…"):
            m = cliente.get("/metricas", modo=modo)
    except cliente.ErrorApi as error:
        _error(error)
        return
    estilo.chip(f"{m['modo']} · ground truth {m['ground_truth']}", "aviso" if m["modo"] != "LIVE" else "acento")
    st.caption(m["descripcion_modo"])
    s = m["resumen"]
    estilo.kpis([("Falsos PAGAR en este dataset", s["falsos_pagar"], "FRENAR" if s["falsos_pagar"] else "PAGAR"),
                 ("Exactitud", f"{s['aciertos']}/{s['total']}", "acento"),
                 ("Autonomía medida", f"{s['autonomas']}/{s['total']}", "neutro"),
                 ("Pendientes de una persona", s.get("pendientes_humano", "—"), "ESCALAR")])
    estilo.barra(s.get("autonomia") or 0, f"Autonomía medida: {s['autonomas']} de {s['total']}")
    st.caption(f"Autonomía medida: {s['autonomas']} de {s['total']} facturas se resolvieron sin una persona.")
    izquierda, derecha = st.columns(2, gap="large")
    with izquierda:
        st.markdown("**Matriz de confusión** (filas = esperado, columnas = obtenido)")
        estilo.matriz(m["matriz"]["etiquetas"], m["matriz"]["filas"])
    with derecha:
        st.markdown("**Latencia medida (ms)**")
        st.dataframe([{"etapa": k, **v} for k, v in (m.get("latencia") or {}).items()],
                     use_container_width=True, hide_index=True)
    with st.expander("Detalle por factura"):
        st.dataframe(m["facturas"], use_container_width=True, hide_index=True)
    st.caption(f"Costo: {'medido' if m['costo']['medido'] else 'no medido'} — {m['costo']['motivo']}")
    a, b = st.columns(2)
    if a.button("Verificar cadena", use_container_width=True):
        v = cliente.get("/verificar")
        (st.success if v["integra"] and v["pagos_integros"] else st.error)(
            f"Cadena íntegra: {v['integra']} · pagos íntegros: {v['pagos_integros']}")
    if b.button("Paquete del jurado", use_container_width=True, disabled=not _token()):
        try:
            p = cliente.post("/paquete-jurado", token=_token())
            st.info(p["advertencia"])
            for x in p["resultados"]:
                st.markdown(f"{x['numero']} → **{x['decision']['decision']}** · "
                            f"{estilo.etiqueta_codigo(x['decision']['codigo_principal'])}")
        except cliente.ErrorApi as error:
            _error(error)


# ---------- G. Pantalla del pitch (se proyecta) ----------

# Solo para reconocer una URL que no es pública; no abre ningún puerto.
LOCALES = ("localhost", "127.0.0.1", "0.0.0.0")  # noqa: S104  # nosec B104


def _url_publica() -> tuple[str, bool]:
    """URL a la que apunta el QR: PUBLIC_URL o el Host con el que se abrió la pantalla (p. ej. el túnel)."""
    url = os.environ.get("PUBLIC_URL", "").strip().rstrip("/")
    if not url:
        try:
            cabeceras = st.context.headers
            host = cabeceras.get("Host") or ""
            proto = cabeceras.get("X-Forwarded-Proto") or ("https" if host.endswith(".trycloudflare.com") else "http")
        except Exception:  # noqa: BLE001 - sin contexto de navegador (pruebas)
            host = ""
        url = f"{proto}://{host}" if host else "http://localhost:8501"
    return url + "/", not any(local in url for local in LOCALES)


def pantalla() -> None:
    with st.container(key="pantalla_raiz"):
        estilo.hero("¿Puedes robarle a este agente?",
                    "Escanea el QR, falsifica la factura y envíala. Facturas 100 % ficticias: no hay pagos reales.",
                    "Róbale a mi agente · en vivo")
        url, publica = _url_publica()
        tablero_col, qr_col = st.columns([2.3, 1], gap="large")
        with qr_col:
            estilo.qr(url, f"Código QR para atacar: {url}")
            st.markdown('<div class="al-instruccion">📱 Escanea y roba</div>', unsafe_allow_html=True)
            st.caption(url)
            if not publica:
                st.warning("Esta URL solo funciona en esta máquina: inicia el túnel público "
                           "(docker compose --profile publico up) o define PUBLIC_URL.")
            token_jurado = os.environ.get("APROBADOR_JURADO_TOKEN")
            if _token() and token_jurado:
                if st.toggle("Mostrar QR del aprobador", key="mostrar_qr_aprobador"):
                    estilo.qr(f"{url}aprobar?clave={quote(token_jurado, safe='')}",
                              "QR del aprobador: abre la página para aprobar lo que escaló")
                    st.caption("QR del aprobador · quien lo escanee puede aprobar SOLO lo aprobable")

        @st.fragment(run_every=2)
        def tablero() -> None:
            try:
                e = cliente.get("/estado")
            except cliente.ErrorApi as error:
                _error(error)
                return
            with st.container(key="pantalla_kpis"):
                c1, c2, c3 = st.columns(3)
                c1.metric("Intentos de robo", e["intentos"])
                c2.metric("Pagos indebidos", e["pagos_fuera_de_reglas"])
                c3.metric("Frenados", e["frenados"])
            st.caption(f"{e['pagos_auditados']} pagos simulados, auditados de forma independiente. {e['auditoria']}")
            ultimo = e.get("ultimo")
            if ultimo:
                st.markdown("**Último veredicto**")
                estilo.sello(ultimo["decision"], ultimo["codigo_principal"], grande=True)
                st.write(ultimo["explicacion"])
            st.subheader("Últimos intentos")
            if not e["feed"]:
                st.caption("Todavía nadie ha falsificado una factura desde el QR.")
            estilo.feed(e["feed"])

        with tablero_col:
            tablero()


# ---------- H. Aprobador (jurado voluntario, 2.º QR) ----------

def aprobar() -> None:
    clave = st.query_params.get("clave")
    if clave:
        st.session_state["token"] = clave           # vive en la sesión del servidor, no en la URL
        del st.query_params["clave"]
    estilo.hero("Aprobación humana",
                "Solo puedes aprobar lo que las reglas permiten. Si cambiaron la cuenta o el proveedor, ni tú puedes.",
                "Persona en el circuito")
    if not _token():
        st.info("Escanea el QR del aprobador que aparece en la pantalla grande.")
        return
    try:
        items = cliente.get("/decisiones", limite=50)["items"]
    except cliente.ErrorApi as error:
        _error(error)
        return
    pendientes = [x for x in items if x["estado"] == "pendiente_humano"]
    st.caption("Aprobar registra una autorización simulada y auditada: no se transfiere dinero.")
    if st.button("Actualizar", key="j_actualizar"):
        st.rerun()
    if not pendientes:
        st.success("No hay nada pendiente de aprobar.")
    for x in pendientes:
        with st.container(border=True):
            estilo.chip(estilo.etiqueta_codigo(x["codigo_principal"]), "ESCALAR" if x["aprobable"] else "FRENAR")
            st.text(f"{x['proveedor']} · {x['numero_factura']}")
            st.markdown(f"**{estilo.monto(x['monto_original'], x['moneda'])}**")
            if x.get("contrafactual"):
                st.caption(x["contrafactual"])
            if x["aprobable"]:
                a, b = st.columns(2)
                if a.button("✅ Aprobar", key=f"jap_{x['factura_id']}", type="primary", use_container_width=True):
                    _resolver(x["factura_id"], "aprobar")
                if b.button("❌ Rechazar", key=f"jre_{x['factura_id']}", use_container_width=True):
                    _resolver(x["factura_id"], "rechazar")
            else:
                st.error("⛔ No se puede aprobar desde aquí.")
                st.warning(x.get("accion_requerida") or "Hay que volver a evaluar la factura.")
