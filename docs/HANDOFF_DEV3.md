# Handoff a Dev 3: Attack Lab (API + UI)

| | |
|---|---|
| **Autoría** | Dev 2 (cerebro e integración), como **anticipo** del alcance de Dev 3 |
| **Estado de revisión** | **PENDIENTE**: Dev 3 debe auditar, mejorar y completar |
| **Rama** | `feat/attack-lab-dev2-handoff` (worktree `../robale-attack-lab`), creada desde `feat/dev2-cerebro` @ `40bebdf` (G4) |
| **Remoto** | Nada se publicó. PR #1 de Dev 1 sigue abierto; no hay push ni merge |

El reto termina en la decisión **PAGAR / ESCALAR / FRENAR**. No hay pagos reales, cuentas reales ni integración bancaria: PAGAR es una autorización **simulada**.

## 1. Arquitectura

```
Navegador (jurado, celular)
   │  HTTP
   ▼
Streamlit  app/ui/  (proyecto uv aparte: Streamlit exige pillow<13)
   │  HTTP interno (API_URL). Nunca abre la base ni la clave de firma.
   ▼
FastAPI  app/api.py  →  app/servicios.py  ─┬─  cerebro (Dev 2): decidir_async, reanudar_async, reevaluar_async,
   UN proceso, UN worker, un candado de     │   reiniciar_demo, paquete_evidencia, verificar_cadena, vista_publica
   escritura (SQLite con un solo escritor)  └─  extraccion (Dev 1): extraer()  (solo para /ingest)
   │
   ▼
DB_PATH (SQLite), DB_BASE_PATH (base controlada para reiniciar), SIGNING_KEY_PATH (Ed25519)
```

| Archivo | Rol |
|---|---|
| `app/api.py` | Rutas, autenticación por rol, cuotas, CORS, cabeceras de seguridad, errores en español. Se arranca con `uvicorn --factory app.api:crear_app`: importar el módulo no abre ninguna base |
| `app/servicios.py` | Adaptador sobre el backend real. Toda decisión sale del cerebro; las salidas son vistas saneadas |
| `app/sintetico.py` | Modo **«DATOS SINTÉTICOS — EVALUACIÓN REAL DEL CEREBRO»**: presets, validación y reconstrucción de la `FacturaCanonica` |
| `app/documentos.py` | Modo **«SUBIR DOCUMENTO»**: validación del archivo, guardado seguro y extracción honesta (caché o LIVE autorizado) |
| `app/seguridad.py` | Tokens Bearer (SHA-256, comparación en tiempo constante) y limitador por ventana deslizante |
| `app/config.py` | Variables de entorno de la app |
| `app/ui/` | Streamlit: `ui.py` (navegación), `paginas.py`, `estilo.py`, `cliente.py`, `tests/` |
| `docker/`, `docker-compose.yml` | Solo desarrollo local |

## 2. Dos modos de análisis, sin engañar

**1. Datos sintéticos** (`POST /simular`). El jurado edita los datos de negocio de una factura ficticia.
- El servidor acepta **solo** esos campos (`extra="forbid"`). Si el cliente envía `extraccion_ok`, `texto_oculto`, `id_documento`, `codigo_principal`, `decision`, `aprobable`, `total` o `diferencias`, recibe un 422 y no se registra ninguna decisión.
- Recalcula en `Decimal` los totales de cada línea, el subtotal y el total.
- `id_documento` es el SHA-256 del documento sintético reconstruido (incluye la sesión), nunca el de un archivo del set.
- La nota se pasa como `texto_libre`, es decir, como dato no confiable. La revisa el detector de seguridad real.
- No es OCR ni lectura por modelo, y la UI lo dice.

**2. Documento** (`POST /ingest`).
- Formatos PDF, PNG, JPG, EML y TXT; máximo 10 MB (`APP_MAX_UPLOAD_MB`). Se comprueba la firma mágica.
- Se guarda en `entrada/<sha256><ext>` con un nombre puesto por el servidor; el nombre del cliente nunca forma parte de la ruta.
- Luego `extraer()` de Dev 1, y después `decidir_async`.
- **Por defecto no se llama a ningún modelo:** se usan extractores que fallan si se les llama, más la caché de solo lectura. La etiqueta es honesta:

| Etiqueta | Cuándo |
|---|---|
| `CACHÉ` | Todo salió de `cache/` |
| `SIN_EXTRACCION` | Documento nuevo y extracción LIVE no autorizada: ESCALAR no aprobable |
| `LIVE` | Solo con `ATTACK_LAB_EXTRACCION_LIVE=1` **y** si algún modelo respondió (cuesta dinero) |

## 3. API

Los errores siempre tienen la forma `{"error": <código>, "mensaje": <texto en español>, ...}`.

| Método y ruta | Acceso | Notas |
|---|---|---|
| `GET /health` | Público | Estado, versión, `revision_dev3`, cadena íntegra, modo de extracción y capa semántica. Sin secretos ni rutas |
| `GET /presets`, `GET /presets/{nombre}` | Público | `limpia`, `cuenta_cambiada`, `proveedor_nuevo`, `monto_inflado`, `duplicado`, `instruccion_maliciosa` |
| `POST /simular` | Público, con cuota | 20/min por IP y 60/h por `sesion_id`. Devuelve `intento_id`, `modo_analisis`, `decision` (= `vista_publica`), `regla_principal`, `factura`, `advertencia` |
| `POST /ingest` | Público, con cuota | Multipart `archivo` + `canal`. 5/min por IP. Añade `fuente_extraccion` |
| `GET /intentos/{intento_id}` | Público | Etapa real: `recibido` → `extrayendo` → `evaluando` → `decidido` (en memoria) |
| `GET /decisiones?limite&desplazamiento` | Público | Última decisión de cada factura, vista pública enmascarada, con `origen` |
| `GET /eventos/{factura_id}` | Público | Solo los eventos persistidos por el cerebro. Si aún no existen, `estado: "procesando"` |
| `GET /evidencia/{factura_id}` | Público restringido / operador | Sin token: decisión, regla principal, factura enmascarada, documento y su hash, cadena, historial. Con token: `paquete_evidencia()` completo (ya saneado) |
| `GET /reglas` | Público | Solo lectura: límites, frases y proveedores con la cuenta enmascarada |
| `POST /politica/simular` | Público, con cuota | Sandbox de solo lectura del cerebro |
| `GET /metricas?modo=mock\|cache` | Público | `cerebro.medir`. **LIVE nunca se lanza desde la API** |
| `GET /verificar` | Público | Cadena y registro de pagos |
| `POST /aprobar/{id}`, `POST /rechazar/{id}` | Bearer `aprobador` | Cabecera `Idempotency-Key` opcional. La identidad debe estar en `CEREBRO_APROBADORES` |
| `POST /reevaluar/{id}` | Bearer `aprobador` o `admin` | Nueva validación completa; no paga |
| `POST /paquete-jurado` | Bearer `aprobador` o `admin` | Plan B: las 6 facturas del jurado desde los JSON canónicos. No crea pagos ni duplica decisiones; **el resultado depende del saldo actual: usarlo justo después de reiniciar** |
| `POST /admin/reiniciar-demo` | Bearer `admin` | La identidad debe estar en `CEREBRO_ADMINS`. **Nunca es público.** No está en la UI del jurado |

**Códigos HTTP:**

| Código | Significado |
|---|---|
| 401 | Sin token o token inválido |
| 403 | Rol sin permiso, o identidad no autorizada por el cerebro |
| 404 | No existe |
| 409 | `no_aprobable` (con `codigo` y `accion_requerida`), conflicto, doble aprobación o reinicio ocupado |
| 413 | Archivo demasiado grande |
| 415 | Tipo o contenido no permitido |
| 422 | Datos inválidos (detalle por campo, en español) |
| 423 | Registro alterado |
| 429 | Demasiados intentos |
| 503 | Hay que volver a evaluar |

**Control de aprobación, doble:**
- La API no aprueba si la última decisión es pendiente y `aprobable=false`.
- Además, `cerebro.reanudar` recalcula la autorización en el servidor.
- La UI nunca envía `aprobable`, y una llamada directa a la API tampoco puede saltarse el control.

