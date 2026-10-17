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
| `ground_truth.csv` | Decisión y motivo esperados; `jurado=1` marca el paquete del jurado (07, 08, 10, 11, 12, 14) |
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

## Regenerar los documentos

Necesita WeasyPrint (en WSL):

```bash
uv run python datos/generar.py
```
