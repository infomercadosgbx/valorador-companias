# Valorador de compañías

Web estática (GitHub Pages) que valora compañías cotizadas con **datos oficiales de la SEC** y se actualiza sola cada noche laborable. No hay servidor propio: un GitHub Action descarga los datos, los valida, escribe JSON en `/data` y hace commit solo si algo cambió.

> Estado: **fases 1 y 2**. Descarga, validación y Action verificados con datos reales de la SEC el 30-oct-2026; la web lee `/data`, `/analysis` y `/manual`.

## Puesta en marcha (una sola vez)

Necesitas permisos de administrador en el repositorio. Todo se hace desde la web de GitHub.

**1. Sube el código** a la rama `main` del repositorio.

**2. Identifícate ante la SEC.** La SEC exige una cabecera User-Agent con tu nombre y un email.
- *Settings → Secrets and variables → Actions → pestaña **Variables** → **New repository variable***
- Nombre: `SEC_USER_AGENT`
- Valor: tu nombre y tu email separados por un espacio, por ejemplo `Ana Pérez ana@ejemplo.com`
- (Si prefieres que no sea visible, créalo en la pestaña *Secrets* con el mismo nombre; funciona igual.)

**3. Crea la clave de precios (Finnhub, gratuita).**
- Regístrate en <https://finnhub.io/register> y copia la *API key* de tu panel.
- *Settings → Secrets and variables → Actions → pestaña **Secrets** → **New repository secret***
- Nombre: `FINNHUB_API_KEY`, valor: la clave.
- Sin esta clave todo funciona salvo el precio, y la web lo avisa.

**4. Activa GitHub Pages.**
- *Settings → Pages → Build and deployment → Source:* **GitHub Actions**.

**5. Comprueba los permisos de los Actions.**
- *Settings → Actions → General*: «Allow all actions and reusable workflows».
- En la misma página, *Workflow permissions*: **Read and write permissions** (los workflows piden `contents: write` e `issues: write`).

**6. Captura las fixtures reales de la SEC** (para los tests de aceptación).
- *Actions → **Capturar fixtures SEC** → Run workflow → Run workflow*.
- Descarga los datos de AppLovin, Alphabet, Broadcom, Reddit y Amazon, los guarda en `tests/fixtures/` y ejecuta los criterios de aceptación. Si alguno falla, la ejecución sale en rojo y el log dice qué cifra no cuadra.

**7. Lanza el primer Action.**
- *Actions → **Actualizar datos** → Run workflow* (deja «Tickers» vacío para todas).
- Al terminar verás un commit `datos: actualización AAAA-MM-DD` con `data/*.json`, y después el workflow **Publicar web** desplegará la página en `https://<tu-usuario>.github.io/<repositorio>/`.

A partir de ahí se ejecuta solo de lunes a viernes a las 23:17 UTC (00:17 en Madrid en invierno, 01:17 en verano).

## La web

`valorador.html` carga `companies.json` y, para cada compañía, `data/<TICKER>.json` (cifras de la SEC y cotización), `analysis/<TICKER>.json` (tu criterio) y `manual/<TICKER>.json` (precios objetivo). No guarda nada en ningún servidor.

- **Fuente y fecha de cada cifra.** Junto a cada cifra importante aparece su origen («SEC 10-Q · 29-oct-26», «Finnhub · 30-oct-26» o «manual»). Al pasar el ratón se ve la etiqueta XBRL y el periodo; al hacer clic se abre el filing en EDGAR. La pestaña *Fuentes* tiene la tabla completa, el último 10-Q/10-K, el 8-K de resultados y su Exhibit 99.1.
- **Avisos.** Bajo la cabecera de cada compañía hay una franja con los avisos del Action y los que calcula la web: si la deuda, la caja o las acciones de tu modelo difieren más de un 20% del dato de la SEC, aparece un aviso y, en *Valoración*, el botón «Usar dato SEC».
- **Supuestos que siguen a la SEC.** Si en `analysis/<TICKER>.json` no pones `v.shares`, `v.cash` o `v.debt`, el DCF usa el último dato de la SEC y se actualiza solo cada noche.
- **Editar tu análisis.** «Editar» funciona como antes, pero los cambios se guardan como borrador en tu navegador. Para publicarlos, pulsa «Descargar <TICKER>.json» y súbelo a la carpeta `analysis/` del repositorio (*Add file → Upload files*, sustituyendo el archivo). La web te lleva a esa página de GitHub.
- **Cambios del valorador antiguo.** Si editaste algo en la versión anterior, en ella pulsa «Datos → Copiar JSON» y pégalo en «Mi análisis → Importar como borradores».
- **En local**, abre la carpeta con `python -m http.server` y entra en `http://localhost:8000/valorador.html` (abriendo el archivo con doble clic el navegador bloquea la lectura de los JSON).