## 4. Pantallas (Streamlit)

- **Navegación:** Attack Lab (`/attack-lab`), Comité en vivo, Bandeja, Documento, Reglas (lectura) y Métricas.
- **Barra lateral:** estado de la API e inicio de sesión de operador. El token se escribe a mano y se guarda en la sesión **del servidor** de Streamlit; no queda en el navegador ni en el HTML.

| Pantalla | Qué hace |
|---|---|
| **A. Attack Lab** | Seis presets editables, formulario, vista previa ("el servidor recalcula todo") y botón «Intentar el ataque». Muestra decisión, código, si es aprobable, acción requerida, regla principal, evidencia permitida y montos. Pestaña para subir documentos |
| **B. Comité** | Cinco tarjetas con los eventos **reales**: "procesando…" mientras no existen, sin tiempos ni probabilidades inventados. Llave de reglas y sello. Actualización opcional cada 2 s |
| **C. Bandeja** | PAGAR (simulado), ESCALAR pendiente y FRENAR. Aprobar/Rechazar **solo** si está pendiente, es aprobable y hay sesión de operador. Si no es aprobable, muestra la acción requerida y «Volver a evaluar» |
| **D. Documento** | Datos estructurados (no se renderiza el archivo subido), cuenta enmascarada, hallazgos con códigos, cadena e historial. Para el operador, el paquete completo |
| **E. Métricas** | MOCK o CACHÉ con su etiqueta, falsos PAGAR **en ese dataset**, exactitud, autonomía medida, matriz 3×3, costo "no medido", Verificar cadena y Paquete del jurado |
| **F. Reglas** | Solo lectura, más el simulador de política con su advertencia |

Seguridad de la UI: el HTML propio solo lleva valores de lista blanca o escapados con `html.escape`. El texto de la API o del jurado se muestra con componentes que escapan el contenido.

## 5. Variables de entorno

Además de las del cerebro (`DB_PATH`, `DB_BASE_PATH`, `SIGNING_KEY_PATH`, `CEREBRO_APROBADORES`, `CEREBRO_ADMINS`, `CEREBRO_SEMANTICA`… ver `cerebro/README.md` §7):

| Variable | Uso |
|---|---|
| `APP_APROBADOR_TOKENS` | `identidad=token,...`. Token de 24 caracteres o más. La identidad **también** debe estar en `CEREBRO_APROBADORES` |
| `APP_ADMIN_TOKENS` | Igual; la identidad debe estar en `CEREBRO_ADMINS` |
| `APP_CORS_ORIGINS` | Por defecto, solo la UI local (:8501) |
| `APP_MAX_UPLOAD_MB` | 10 por defecto, con tope de 20 |
| `APP_ENTRADA_DIR` | Carpeta de archivos subidos |
| `ATTACK_LAB_EXTRACCION_LIVE=1` | Autoriza extracción con modelos reales. **Cuesta dinero**; desactivado por defecto |
| `APP_CONFIAR_EN_PROXY=1` | Usa `X-Forwarded-For` para las cuotas, solo detrás de un proxy propio |
| `API_URL` | Lo usa la UI para encontrar la API |

## 6. Cómo correrlo y qué se verificó

```bash
# API (raíz del repo)
uv sync --locked
DB_PATH=./blinka_demo.db CEREBRO_APROBADORES=tg:111 CEREBRO_ADMINS=admin:ops \
APP_APROBADOR_TOKENS="tg:111=<token-largo>" APP_ADMIN_TOKENS="admin:ops=<token-largo>" \
uv run uvicorn --factory app.api:crear_app --host 127.0.0.1 --port 8000 --workers 1

# UI (proyecto aparte)
cd app/ui && uv sync --locked && API_URL=http://127.0.0.1:8000 uv run streamlit run ui.py --server.port 8501
# → http://127.0.0.1:8501/attack-lab

# Reinicio de la demo (solo admin; no hay botón en la UI del jurado)
curl -X POST -H "Authorization: Bearer <token-admin>" http://127.0.0.1:8000/admin/reiniciar-demo
```

