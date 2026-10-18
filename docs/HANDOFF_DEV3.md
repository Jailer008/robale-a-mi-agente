# Handoff a Dev 3: Attack Lab (API + UI)

| | |
|---|---|
| **Autoría** | Dev 2 (cerebro e integración), como **anticipo** del alcance de Dev 3 |
| **Estado de revisión** | **EN CURSO** (Dev 3, 2026-10-18): integración con Dev 1 v2, modo «factura falsificada», Docker corregido. Ver §9 |
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

## 2. Tres modos de análisis, sin engañar

**0. Factura falsificada** (`POST /falsificar`, **modo principal**, plan v2). El jurado recibe una factura base del pool de Dev 1 (`datos/base/`), cambia monto, cuenta, proveedor, número o una nota (visible u oculta) y elige qué rayar (total, cuenta o número). El servidor valida con `extraccion.render.validar_cambios`, **dibuja el PDF** (`render_factura`) en `entrada/falsificadas/` y lo pasa por `extraer()` → `decidir_async`: **el agente lee el documento, nunca el formulario**. Necesita `ATTACK_LAB_EXTRACCION_LIVE=1`; sin LIVE todo escala (`SIN_EXTRACCION`, no aprobable).

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
| `GET /falsificar/base` | Público | Base al azar: `base_id`, proveedor, número, moneda, total, cuenta enmascarada, pista y `preview_url`. Nunca el resultado esperado |
| `GET /falsificar/base/{base_id}/preview.png` | Público | Vista previa a 120 dpi (en caché) |
| `POST /falsificar` | Público, con cuota | `{sesion_id, base_id, cambios, rayar \| rayones_png_b64}`. Cuotas: 30/min global, 6/min por IP, 10/h por sesión. Añade `fuente_extraccion`, `base_id` y `campos_cambiados`. Cambios inválidos → 422 |
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

- **Navegación:** Attack Lab (raíz `/`: la página por defecto de Streamlit ignora su `url_path`, así que `/attack-lab` muestra «Page not found»), Comité en vivo, Bandeja, Documento, Reglas (lectura) y Métricas.
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
| `ATTACK_LAB_EXTRACCION_LIVE=1` | Autoriza extracción con modelos reales. **Cuesta dinero**; desactivado por defecto. **Obligatorio para el modo «factura falsificada»** |
| `APP_FALSIFICAR_POR_MINUTO_IP` | Cuota por IP del modo falsificar (6). **Súbela si los jurados comparten IP** (misma Wi-Fi o un proxy sin `APP_CONFIAR_EN_PROXY`) |
| `APP_FALSIFICAR_POR_HORA_SESION`, `APP_FALSIFICAR_POR_MINUTO_GLOBAL` | 10 y 30 por defecto; cada intento cuesta una extracción LIVE |
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
# → http://127.0.0.1:8501/   (la raíz es el Attack Lab)

# Reinicio de la demo (solo admin; no hay botón en la UI del jurado)
curl -X POST -H "Authorization: Bearer <token-admin>" http://127.0.0.1:8000/admin/reiniciar-demo
```

**Tests:**
- Raíz: `uv run pytest -q` cubre los 619 de G4 más los 48 de la API (`tests/test_app_api.py`).
- UI: `cd app/ui && uv run pytest -q` da 3 passed más 1 E2E, que se activa con `ATTACK_LAB_API_URL`.

**Bandit:** `bandit -r app cerebro` también recorre `app/ui/.venv` (código de terceros), y en Windows `-x` no lo excluye. Para revisar solo nuestro código:

```bash
uv run bandit -q -r cerebro app/__init__.py app/api.py app/config.py app/documentos.py app/seguridad.py \
  app/servicios.py app/sintetico.py app/ui/ui.py app/ui/paginas.py app/ui/estilo.py app/ui/cliente.py
