"""Pantallas del Attack Lab. Todo dato viene de la API (que usa el cerebro real); nada se inventa aquí.

Autoría: Dev 2 (anticipo del alcance de Dev 3) · revisión de Dev 3 PENDIENTE.
"""

from __future__ import annotations

import datetime as dt
import uuid

import cliente
import estilo
import streamlit as st

PRESETS = {"limpia": "Factura limpia", "cuenta_cambiada": "Cuenta bancaria cambiada",
           "proveedor_nuevo": "Proveedor nuevo", "monto_inflado": "Monto inflado",
           "duplicado": "Factura duplicada", "instruccion_maliciosa": "Instrucción maliciosa"}
MONEDAS = ["USD", "COP", "MXN", "ARS", "PEN", "EUR"]


def _token() -> str | None:
    return st.session_state.get("token") or None


def _error(error: cliente.ErrorApi) -> None:
    st.error(f"{error}")
    detalle = error.cuerpo.get("detalle")
    if detalle:
        st.caption("; ".join(f"{d.get('campo')}: {d.get('problema')}" for d in detalle[:6]))
    if error.cuerpo.get("accion_requerida"):
        st.info(f"Acción requerida: {error.cuerpo['accion_requerida']}")


def _resultado(r: dict) -> None:
    d = r["decision"]
    estilo.chip(r.get("modo_analisis", ""))
    estilo.sello(d["decision"], d["codigo_principal"])
    c1, c2, c3 = st.columns(3)
    c1.metric("Monto", estilo.monto(d["monto_original"], d["moneda"]))
    c2.metric("Monto USD", estilo.monto(d["monto_usd"], "USD"))
    c3.metric("¿Aprobable por una persona?", "Sí" if d["aprobable"] else "No")
    if d.get("accion_requerida"):
        st.warning(f"Acción requerida: {d['accion_requerida']}")
    regla = r.get("regla_principal") or {}
    st.write(f"**Regla o agente principal:** {regla.get('tipo', '—')} · {regla.get('nombre', '—')} "
             f"({estilo.etiqueta_codigo(regla.get('codigo', 'OK'))})")
    st.write(f"**Explicación:** {d['explicacion']}")
    if d.get("contrafactual"):
        st.caption(f"Contrafactual: {d['contrafactual']}")
    if d["hallazgos"]:
        st.write("**Evidencia permitida (motivos con código estable):**")
        for h in d["hallazgos"]:
            st.write(f"- `{h['codigo']}` · severidad {h['severidad']} · {h['agente']}: {h['motivo']}")
    st.caption(f"{r.get('advertencia', '')} · factura_id {d['factura_id'][:12]}…")


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


def _falsificar() -> None:
    """Modo principal (plan v2): el jurado edita y raya; el servidor dibuja el PDF y el agente lo LEE."""
    st.session_state.setdefault("sesion_id", uuid.uuid4().hex[:24])
    if "base_f" not in st.session_state:
        _cargar_base()
    base = st.session_state.get("base_f")
    if not base:
        return
    estilo.chip(base["etiqueta_modo"])
    st.markdown(f"💡 {base['pista']}")
    st.markdown(f"**{base['proveedor']}** · factura {base['numero']} · "
                f"{estilo.monto(base['total'], base['moneda'])} · cuenta {base['cuenta_enmascarada']}")
    if st.session_state.get("preview_f"):
        estilo.imagen_png(st.session_state["preview_f"],
                          f"Vista previa de la factura {base['numero']} de {base['proveedor']}: total "
                          f"{estilo.monto(base['total'], base['moneda'])}, cuenta {base['cuenta_enmascarada']}")
        st.caption("La factura que recibiste")
    if st.button("Dame otra factura", key="f_otra"):
        _cargar_base()
        st.session_state.pop("resultado_f", None)
        st.rerun()

    with st.form("falsificar"):
        st.caption("Deja vacío lo que no quieras cambiar. El servidor vuelve a dibujar la factura y el agente "
                   "lee el documento, no este formulario.")
        c1, c2 = st.columns(2)
        monto = c1.number_input(f"Nuevo total ({base['moneda']})", min_value=0.0, max_value=1_000_000_000.0,
                                value=None, placeholder=f"{base['total']:,.2f}", key="f_monto")
        cuenta = c2.text_input("Cuenta bancaria", max_chars=40, key="f_cuenta",
                               placeholder="Inventa una, p. ej. ATACANTE-1234",
                               help="Inventa una cuenta. No pongas la tuya real.")
        proveedor = c1.text_input("Proveedor", max_chars=40, key="f_proveedor", placeholder=base["proveedor"])
        numero = c2.text_input("Número de factura", max_chars=40, key="f_numero",
                               placeholder="p. ej. FV-0192 (ya pagada)")
        nota = st.text_area("Nota al agente", max_chars=200, key="f_nota",
                            placeholder="Escríbele una orden al agente…")
        oculta = st.checkbox("Esconder la nota (texto blanco diminuto)", key="f_oculta")
        rayar = st.multiselect("Rayar encima de…", list(RAYABLE), format_func=RAYABLE.get, key="f_rayar")
        enviar = st.form_submit_button("Enviar y robar", use_container_width=True)
    if enviar:
        cambios: dict = {}
        if monto is not None:
            cambios["monto"] = float(monto)
        for campo, valor in (("cuenta", cuenta), ("proveedor", proveedor), ("numero", numero)):
            if valor.strip():
                cambios[campo] = valor.strip()
        if nota.strip():
            cambios["nota"] = nota.strip()
            if oculta:
                cambios["nota_oculta"] = True
        datos = {"sesion_id": st.session_state["sesion_id"], "base_id": base["base_id"], "cambios": cambios}
        if rayar:
            datos["rayar"] = rayar
        try:
            with st.spinner("El agente está leyendo tu factura…"):
                r = cliente.post("/falsificar", json=datos)
            st.session_state["resultado_f"] = r
            st.session_state["ultimo_id"] = r["decision"]["factura_id"]
        except cliente.ErrorApi as error:
            _error(error)
    r = st.session_state.get("resultado_f")
    if r:
        cambiados = ", ".join(r.get("campos_cambiados") or []) or "nada (la enviaste tal cual)"
        st.markdown(f"**Lo que cambiaste:** {cambiados} · lectura: {r.get('fuente_extraccion', '—')}")
        _resultado(r)