**Tests:**
- Raíz: `uv run pytest -q` cubre los 619 de G4 más los 48 de la API (`tests/test_app_api.py`).
- UI: `cd app/ui && uv run pytest -q` da 3 passed más 1 E2E, que se activa con `ATTACK_LAB_API_URL`.

**Smoke local (2026-10-17):** uvicorn en `127.0.0.1:8000` y Streamlit en `127.0.0.1:8501/attack-lab` (HTTP 200).

| Caso | Resultado |
|---|---|
| Factura limpia | PAGAR |
| Cuenta cambiada | FRENAR `CUENTA_NO_REGISTRADA` |
| Proveedor nuevo | FRENAR `PROVEEDOR_NO_PERMITIDO` |
| Monto inflado | ESCALAR `LIMITE_PAGO` aprobable |
| Duplicado | FRENAR `DUPLICADO_EXACTO` |
| Instrucción maliciosa | FRENAR `INYECCION` |
| Aprobar un FRENAR | 409 |
| Aprobar ESCALAR / segunda aprobación | 200 PAGAR / 409 |
| Falsificar `extraccion_ok` | 422 |
| Métricas CACHÉ | 15/15, 0 falsos PAGAR, autonomía 11/15 |
| E2E de la UI contra la API real | Passed |

Los logs no contenían tokens ni cuentas completas.

**Docker:** `docker compose config` es válido, pero las imágenes **no se construyeron** porque el daemon de Docker Desktop no estaba corriendo en esta máquina.

## 7. Problemas conocidos y límites (revisar, Dev 3)

1. **Cuotas, progreso y etiquetas de origen viven en memoria** del único proceso API: se pierden al reiniciarlo. El origen se recupera de `factura.archivo`; la fuente de extracción (CACHÉ/LIVE) no.
2. **Un solo proceso y un solo worker.** Si se agrega un bot de Telegram, debe llamar a esta API y no abrir la base.
3. **Los eventos del comité se escriben al final** de cada decisión, todos juntos. La UI muestra "procesando" hasta que existen; no hay animación por agente en tiempo real.
4. **Los ataques sintéticos consumen saldo real de la demo** cuando terminan en PAGAR. Dos facturas "limpias" con el mismo monto y proveedor pueden escalar como posible duplicado: es comportamiento correcto del cerebro. Usar `/admin/reiniciar-demo` entre ensayos.
5. **El paquete del jurado depende del saldo actual.** Para obtener la matriz del set, correrlo justo después de reiniciar.
6. **Validación en Streamlit:** los errores 422 muestran el detalle por campo. Falta probarla a fondo en celulares reales.
7. **No hay exportación CSV.** Si Dev 3 la agrega, debe neutralizar celdas que empiecen con `= + - @` (inyección CSV).
8. **Reglas solo en lectura.** La edición con versionado para administradores no está implementada.
9. **Pendientes:** bot de Telegram, despliegue en la nube, video de respaldo, accesibilidad (contraste AA medido, navegación con teclado), y la prueba LIVE de Jev y de los extractores (cuestan dinero y requieren autorización).
10. **Coordinación:** cambió `pyproject.toml` (FastAPI, Uvicorn, multipart; httpx en dev), pero pillow sigue en 13.0.0. `app/ui` tiene su propio `uv.lock`.

## 8. Lista de revisión para Dev 3

- [ ] Leer `app/api.py` y `app/servicios.py`; confirmar que ninguna ruta devuelve la evidencia cruda a un jurado.
- [ ] Probar los seis presets desde un celular (`/attack-lab`) contra `uvicorn` local.
- [ ] Intentar aprobar un FRENAR por la API y por la UI: debe ser imposible.
- [ ] Revisar la estética y la accesibilidad (`app/ui/estilo.py`) en la pantalla del pitch.
- [ ] Construir con Docker (`docker compose up --build`) con Docker Desktop encendido.
- [ ] Decidir si Telegram reutiliza `/simular` o `/ingest` (recomendado) y cómo se autentican los aprobadores (`chat_id` en `APP_APROBADOR_TOKENS` / `CEREBRO_APROBADORES`).