## Qué hace cada noche

1. Ejecuta los tests. Si fallan, no se toca ningún dato.
2. Para cada compañía de `companies.json`: descarga `companyfacts` y `submissions` de data.sec.gov, aplica las reglas de extracción, valida y escribe `data/<TICKER>.json`.
3. Pide precio y recomendaciones de analistas a Finnhub.
4. Hace commit solo si cambió algún archivo (el sello de hora no cuenta como cambio).
5. Si la SEC no devuelve nada para alguna compañía, el Action termina en rojo y abre un Issue (o comenta en el que ya esté abierto) con el error. Las demás compañías se actualizan igualmente.

## Estructura

| Ruta | Qué es | ¿Quién lo edita? |
|---|---|---|
| `companies.json` | Única lista de compañías: ticker, nombre, CIK, color, monograma | Tú (o el alta automática, fase 3) |
| `data/<TICKER>.json` | Datos automáticos con fuente de cada cifra | **Solo el Action. Nunca a mano.** |
| `data/index.json` | Resumen de todas las compañías para la web | Solo el Action |
| `analysis/<TICKER>.json` | Tus supuestos y textos: DCF, scorecard, veredicto, directiva, MOAT, riesgos, última presentación de resultados (`mgmt.call`) y series por segmento que la SEC no publica (`fin_manual`) | Tú, versionado en git |
| `analysis/_plantilla.json` | Análisis en blanco para compañías nuevas | — |
| `manual/<TICKER>.json` | Consenso de precios objetivo introducido a mano (la web lo marca «manual») | Tú |
| `fetcher/` | Código Python (solo biblioteca estándar) | — |
| `tests/` | Tests sintéticos de cada regla y tests de aceptación con fixtures reales | — |
| `valorador.html` | La web | — |

## Fuentes de datos

- **Cifras financieras:** solo SEC EDGAR (`data.sec.gov/api/xbrl/companyfacts` y `data.sec.gov/submissions`), con User-Agent identificado, como máximo 5 peticiones por segundo y reintentos con espera creciente.
- **Precio:** Finnhub, endpoints `/quote` y `/stock/metric` (rango de 52 semanas) (API oficial, plan gratuito de 60 llamadas por minuto). Proveedor abstraído en `fetcher/prices.py`; para cambiarlo basta con otra clase `PriceProvider`.
- **Consenso:** las recomendaciones (compra/mantener/venta) llegan de Finnhub `/stock/recommendation`, gratuito. Los **precios objetivo** son de pago en Finnhub, así que van en `manual/<TICKER>.json` y la web los marcará como «manual».
- No se hace scraping de ninguna web.

## Reglas de extracción