def attack_lab() -> None:
    estilo.hero("¿Puedes engañar al agente?", "Prueba con facturas 100 % ficticias. No hay pagos reales.")
    falsificada, sintetico, documento = st.tabs(["Falsificar la factura", "Editar datos (sintético)",
                                                 "Subir un documento"])
    with falsificada:
        _falsificar()
    with sintetico:
        estilo.chip("DATOS SINTÉTICOS — EVALUACIÓN REAL DEL CEREBRO")
        elegido = st.segmented_control("Elige un ataque", list(PRESETS), format_func=PRESETS.get,
                                       key="preset_elegido", default=None)
        if elegido and elegido != st.session_state.get("preset_cargado"):
            st.session_state["preset_cargado"] = elegido
            _cargar_preset(elegido)
        caso = st.session_state.get("caso")
        if not caso:
            st.info("Elige un ataque para cargar una factura ficticia editable.")
            return
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
            enviar = st.form_submit_button("Intentar el ataque", use_container_width=True)
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
            _resultado(st.session_state["resultado"])
    with documento:
        st.caption("PDF, PNG, JPG, EML o TXT, máximo 10 MB. Sin extracción LIVE autorizada, un documento nuevo "
                   "se escala de forma honesta (no se inventa una lectura).")
        archivo = st.file_uploader("Factura", type=["pdf", "png", "jpg", "jpeg", "eml", "txt"])
        canal = st.selectbox("Canal", ["web", "telegram", "email", "chat"])
        if archivo is not None and st.button("Analizar documento", use_container_width=True):
            try:
                with st.spinner("Leyendo y evaluando…"):
                    r = cliente.subir(archivo.name, archivo.getvalue(), canal)
                st.session_state["ultimo_id"] = r["decision"]["factura_id"]
                _resultado(r)
            except cliente.ErrorApi as error:
                _error(error)


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
    estilo.hero("Comité en vivo", "Cinco agentes revisan cada factura. Solo pueden endurecer la decisión.")
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
        columnas = st.columns(5)
        for columna, nombre in zip(columnas, estilo.AGENTES, strict=True):
            with columna:
                estilo.tarjeta_agente(nombre, por_agente.get(nombre))
        if datos["estado"] != "listo":
            st.info(f"Procesando… (etapa real: {datos.get('etapa') or 'pendiente'})")
            return
        llave = por_agente.get("reglas")
        st.write(f"**Llave de reglas:** {'DENY' if llave and llave['severidad'] else 'ALLOW'}")
        d = evidencia["decision"]
        estilo.sello(d["decision"], d["codigo_principal"])
        st.write(d["explicacion"])

    st.toggle("Actualizar en vivo", key="en_vivo")
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
    estilo.hero("Bandeja", "PAGAR es una autorización simulada. Solo lo pendiente y aprobable se puede aprobar.")
    try:
        items = cliente.get("/decisiones", limite=100)["items"]
    except cliente.ErrorApi as error:
        _error(error)
        return
    columnas = st.columns(3)
    grupos = [("PAGAR (simulado)", [x for x in items if x["decision"] == "PAGAR"]),
              ("ESCALAR pendiente", [x for x in items if x["estado"] == "pendiente_humano"]),
              ("FRENAR", [x for x in items if x["decision"] == "FRENAR"])]
    for columna, (titulo, lista) in zip(columnas, grupos, strict=True):
        with columna:
            st.subheader(f"{titulo} · {len(lista)}")
            for x in lista:
                with st.container(border=True):
                    st.write(f"**{x['proveedor']}** · {x['numero_factura']}")
                    st.write(f"{estilo.monto(x['monto_original'], x['moneda'])} · "
                             f"{estilo.etiqueta_codigo(x['codigo_principal'])}")
                    st.caption(x.get("origen", ""))
                    if x["estado"] != "pendiente_humano":
                        continue
                    if not _token():
                        st.caption("Inicia sesión de operador para resolver.")
                    elif x["aprobable"]:
                        a, b = st.columns(2)
                        if a.button("Aprobar", key=f"ap_{x['factura_id']}"):
                            _resolver(x["factura_id"], "aprobar")
                        if b.button("Rechazar", key=f"re_{x['factura_id']}"):
                            _resolver(x["factura_id"], "rechazar")
                    else:
                        st.warning(x.get("accion_requerida") or "No aprobable: hay que volver a evaluar.")
                        if st.button("Volver a evaluar", key=f"ev_{x['factura_id']}"):
                            _resolver(x["factura_id"], "reevaluar")


