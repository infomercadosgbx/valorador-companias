# Orden «Actualizar todo»: revisión completa de una compañía

Estas instrucciones las sigue la orden **«Actualizar todo»** (por ejemplo: «Actualiza todo de AMZN» o «Actualiza todo de todas las compañías»).
A diferencia de la «Revisión tras resultados» (`INSTRUCCIONES.md`), que solo mira la última nota de resultados, esta orden repasa **las 10 pestañas** con todo lo publicado desde la última revisión: 10-K, 10-Q, 8-K, presentaciones, prensa financiera y sectorial, y redes sociales.

El resultado es siempre una **propuesta** en `propuestas/<T>.json`; tú **nunca** escribes en `analysis/` ni en `data/`. Después se sigue `INSTRUCCIONES.md`, apartado 8: cada cambio lleva `tipo` (`"hecho"` o `"criterio"`), un segundo agente verifica los hechos y `scripts/aplicar_cambios.py` aplica solo los verificados. En la orden «Actualizar todo», pedida por el usuario, la propuesta es `urgente: true`: el criterio le llega en el momento, sin esperar al sábado.

## 0. Alcance y punto de partida

- Compañías: las que pida el usuario; «todas» = todas las de `companies.json`, una detrás de otra, con un commit por compañía (así el avance no se pierde si algo falla).
- Ventana de revisión: desde `analysis/<T>.json → meta.asOf` hasta hoy. Si `asOf` falta o tiene más de 6 meses, usa los últimos 6 meses.
- Si ya existe `propuestas/<T>.json` (por ejemplo, una revisión tras resultados sin aplicar), **intégrala**: conserva sus cambios salvo los que mejores con información más reciente, y une sus `fuentes`.

Lee antes de buscar nada fuera:

| Archivo | Qué te da |
|---|---|
| `analysis/<T>.json` | El análisis actual: lo que hay que revisar campo a campo |
| `data/<T>.json` | Cifras oficiales ya calculadas (`resultados`, `balance`, `segmentos`, `vencimientos_deuda`), `ultimo_informe` y `ultimo_8k_resultados` (con enlaces), `riesgos_10k` (riesgos nuevos o eliminados entre 10-K), `directivos` (formularios 4), `precio`, `consenso_automatico`, `resultados_previstos`, `noticias` (hasta 30 titulares con sentimiento: Finnhub, Marketaux, Google News —titulares de Reuters, Bloomberg, FT, WSJ, Expansión, Cinco Días…—, Seeking Alpha, medios sectoriales y agencias), `redes.stocktwits` (porcentaje de mensajes alcistas), `peers` y `avisos` |
| `manual/<T>.json` | Precios objetivo (media, rango e historial) y estimaciones introducidos a mano |
| `companies.json` | `medios` sectoriales y `alias` de la compañía |
| `seguimientos.json` | Hechos que el usuario vigila (p. ej. préstamo del DOE a Vistra) |
| Doc del proyecto `claude/fuentes-de-prensa.md` | Qué webs se leen bien, en parte o no se pueden leer |

## 1. Fuentes, por orden de autoridad

1. **SEC (oficial).** Último 10-K: Item 1 (negocio, clientes de más del 10%, competencia, empleados), Item 1A (riesgos), Item 7 (MD&A). Último 10-Q: MD&A y Part II Item 1A (riesgos nuevos). Todos los 8-K de la ventana: 2.02 (resultados), 5.02 (cambios en la dirección), 1.01 (contratos relevantes), 7.01/8.01 (otros hechos). Último DEF 14A (proxy): retribución, voto, consejo. Si sec.gov no es accesible desde tu entorno, usa el mismo documento en la web de relación con inversores de la compañía y las cifras de `data/<T>.json`.
2. **La compañía.** Web de relación con inversores (`sources.ir`): nota de resultados, presentación, día del inversor. Transcripción de la llamada (The Motley Fool u otra fuente fiable).
3. **Prensa financiera.** Los titulares de `data/<T>.json → noticias` y búsqueda web: Investing (también para los teletipos de Reuters), Yahoo Finance, Seeking Alpha, Barron's, CNBC. Para medios de pago o bloqueados (Reuters, FT, Bloomberg, WSJ, Investing Premium, Expansión, Cinco Días): solo si están disponibles las herramientas del navegador de la app de escritorio con la sesión del usuario iniciada; si no, dilo en el resumen y no los cites.
4. **Prensa sectorial.** Los medios de `companies.json → medios` (Utility Dive, The Next Platform, AdExchanger, Data Center Dynamics…) y datos oficiales del sector cuando aplique (EIA, ERCOT, FERC…).
5. **Redes sociales.** Reddit (subforo de la compañía, r/stocks, r/investing, r/wallstreetbets), X, StockTwits y YouTube (vídeos de los últimos 30 días con muchas visualizaciones). Solo sirven para medir **el tono y los temas de conversación**: nunca salen de aquí cifras, hechos ni cambios en la tesis.