1. **Varias etiquetas por concepto.** Ingresos: `RevenueFromContractWithCustomerExcludingAssessedTax`, `Revenues`, `SalesRevenueNet` (y la variante *IncludingAssessedTax*), combinadas por periodo: en cada año manda la etiqueta con datos más recientes. Beneficio neto: `NetIncomeLoss`, con `ProfitLoss` como alternativa. Deuda: `LongTermDebtNoncurrent` + `LongTermDebtCurrent` (o `DebtCurrent`) y, si no, `LongTermDebt`, `LongTermDebtAndCapitalLeaseObligations`, notas convertibles o senior. El catálogo completo está en `fetcher/concepts.py`.
2. **Etiqueta obsoleta.** Se descarta si su último dato va más de 60 días por detrás de los ingresos (queda un aviso informativo).
3. **Duplicados.** Un mismo periodo aparece en varios informes: queda el presentado más recientemente (así entran las reexpresiones).
4. **Anual** = periodo de 350–380 días en un 10-K. **Trimestre** = 80–100 días. Los flujos de caja, que la SEC da acumulados (6 y 9 meses), se convierten en trimestres restando.
5. **4T** = año − 1T − 2T − 3T. El 4T de **ingresos** se acepta solo si encaja con el 3T y el 1T siguiente (ratio 0,6–1,9); si no, se descarta y se avisa. El resto de conceptos sigue la decisión de los ingresos de ese año: con datos reales, aplicar el ratio a cada concepto tiraba trimestres legítimos (caja operativa estacional de Amazon, beneficio neto con extraordinarios de Broadcom o Alphabet).
6. **Caída de ingresos > 25 %** en un año: aviso de posible operación discontinuada o reclasificación (caso AppLovin 2023).
7. **Años de 52/53 semanas** (Broadcom): los trimestres se etiquetan por su cierre respecto al fin de ejercicio que publica la SEC; aviso informativo.
8. **Sin deuda etiquetada** (Reddit): deuda = 0 con la marca `"asumido": true` y aviso.
9. **Balance:** solo los saldos de los ~16 meses anteriores al último informe.
10. **Acciones:** las de la portada del último informe (`dei:EntityCommonStockSharesOutstanding`). Las compañías con varias clases (Alphabet, AppLovin, Reddit) solo las publican por clase, y la API de la SEC no las incluye; entonces se usan las acciones diluidas medias del último trimestre, con aviso informativo.
11. **Informes:** del último 10-Q/10-K y del último 8-K de resultados (Item 2.02) se guardan fecha, tipo, enlace al documento y enlace al Exhibit 99.1.
12. **Compañías extranjeras** (20-F, IFRS): se marcan `"soportada": false` con un aviso; no se muestra ninguna cifra.

## Formato de cada cifra

```json
{
  "valor": 127577000000,
  "fuente": "SEC EDGAR · 10-Q",
  "url": "https://www.sec.gov/Archives/edgar/data/1652044/…-index.htm",
  "fecha_presentacion": "2026-10-29",
  "etiqueta": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
  "periodo_inicio": "2026-07-01",
  "periodo_fin": "2026-09-30",
  "formulario": "10-Q",
  "accn": "0001652044-26-…",
  "periodo": "3T26",
  "derivado": "Año − 1T − 2T − 3T"
}
```

Los valores están en dólares (no en millones), salvo el BPA (dólares por acción) y las acciones (número). `derivado` solo aparece cuando la cifra se calcula a partir de otras.

## Avisos

Cada `data/<TICKER>.json` lleva una lista `avisos` con `nivel` (`info`, `aviso` o `error`), `codigo` y `mensaje` en español. Códigos: `etiqueta_obsoleta`, `4t_descartado`, `trimestres_no_suman`, `posible_discontinuada`, `salto_raro`, `anio_52_53_semanas`, `deuda_asumida_cero`, `componente_no_etiquetado`, `concepto_no_encontrado`, `informe_sin_xbrl`, `sin_precio`, `cik`, `no_soportada`. La web (fase 2) los mostrará junto a la cifra afectada.

## Ejecutar en local

```bash
export SEC_USER_AGENT="Ana Pérez ana@ejemplo.com"
export FINNHUB_API_KEY="…"            # opcional
python -m fetcher.main                 # todas
python -m fetcher.main --only GOOGL    # una
pip install pytest && python -m pytest -v
```

## Problemas frecuentes

- **El Action no hace commit:** revisa el paso 5 (permisos de escritura).
- **Error «Falta SEC_USER_AGENT»:** la variable del paso 2 no existe o no tiene el formato «Nombre email».
- **No se ejecuta de noche:** GitHub desactiva los workflows programados de repositorios públicos tras 60 días sin actividad; el propio commit diario lo evita, pero si lo ves desactivado, reactívalo en *Actions*.