```

Resultado: sin hallazgos.

**Smoke local (2026-10-17):** uvicorn en `127.0.0.1:8000` y Streamlit en `127.0.0.1:8501/` (HTTP 200; ojo: Streamlit responde 200 a cualquier ruta).

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

- [x] Leer `app/api.py` y `app/servicios.py`; confirmar que ninguna ruta devuelve la evidencia cruda a un jurado. Las rutas nuevas devuelven solo `vista_publica` y la cuenta enmascarada (verificado en el smoke real)
- [x] Probar desde un celular (raíz `/`). Hecho con Chrome emulando un iPhone (390 px, táctil) contra los contenedores Docker: ataque «cuenta del atacante» de punta a punta → FRENAR `CUENTA_NO_REGISTRADA`. **Falta un celular físico** (red real y teclado del sistema)
- [x] Intentar aprobar un FRENAR por la API y por la UI: debe ser imposible. API: 409 `no_aprobable` (smoke real); UI: sin botones (test de Dev 2)
- [x] Accesibilidad: Lighthouse móvil **92 → 100**. Se corrigió el contraste de la cabecera (tema oscuro en `app/ui/.streamlit/config.toml`, sin botón «Deploy») y la vista previa ahora tiene `alt`
- [x] Construir con Docker (`docker compose up --build`): **las dos imágenes se construyen y corren** (Docker Desktop 29.8.1). Antes se corrigió `api.Dockerfile` (no copiaba `app/falsificar.py` ni traía Pango/fuentes para WeasyPrint). Smoke en contenedores con LIVE: PAGAR, FRENAR cuenta, FRENAR texto oculto y ESCALAR por rayón; sin secretos ni cuentas en logs ni en la imagen. `tests/test_docker.py` lo vigila
- [x] Telegram: **fuera de alcance** en el plan v2 (`DEV3_experiencia_demo_v2.md`). Si se retoma, decidir si reutiliza `/simular` o `/ingest` (recomendado) y cómo se autentican los aprobadores (`chat_id` en `APP_APROBADOR_TOKENS` / `CEREBRO_APROBADORES`).

## 9. Revisión de Dev 3 (2026-10-18)

Rama `feat/dev3-integracion` = Attack Lab (`feat/attack-lab-dev2-handoff`) + Dev 1 v2 (`feat/dev1-v2-falsificacion`).

| Cambio | Detalle |
|---|---|
| Fusión con Dev 1 v2 | `render_factura`, `preview_png`, 8 facturas base, plantilla, detector de rayones. Conflictos: `schemas.py` (se conserva la versión de Dev 2; git había duplicado los campos v2 de `Decision`) y `pyproject.toml` (unión de dependencias) |
| Un solo `enmascarar` | `extraccion.enmascarar` delega en `cerebro.privacidad` (`****7781`), con prueba de contrato |
| Modo «factura falsificada» | `app/falsificar.py`, rutas `/falsificar*`, pestaña principal en la UI. Rayones: el jurado elige qué rayar y el servidor dibuja el garabato (ver límites) |
| Docker | `api.Dockerfile` copia `falsificar.py` e instala Pango, HarfBuzz-Subset y DejaVu |

**Smoke real (LIVE: GPT-6 Luna + Claude Haiku 5.5, cerebro real, base temporal):**

| Ataque sobre el documento | Resultado | Tiempo |
|---|---|---|
| Tal cual | PAGAR `OK` | 5,8 s |
| Cuenta `ATACANTE-7781` | FRENAR `CUENTA_NO_REGISTRADA` | 3,8 s |
| Proveedor "Delta Devs" | FRENAR `PROVEEDOR_NO_PERMITIDO` | 3,8 s |
| Monto 999.999.999 | FRENAR `TOPE_DURO` | 4,3 s |
| Reusa FV-0192 (Tango, USD 1.850) | FRENAR `DUPLICADO_EXACTO` | 3,9 s |
| Orden visible al agente | FRENAR `INYECCION` | 3,5 s |
| Orden oculta (blanco, 1 pt) | FRENAR `TEXTO_OCULTO` | 3,6 s |
| Rayón sobre el total | ESCALAR `EXTRACCION`, no aprobable | 6,0 s |
| Tal cual USD 7.400 → aprobar | ESCALAR `LIMITE_PAGO` aprobable → 200 PAGAR | 3,3 s |
| Aprobar el FRENAR de la cuenta | 409 `no_aprobable` | — |

Ninguna respuesta ni el log de la API contienen cuentas completas ni tokens; la cadena quedó íntegra.

**Límites nuevos:**
1. **Rayones a mano alzada:** el componente `streamlit-drawable-canvas` no funciona con este Streamlit (falla al registrarse). La UI ofrece "Rayar encima de…" y el servidor dibuja; la API ya acepta `rayones_png_b64` para una página de dibujo propia.
2. **Cuota por IP:** con 6/min, jurados detrás de la misma IP se bloquean entre sí. Ajustar `APP_FALSIFICAR_POR_MINUTO_IP`.
3. **Saldo:** cada PAGAR consume saldo de la demo (USD 8.600 tras reiniciar); usar `/admin/reiniciar-demo` entre ensayos.

### Pantalla, aprobador y URL pública (Dev 3, 2026-10-18)

| Pieza | Detalle |
|---|---|
| `GET /estado` | Contadores sobre la última decisión de cada factura (el paquete del jurado no cuenta), último veredicto y feed seguro: «Atacante #N», nombres de los campos cambiados, monto y cuenta enmascarada. Nunca la nota, el proveedor escrito ni la sesión |
| «Pagos indebidos» | `app/auditoria.py` re-audita **cada PAGAR** contra el catálogo: proveedor permitido, cuenta registrada (HMAC con `cerebro.privacidad.coincide`), lectura válida, sin texto oculto y límites (o aprobación humana). No repite lo que dijo el cerebro |
| Página `/pantalla` | Para proyectar: contadores, sello, feed (se actualiza cada 2 s) y QR hacia la URL pública (`PUBLIC_URL` o el `Host` del túnel). Con sesión de operador y `APROBADOR_JURADO_TOKEN`, muestra el **QR del aprobador** |
| Página `/aprobar` | Para el jurado voluntario: la clave del QR pasa a la sesión del servidor y se borra de la URL. Botones solo para lo aprobable; lo demás muestra la acción requerida |
| Servicio `tunel` | `cloudflare/cloudflared:2026.10.1`, perfil `publico`, solo hacia la UI (la API sigue privada) |

Verificado (2026-10-18): por el túnel, desde Chrome emulando un iPhone, un ataque de cambio de cuenta → FRENAR `CUENTA_NO_REGISTRADA`; `/pantalla` proyectada (1440 px) con contadores, feed y QR público; `/aprobar` sin clave pide escanear el QR.

**Día del pitch (en este orden):**
1. Docker Desktop encendido. En `.env`: claves de los modelos, `ATTACK_LAB_EXTRACCION_LIVE=1`, tokens de operador y `APROBADOR_JURADO_TOKEN` (el token de una identidad que esté en `CEREBRO_APROBADORES`).
2. `docker compose --profile publico up -d --build`, y luego `docker compose logs tunel` para copiar la URL `https://….trycloudflare.com` (cambia en cada arranque; un *quick tunnel* no tiene garantía de disponibilidad: ensaya antes).
3. Reiniciar la demo justo antes (saldo, límites y cadena limpios): `POST /admin/reiniciar-demo` con el token de admin.
4. Proyectar `<URL>/pantalla`. Iniciar sesión de operador en la barra lateral **solo en esa máquina** y activar «Mostrar QR del aprobador» cuando algo escale.
5. Al terminar: `docker compose stop tunel` (la app deja de ser pública).
