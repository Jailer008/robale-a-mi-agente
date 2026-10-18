"""Attack Lab · UI Streamlit. Arranque: uv run --project app/ui streamlit run app/ui/ui.py

Autoría: Dev 2 (anticipo del alcance de Dev 3) · revisión de Dev 3 PENDIENTE.
La UI no abre la base ni la clave de firma: consume la API (API_URL).
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cliente  # noqa: E402
import estilo  # noqa: E402
import paginas  # noqa: E402
import streamlit as st  # noqa: E402

st.set_page_config(page_title="Attack Lab · Róbale a mi agente", page_icon="🛡️", layout="wide",
                   initial_sidebar_state="collapsed")
estilo.aplicar()
st.session_state.setdefault("sesion_id", uuid.uuid4().hex[:24])

with st.sidebar:
    st.markdown("### 🛡️ Róbale a mi agente")
    try:
        salud = cliente.get("/health")
        st.caption(f"API {salud['version']} · extracción: {salud['modo_extraccion']} · "
                   f"capa semántica: {salud['capa_semantica']}")
    except Exception:  # noqa: BLE001 - la UI debe seguir mostrando algo útil
        st.error("La API no responde. Plan B: video y capturas.")
    st.caption("Facturas 100 % ficticias. No hay pagos reales.")
    st.divider()
    with st.expander("Acceso de operador", expanded=bool(st.session_state.get("token"))):
        st.caption("Aprobaciones y paquete del jurado")
        if st.session_state.get("token"):
            st.success("Sesión de operador activa")
            if st.button("Cerrar sesión de operador"):
                st.session_state.pop("token", None)
                st.rerun()
        else:
            token = st.text_input("Token de operador", type="password", key="token_entrada")
            if st.button("Entrar") and token:
                st.session_state["token"] = token            # vive en la sesión del servidor de Streamlit
                st.session_state.pop("token_entrada", None)
                st.rerun()

navegacion = st.navigation([
    st.Page(paginas.attack_lab, title="Attack Lab", icon="🎯", url_path="attack-lab", default=True),
    st.Page(paginas.pantalla, title="Pantalla", icon="📺", url_path="pantalla"),
    st.Page(paginas.aprobar, title="Aprobar", icon="✅", url_path="aprobar"),
    st.Page(paginas.comite, title="Comité", icon="🧠", url_path="comite"),
    st.Page(paginas.bandeja, title="Bandeja", icon="📥", url_path="bandeja"),
    st.Page(paginas.documento, title="Documento", icon="📄", url_path="documento"),
    st.Page(paginas.reglas, title="Reglas", icon="📏", url_path="reglas"),
    st.Page(paginas.metricas, title="Métricas", icon="📊", url_path="metricas"),
], position="top")
navegacion.run()