Reglas:

- **No inventes nada.** Toda cifra sale de las fuentes 1–2 o de `data/<T>.json`; la prensa sirve para hechos (contratos, demandas, cambios de directivos) que se puedan citar con enlace y fecha. Si algo no se puede confirmar, no lo incluyas.
- Las cifras de la propuesta deben **coincidir con `data/<T>.json`** cuando existan allí (ingresos, márgenes, caja, deuda). Si la SEC y la prensa discrepan, gana la SEC.
- Estilo de siempre: español claro, frases cortas, cifras en M$ con punto de miles («25.274 M$»), porcentajes con coma («+5,6%»), trimestres como «3T26», fechas como «29-oct-2026».

## 2. Qué revisar en cada pestaña

Propón solo lo que **cambia**. Si un campo sigue siendo correcto, no lo incluyas. Los listados se proponen completos (sustituyen al actual).

| Pestaña | Campos (`analysis/<T>.json`) | Qué comprobar | Fuente principal |
|---|---|---|---|
| **Resumen** | `overview.thesis`, `overview.summary`, `overview.keyFacts`, `overview.catalysts`, `meta.nextEarnings`, `meta.employees`, `meta.asOf` | Tesis con el precio actual; datos clave con las últimas cifras; quita catalizadores ya pasados y añade los nuevos con fecha; próxima fecha de resultados (`data → resultados_previstos.proximos`) | 10-Q/8-K, `data/<T>.json`, IR |
| **Negocio** | `business.model`, `business.customers`, `business.clients` (`nota`, `kpis`…), `business.customerTypes`, `business.segments`, `business.segNote`, `business.quality`, `business.phase`, `business.phaseNote` | Nuevos productos o líneas de negocio, clientes y contratos firmados, cartera de pedidos, concentración de clientes, peso de cada segmento (`data → segmentos`), puntuaciones de calidad (márgenes, conversión en caja) | 10-K Item 1, 10-Q MD&A, 8-K 1.01, notas de prensa |
| **Finanzas** | `fin_manual.q` (solo series que la SEC no publica, p. ej. crecimiento de AWS) | El resto lo pone el robot: no lo toques. Añade el último trimestre a las series manuales con las mismas etiquetas que la SEC | Nota de resultados, presentación |
| **Ventaja competitiva** | `moat.width`, `moat.trend`, `moat.note`, `moat.sources`, `moat.comps` | Cambios en cuota, precios, entrada de competidores, cifras de crecimiento de rivales, amenaza de cada competidor | 10-K (competencia), prensa sectorial, resultados de los rivales |
| **Crecimiento** | `growth.score`, `growth.scoreNote`, `growth.tam`, `growth.guidance`, `growth.drivers` | Guía nueva frente a la anterior; estado de cada motor (`st`, `k`, `impact`); motores nuevos o agotados; tamaño del mercado actualizado | Nota y llamada de resultados, prensa sectorial |
| **Directiva** | `mgmt.people`, `mgmt.note`, `mgmt.scores`, `mgmt.alloc`, `mgmt.vote`, `mgmt.call` | Altas y bajas (8-K 5.02), retribución y voto (DEF 14A), compras y ventas de directivos (`data → directivos`), uso de la caja (recompras, dividendos, capex, M&A), resumen de la última llamada (`{periodEnd, q, date, doc, url, nota, dir, ret, guia, cap}`) | 8-K, DEF 14A, formularios 4, transcripción |
| **Riesgos** | `risks` (`[{n, cat, p, i, note}]`, p e i de 1 a 5) | Riesgos nuevos o eliminados del 10-K/10-Q (`data → riesgos_10k`), demandas, regulación, deuda, concentración; ajusta probabilidad e impacto con hechos | 10-K/10-Q Item 1A, 8-K, prensa |
| **Valoración** | `v.*` (`rev0`, `year0`, `g`, `m1`, `m5`, `capex`, `capex5`, `sbc`, `da`, `tax`, `wacc`, `tg`, `exit`, `eps`, `pe`, `evm`, `scn`), `peers` | Año base y ventas con el último anual o los últimos 12 meses; crecimiento y márgenes según la guía; capex según lo anunciado. Explica cada supuesto. Si los precios objetivo de `manual/<T>.json` están desfasados, actualízalos como indica `INSTRUCCIONES.md`, apartado 5 bis | `data/<T>.json`, guía de la compañía |
| **Veredicto** | `verdict.summary`, `verdict.bull`, `verdict.bear`, `verdict.watch`, y solo si está claramente justificado `verdict.rating`, `verdict.conviction`, `verdict.buyBelow`, `verdict.horizon` | Que encaje con todo lo anterior: los riesgos principales aparecen en «En contra», los motores en «A favor», y el precio de compra es coherente con el DCF | Todo lo anterior |
| **Fuentes** | `sources.docs`, `sources.news`, `social.pulse`, `social.videos`, `social.pulseFuente`, `notes` | Añade los nuevos 10-K, 10-Q, 8-K, presentaciones y transcripciones (`{cat, t, d, u}`); 5–8 noticias de calidad de la ventana (`{t, src, u}`); pulso por red `[{p, s, note}]` con `s` = −1 negativo, 0 neutral, 1 positivo; 3–5 vídeos recientes `{t, u}` | SEC, IR, prensa, redes |

