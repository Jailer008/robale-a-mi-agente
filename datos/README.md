# Datos ficticios (Dev 1)

Todo lo que hay aquí es inventado: empresas, personas, IDs fiscales y cuentas.

| Archivo | Qué es |
|---|---|
| `proveedores.yaml` | 8 proveedores (CO, MX, AR, PE); Vicuña Consulting SAC está bloqueado |
| `contratos.yaml` | Un contrato por proveedor permitido, con ítems y `tasa_pactada_por_usd` si no es USD |
| `historico_pagos.csv` | 20 pagos entre el 2026-08-20 y el 2026-10-09; incluye FV-0192 |
| `tasas_fx.yaml` | Tasa, fuente y fecha por moneda |
| `facturas/` | Los 15 documentos (PDF, PNG, JPG, `.eml`, `.txt`) |
| `facturas_json/NN.json` | La `FacturaCanonica` correcta de cada documento: entrada de Dev 2 y ground truth de la extracción |
| `ground_truth.csv` | Decisión y motivo esperados; `jurado=1` marca el paquete del jurado (07, 08, 10, 11, 12, 14). v2: 09 y 10 son FRENAR no aprobables |
| `generar.py` | Dibuja los documentos a partir de los JSON y actualiza `id_documento` |

## Supuestos que el cerebro (Dev 2) debe respetar

Los tests de `tests/test_datos.py` verifican que cada trampa dispare **solo** su motivo
bajo estas reglas. Si el cerebro calcula distinto, la autonomía medida no coincidirá.

- **Fecha de referencia:** 2026-10-17. El "mes en curso" es octubre de 2026.
- **Conversión a USD:** `monto_usd = monto / unidades_por_usd` (de `tasas_fx.yaml`).
- **Saldo:** `saldo_disponible_usd` de `reglas.yaml` es el saldo al inicio del mes.
  Saldo actual = `saldo_disponible_usd` − suma de `monto_usd` pagado en el mes
  (histórico de octubre + lo que se vaya pagando). Con el histórico, arranca en **USD 8.600**.
- **Gasto mensual:** por proveedor y global, sobre los pagos de octubre.
- **Duplicados:** se compara `fecha_pago` del histórico contra `fecha_emision` de la factura.
  Solo la 07 (exacto) y la 08 (disfrazado) tienen candidatos.

### Por qué la 13 frena por saldo y no por tope duro

Con saldo USD 25.000 y tope duro USD 15.000, un saldo fijo no permite el caso. Con el saldo
del mes, la 13 (PEN 34.000 = USD 9.066,67) supera el saldo (USD 8.600, o menos después de
pagar las limpias) sin tocar el tope duro ni el límite mensual del proveedor. La 12
(USD 7.400) sí cabe en el saldo que queda tras pagar las 6 limpias (USD 7.477,34), así que
solo escala por el límite por pago.

## Modo en vivo (v2): el jurado falsifica facturas

| Archivo | Qué es |
|---|---|
| `base/base_01..08.json` | Facturas que el servidor reparte: 5 limpias (USD 833–1.120, cinco monedas) y 3 trampas (06 tarifa +30 %, 07 USD 7.400, 08 nota oculta). Cada una trae `esperado_tal_cual` y `pista` |
| `plantillas/factura.html` | Plantilla Jinja2 (autoescape) con la que se dibuja todo lo del modo en vivo |

```python
from extraccion.render import render_factura, preview_png, CambiosInvalidos
from extraccion import extraer, enmascarar

pdf = render_factura("base_01", {"cuenta": "ATACANTE-7781"}, rayones_png, "A7", Path("intentos/"))
factura = extraer(pdf, "web")        # el agente lee el PDF, nunca el formulario
enmascarar(factura.cuenta_bancaria)  # "…7781"
```

- **Cambios permitidos:** `monto` (0 a 1.000.000.000), `cuenta`, `proveedor` y `numero` (máx. 40 caracteres de `[A-Za-z0-9 .-_/áéíóúñ]`), `nota` (máx. 200) y `nota_oculta` (bool). `rayones_png`: PNG transparente de máx. 2 MB. Cualquier otra cosa lanza `CambiosInvalidos` (subclase de `ValueError`: respóndela con 400); una base desconocida lanza `ValueError`.
- **Número:** si el jurado no lo cambia se dibuja `"{numero}-{sufijo}"` (evita duplicados falsos entre jurados); si lo cambia (p. ej. `FV-0192`) se respeta.
- **Monto (opción simple del plan):** se cambia solo el total; líneas y subtotal quedan igual. El validador ve que no suman y la factura escala (y el cerebro frena si supera el tope duro).
- **Proveedor:** cambia solo el nombre; el ID fiscal y la cuenta siguen siendo los de la base.
- **Nota:** visible → bloque "Observaciones", que llega a `texto_libre` leído del PDF sin modelo; oculta → texto blanco de 1 pt, que llega a `texto_oculto`.
- **Rayones:** si un trazo tapa texto (≥ 5 % de un fragmento), la ingesta agrega el aviso "Hay trazos encima del texto «…»" y la factura escala. Un trazo en el margen no cuenta.

Medición real del modo en vivo (2026-10-17, GPT-6 Luna + Claude Haiku 5.5): render + extracción en 3–5,5 s por intento. Tal cual, la cuenta del atacante y `FV-0192` se leen exactos (`extraccion_ok=True`, el cerebro decide); monto 999.999.999 y rayón sobre el total dan `extraccion_ok=False`; las notas llegan a `texto_libre` o `texto_oculto`.

**Ojo con el saldo en la demo:** tras `reiniciar_demo()` el saldo es USD 8.600. Las 5 limpias suman USD 4.939, así que después de unos 7 pagos limpios las siguientes frenan por `SALDO`, y reenviar la misma base escala por duplicado difuso. Ambas cosas son correctas, pero conviene saberlo antes del pitch.

## Caché de demo

`cache/` (en la raíz) guarda las respuestas de GPT-6 Luna (A) y Claude Haiku 5.5 (B) para
las 15 facturas, por SHA-256 del documento. Con `DEMO_CACHE=1`, `extraer()` responde desde
ahí sin llamar a ningún modelo; las facturas nuevas (por ejemplo, las del jurado) sí llaman a
los modelos y se agregan a la caché. La clave incluye el nombre del extractor: si cambia
`EXTRACTORES` o el modelo, hay que volver a llenarla con
`DEMO_CACHE=1 uv run python -m extraccion.medir`.

Resultado de la medición real (2026-10-17, `resultados_extraccion.json`): 15/15 con
`extraccion_ok` correcto, las 14 legibles perfectas en todos los campos, 3–5 s por factura.

## Regenerar los documentos

Necesita WeasyPrint (en WSL):

```bash
uv run python datos/generar.py
```
