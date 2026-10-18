# Guion de la demo: «Róbale a mi agente» (3 minutos)

**Reglas del guion:** no se inventan métricas. Solo se dicen números medidos en el modo indicado (MOCK o CACHÉ) y sobre el set de 15 facturas ficticias. Nada de pagos reales: PAGAR es una autorización simulada.

## Antes de subir al escenario (checklist)

1. `POST /admin/reiniciar-demo` con el token de admin, desde la terminal y nunca desde la pantalla del jurado. Comprobar que la respuesta diga saldo `8600.00` y `decisiones: 0`.
2. API y UI arriba. `/health` debe responder `estado: ok` y `modo_extraccion: solo caché`.
3. Iniciar sesión de operador en la UI del presentador (barra lateral). El jurado usa la UI pública, sin token.
4. Abrir la pestaña **Métricas** en modo **CACHÉ** y dejarla calculada.
5. Tener a mano el QR o la URL raíz de la UI (`/`; `/attack-lab` no existe: Streamlit sirve la página por defecto en la raíz) y el video de respaldo.

## Guion

| Tiempo | Pantalla | Qué se dice |
|---|---|---|
| 0:00–0:20 | La raíz de la UI (Attack Lab) en grande + QR | "Este agente de cuentas por pagar decide PAGAR, ESCALAR o FRENAR. Les damos permiso de intentar robarle, con facturas 100 % ficticias. No hay pagos reales." |
| 0:20–1:10 | Celular del jurado → Attack Lab | Un jurado elige **Cuenta bancaria cambiada** y pone su "cuenta". Resultado: **FRENAR · CUENTA_NO_REGISTRADA · no aprobable**. "Ni siquiera una persona puede aprobarlo desde la factura: el cambio de cuenta va por un proceso administrativo verificado." Otro jurado prueba **Instrucción maliciosa** y obtiene **FRENAR · INYECCION**: "el texto de un documento es dato, no orden". |
| 1:10–1:40 | Comité en vivo | Las cinco tarjetas con los eventos reales de esa factura. "Los modelos detectan, la regla decide, el humano firma. Ningún agente puede bajar la severidad." |
| 1:40–2:10 | Bandeja | **Monto inflado** queda en ESCALAR aprobable. El presentador lo aprueba: PAGAR (simulado). Si alguien vuelve a apretar Aprobar, la API lo rechaza: no se paga dos veces. Si alguien intenta aprobar un FRENAR por la API, recibe 409. |
| 2:10–2:40 | Métricas (CACHÉ) | Leer **lo que dice la pantalla**: modo CACHÉ, 15 documentos del set, falsos PAGAR **en este dataset**, exactitud, autonomía medida y matriz 3×3. "Costo: no medido." No extrapolar a "nunca se equivoca". |
| 2:40–3:00 | Verificar cadena | "Cada decisión queda encadenada por hash y firmada. Si alguien altera el registro, la cadena se rompe y no se aprueba nada." |

**Frases que NO se dicen:** "detecta todo el fraude", "cumple normativa X", "procesa pagos reales", "funciona con cualquier factura del mundo", "0 errores garantizados".

## Plan B

| Si falla… | Hacer… |
|---|---|
| El celular del jurado o la red | El presentador hace los ataques desde su propia UI (mismos presets) |
| Hay que mostrar los casos del set | **Paquete del jurado** (pestaña Métricas, con sesión de operador) **justo después de reiniciar**. Si ya hubo pagos en el ensayo, el saldo bajó y algunas facturas frenan por saldo: es correcto, pero cambia la matriz |
| Un modelo o API externa (Jev, extractores) | No se usan por defecto: la demo corre sin red de modelos. Un documento nuevo sin extracción LIVE autorizada escala, y eso se muestra como fail-closed |
| La API cae | Video de respaldo y capturas de Métricas y del Comité |
| La demo quedó "sucia" | `POST /admin/reiniciar-demo` (admin, terminal) y volver al paso 1 |