# ---------- D. Documento / evidencia ----------

def documento() -> None:
    estilo.hero("Documento y evidencia", "Cuenta enmascarada, motivos con códigos estables y evidencia del veto.")
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
        estilo.chip(ev.get("origen", ""))
    estilo.sello(d["decision"], d.get("codigo_principal", "OK"))
    izquierda, derecha = st.columns(2)
    with izquierda:
        st.subheader("Datos de la factura")
        st.write(f"**Proveedor:** {f.get('proveedor')}  \n**Número:** {f.get('numero_factura')}  \n"
                 f"**Fecha:** {f.get('fecha_emision')}  \n"
                 f"**Cuenta:** {f.get('cuenta_enmascarada') or f.get('cuenta_bancaria') or '—'}")
        st.dataframe(f.get("lineas", []), use_container_width=True)
        st.write(f"**Total:** {estilo.monto(float(f.get('total') or 0), f.get('moneda') or '')}")
    with derecha:
        st.subheader("Comparación con las reglas")
        for h in d.get("hallazgos", []):
            st.write(f"- `{h.get('codigo', '')}` · {h.get('agente')}: {h.get('motivo')}")
        if not d.get("hallazgos"):
            st.write("Sin hallazgos: todas las reglas se cumplen.")
        if ev["acceso"] == "publico":
            st.write(f"**Cadena íntegra:** {'sí' if ev['cadena']['integra'] else 'NO'} · "
                     f"**Documento coincide con su hash:** {ev['documento']['coincide']}")
            st.dataframe(ev["historial"], use_container_width=True)
    if ev["acceso"] == "operador":
        with st.expander("Paquete de evidencia completo"):
            st.json(ev)


# ---------- F. Reglas (solo lectura) ----------

def reglas() -> None:
    estilo.hero("Política de la empresa", "Solo lectura. El jurado no puede modificar límites ni el catálogo.")
    try:
        r = cliente.get("/reglas")
    except cliente.ErrorApi as error:
        _error(error)
        return
    for frase in r["en_palabras"]:
        st.write(f"- {frase}")
    st.dataframe(r["proveedores"], use_container_width=True)
    st.caption(f"Versión de reglas {r['version'][:12]} · {r['empresa']}")
    st.subheader("Simulador de política (no ejecuta nada)")
    factura_id = _elegir_factura("Factura a simular")
    limite = st.number_input("Límite por pago hipotético (USD)", min_value=0.0, value=8000.0, step=500.0)
    if factura_id and st.button("Simular"):
        try:
            s = cliente.post("/politica/simular", json={"factura_id": factura_id,
                                                        "cambios": {"limite_pago_usd": limite}})
            st.warning(s["advertencia"])
            st.write(f"Original: **{s['original']['decision']}** → simulada: **{s['simulada']['decision']}**")
            st.write(s["razon"])
        except cliente.ErrorApi as error:
            _error(error)


# ---------- E. Métricas y prueba del jurado ----------

def metricas() -> None:
    estilo.hero("Métricas y prueba del jurado", "Solo lo medido en el modo indicado. Sin garantías universales.")
    modo = st.radio("Modo de medición", ["mock", "cache"], horizontal=True,
                    format_func={"mock": "MOCK (JSON canónicos)", "cache": "CACHÉ (documentos + caché)"}.get)
    try:
        with st.spinner("Midiendo con el cerebro real…"):
            m = cliente.get("/metricas", modo=modo)
    except cliente.ErrorApi as error:
        _error(error)
        return
    estilo.chip(f"{m['modo']} · ground truth {m['ground_truth']}")
    st.caption(m["descripcion_modo"])
    s = m["resumen"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Falsos PAGAR en este dataset", s["falsos_pagar"])
    c2.metric("Exactitud", f"{s['aciertos']}/{s['total']}")
    c3.metric("Autonomía medida", f"{s['autonomas']}/{s['total']}")
    st.write("**Matriz de confusión (filas = esperado, columnas = obtenido)**")
    st.dataframe([{"esperado": e, **m["matriz"]["filas"][e]} for e in m["matriz"]["etiquetas"]],
                 use_container_width=True)
    st.dataframe(m["facturas"], use_container_width=True)
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
                st.write(f"{x['numero']} → **{x['decision']['decision']}** · "
                         f"{estilo.etiqueta_codigo(x['decision']['codigo_principal'])}")
        except cliente.ErrorApi as error:
            _error(error)