Cierra siempre con `meta.asOf` = fecha de hoy («7-nov-2026»).

## 3. Repaso de coherencia antes de guardar

- Las cifras de `overview.keyFacts`, `business` y `growth` coinciden con `data/<T>.json`.
- Ningún catalizador tiene fecha pasada.
- No propones `v.shares`, `v.cash` ni `v.debt`: salen de la SEC. Los hechos posteriores al último informe van en `ajustes_posteriores` (`INSTRUCCIONES.md`, apartado 8.4).
- Cada riesgo con P×I ≥ 12 aparece en `verdict.bear` o `verdict.watch`.
- `verdict.buyBelow` y `verdict.rating` son coherentes con el valor del DCF y el precio actual (`data → precio.valor`).
- Los seguimientos de `seguimientos.json` de esa compañía están reflejados en riesgos o en «Qué vigilar».

## 4. Formato de `propuestas/<T>.json`

El mismo que la revisión tras resultados, con `alcance: "completa"` y una `fuente` por cambio (la web la enseña junto al «por qué»):

```json
{
  "ticker": "AMZN",
  "creada": "2026-11-07",
  "alcance": "completa",
  "motivo": "Actualización completa (desde el 29-oct-2026)",
  "informe_accn": "0001018724-26-000038",
  "resumen": "Cuatro o cinco frases: qué ha pasado en la ventana, qué cambia en la tesis, qué no se pudo leer y el consenso manual si está desfasado.",
  "fuentes": [{"t": "10-Q 3T26", "u": "https://www.sec.gov/..."}],
  "cambios": [
    {"campo": "growth.drivers", "valor": [], "porque": "AWS acelera al +39%; nuevo motor: Amazon Leo", "fuente": {"t": "Nota de resultados 3T26", "u": "https://…", "d": "29-oct-2026"}}
  ]
}
```

- `informe_accn`: el de `data/<T>.json → ultimo_8k_resultados.accn`.
- Ordena `cambios` por pestaña, en el orden de la tabla del apartado 2.

## 5. Revisión de internet (tarea programada: cada mañana, solo con señal)

La tarea programada de cada mañana (lunes a sábado) se reparte así:

- **Lo oficial** (SEC y la compañía), de martes a sábado: 8-K de resultados, 10-Q y 10-K (MD&A, notas a los estados financieros, factores de riesgo), otros 8-K y notas de prensa de la compañía, llamadas con analistas y comentarios de la dirección. Se hace con `INSTRUCCIONES.md` (apartados 1–7), no con este documento.
- **Lo que se dice en internet**, cada mañana, pero solo para las compañías con señal: prensa financiera, prensa sectorial y redes sociales (fuentes 3–5 del apartado 1). El viernes, para todas (repaso semanal).

Cómo se hace la revisión de internet:

1. **Qué compañías:** ejecuta `python scripts/senales.py`. Revisa las que salen como «REVISAR» y apunta sus señales en el resumen. Las señales son: movimiento de la cotización de un día ≥ 6 %, dos o más titulares con sentimiento muy marcado, una nota de prensa o noticia sectorial nueva, un asunto de `seguimientos.json` con novedades, resultados en los próximos 7 días o en los 3 últimos, o que sea viernes. Si ninguna sale, la parte de internet termina aquí.
2. **Ventana:** desde la revisión de internet anterior de cada compañía (la columna «desde» de `senales.py`).
3. **Alertas de la prensa de pago en Gmail:** busca en el Gmail del usuario (conector de Gmail) los correos de la ventana con `from:(ft.com OR cnbc.com OR wsj.com OR dowjones.com OR reuters.com OR thomsonreuters.com OR bloomberg.com OR bloombergbusiness.com OR expansion.com OR cincodias.elpais.com OR investing.com OR elconfidencial.com) newer_than:3d` (lunes: 4d). Quédate con los que nombran una compañía de `companies.json` (nombre, alias o ticker). Una alerta con una novedad material cuenta como señal aunque `senales.py` no la marcara: añade esa compañía a la revisión. Usa titular y resumen de la alerta como fuente («FT, alerta myFT del 13-nov-2026: <titular>» con el enlace del artículo); si la alerta trae el texto completo, mejor. Nunca copies párrafos: resume con tus palabras.
4. **Criba primero, barata:** por compañía, mira `data/<T>.json → noticias` (titulares de la ventana, con sentimiento), `seguimientos.json` y una o dos búsquedas web de noticias de la compañía; añade los medios sectoriales de `companies.json → medios` si los titulares no bastan. Empieza por la causa de la señal (por qué se movió la cotización, qué dice la nota de prensa).
5. **¿Hay una novedad material?** Cuenta como material: un contrato o cliente relevante, un cambio de guía, una compra o venta de negocio, una alta o baja en la dirección, una demanda o decisión regulatoria, un producto importante, un movimiento de un competidor que cambie el MOAT, un cambio de recomendación o de precio objetivo de varios analistas, o un movimiento del precio de más del 8% en un día con causa conocida. Si la novedad ya está recogida en `analysis/<T>.json` o en la propuesta pendiente, no cuenta. Si el hecho es oficial (8-K, nota de prensa de la compañía), cítalo con su fuente oficial.
6. **Sin novedad material, no se hace nada** con esa compañía en esta parte (salvo el pulso en redes del punto 8).
7. **Con novedad material:** actualiza todo lo que la novedad afecta en las pestañas, no solo los datos: `overview.thesis` (tesis en una línea), `overview.keyFacts` y `catalysts`, `business.*`, `moat.*` (fuentes, competidores, anchura y tendencia), `growth.*` (motores, guía, puntuación), `mgmt.*`, `risks` (añadir, quitar o recalificar), `sources.news`. Cada cambio con `tipo` «hecho» o «texto» según `INSTRUCCIONES.md` 8.1: se aplican solos si pasan la verificación. Los supuestos del DCF y el veredicto se proponen (`tipo` «criterio») y los decide el usuario. `motivo`: «Novedades del <fecha>: <titular corto>».
8. **Pulso en redes y vídeos** (`social.pulse`, `social.videos`, `social.pulseFuente`): para las compañías revisadas, proponlo solo si el tono o los temas han cambiado frente a lo que hay. Las redes solo sirven para el tono: nunca para cifras ni hechos.
9. **Consenso de analistas:** si en la ventana varios analistas han cambiado su precio objetivo (o la cifra de `manual/<T>.json` tiene más de 30 días), actualízalo como indica `INSTRUCCIONES.md`, apartado 5 bis.
10. **Propuesta pendiente:** si ya existe `propuestas/<T>.json` (también la creada esa misma mañana con lo oficial), añade los cambios nuevos sin quitar los que ya había (si un campo se repite, gana el más reciente), une las `fuentes`, amplía el `resumen` y pon `creada` con la fecha de hoy.
11. **Marca la revisión:** al terminar, `python scripts/senales.py --marcar <T1> <T2> …` con las compañías revisadas (el viernes, sin tickers: todas), para que la próxima ventana empiece hoy.
12. **Un solo commit** al final para todas las compañías con cambios: `Propuestas de internet: <T1>, <T2>` (incluye `propuestas/_estado.json`). Si ninguna tiene novedades, haz commit solo de `propuestas/_estado.json` con «Revisión de internet sin novedades».

## 6. Guardar

1. Si la ventana incluye unos resultados nuevos, traduce también la nota al español (apartado 5 de `INSTRUCCIONES.md`) y actualiza `propuestas/_estado.json → revisado.<T> = {accn, fecha}` para que la revisión de la mañana no repita el trabajo.
2. Valida los JSON (`python -m json.tool propuestas/<T>.json`).
3. Commit en `main`: `Propuesta: <T> actualización completa <fecha>` (en la revisión de internet, el del apartado 5) y push. La web muestra el aviso «Propuesta de actualización» y llega el email.
4. Al terminar, informa al usuario por compañía: número de cambios por pestaña, lo más importante que cambia en la tesis y qué fuentes no se pudieron leer.
