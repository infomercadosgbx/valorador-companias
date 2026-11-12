# Revisión tras resultados: cómo preparar una propuesta

Estas instrucciones las sigue la tarea programada «Valorador · revisión tras resultados y novedades» (y cualquiera que prepare una propuesta a mano).

Tú **nunca** escribes en `analysis/` ni en `data/`. Preparas la propuesta en `propuestas/<T>.json`, un segundo agente la verifica y `scripts/aplicar_cambios.py` (apartado 8) aplica solo los **hechos verificados**, con registro y opción de deshacer en la web. Los cambios de **criterio** (supuestos del DCF, scorecard, veredicto, MOAT, riesgos) los decide siempre el usuario.

## 1. Qué compañías revisar

Para cada compañía de `companies.json`:

- `data/<T>.json` → `ultimo_8k_resultados.accn` es el último 8-K de resultados (Item 2.02) que ha detectado el robot.
- `propuestas/_estado.json` → `revisado.<T>.accn` es el último ya revisado.
- Si son distintos y no existe ya `propuestas/<T>.json` con ese `informe_accn`, hay que preparar una propuesta.

Si no hay ninguna, termina sin hacer commit.

## 2. Qué leer (fuentes primarias primero)

1. La nota de resultados: `ultimo_8k_resultados.url_ex99_1` (Exhibit 99.1) en sec.gov. Si sec.gov no es accesible desde tu entorno, usa la misma nota en la web de relación con inversores de la compañía o en un medio que la reproduzca (Business Wire, PR Newswire), y las cifras ya calculadas en `data/<T>.json`.
2. La transcripción o los comentarios de la llamada con analistas (web de relación con inversores de la compañía, The Motley Fool u otra fuente fiable).
3. Las cifras ya calculadas en `data/<T>.json` (ingresos, márgenes, caja, deuda, segmentos, previsiones, sorpresas) y la cotización actual (`precio.valor`).
4. Prensa financiera solo para la reacción del mercado y cambios de precio objetivo.

No inventes cifras: todo número debe salir de una de esas fuentes. Si algo no se puede confirmar, no lo incluyas.

## 3. Qué proponer

Lee `analysis/<T>.json` y propone solo lo que cambia con los resultados. Mantén el estilo existente: español claro, frases cortas, cifras en M$ con punto de miles («25.274 M$»), trimestres como «3T26».

Campos habituales (rutas con punto, tal y como están en `analysis/<T>.json`):

| Campo | Qué poner |
|---|---|
| `overview.thesis` | Tesis en una frase, con el precio actual |
| `overview.keyFacts` | Lista `[{k, v}]`: cifra primero y la variación entre paréntesis, p. ej. `{"k":"Ingresos 3T26","v":"25.274 M$ (+5,6%; orgánico +3,1%)"}` |
| `overview.catalysts` | Lista `[{d, t}]` con los próximos hitos |
| `growth.guidance` | La guía nueva frente a la anterior |
| `growth.scoreNote` | Lectura del crecimiento |
| `mgmt.call` | `{periodEnd, q, date, doc, url, nota, dir:[], ret:[], guia:[], cap:[]}`: resumen de la presentación (hacia dónde va, retos, guía, capital) |
| `risks` | Lista completa `[{n, cat, p, i, note}]` si cambia algún riesgo (p e i de 1 a 5) |
| `v.*` | Supuestos del DCF que deban moverse (`v.rev0`, `v.g`, `v.m1`, `v.m5`, `v.capex`, `v.eps`…), explicando por qué |
| `verdict.summary`, `verdict.bull`, `verdict.bear`, `verdict.watch` | Conclusión y listas actualizadas |
| `verdict.rating`, `verdict.buyBelow`, `verdict.conviction` | Solo si los resultados lo justifican claramente; explícalo en `porque` |
| `meta.asOf` | Fecha de la revisión, p. ej. `"5-nov-2026"` |
| `ajustes_posteriores` | Lista completa `[{k, delta, base_accn, porque, fuente, fecha}]`: hechos posteriores al último 10-Q/10-K que cambian acciones, caja o deuda (apartado 8.4) |

Cada cambio lleva un `porque` de una línea, una `fuente` `{t, u, d}` y un `tipo`: `"hecho"` o `"criterio"` (apartado 8.1). Los listados se proponen completos (sustituyen al actual).

**Nunca propongas `v.shares`, `v.cash` ni `v.debt`.** Acciones, caja y deuda salen siempre de la SEC; lo que haya pasado después del cierre va en `ajustes_posteriores`.

## 4. Formato de `propuestas/<T>.json`

```json
{
  "ticker": "RDDT",
  "creada": "2026-11-01",
  "motivo": "Resultados del 3T26 (8-K del 29-oct-2026)",
  "informe_accn": "0001713445-26-000114",
  "resumen": "Tres o cuatro frases: qué ha pasado, qué cambia en la tesis y qué cambios propones.",
  "fuentes": [{"t": "Nota de resultados 3T26 (8-K, Ex. 99.1)", "u": "https://www.sec.gov/..."}],
  "urgente": true,
  "cambios": [
    {"campo": "overview.keyFacts", "valor": [], "tipo": "hecho", "porque": "…", "fuente": {"t": "…", "u": "https://…", "d": "29-oct-2026"}},
    {"campo": "overview.thesis", "valor": "…", "tipo": "criterio", "porque": "…", "fuente": {"t": "…", "u": "https://…", "d": "29-oct-2026"}}
  ],
  "avisos_resueltos": []
}
```

- `urgente: true` cuando la propuesta sale de unos resultados (8-K Item 2.02), de un 10-Q/10-K nuevo o de una novedad grave (apartado 8.3). Si no, omítelo.
- `avisos_resueltos`: ver apartado 8.2.

## 5. Traducir la nota al español

El informe de resultados (resultados.html y su PDF) copia de la nota los titulares («Lo destacado según la compañía»), la guía y la cita de la dirección. Las filas de tablas y las horquillas de guía se traducen solas; las frases, no.

1. Ejecuta `python -m fetcher.traduccion`: lista, por compañía, las frases sin traducir del último informe.
2. Añade cada una a `i18n/notas_es.json` → `t`, con el texto original **exacto** como clave (cópialo de la salida, sin tocar espacios ni comillas) y la traducción como valor.
3. Traducción fiel y en español claro: no resumas ni añadas nada. Cifras en formato español («1.400 M$», «4,30 $», «3T26»); nombres propios y de productos sin traducir; las llamadas a notas al pie como «(1)». Si el original está cortado, termina con «…».
4. Vuelve a ejecutar `python -m fetcher.traduccion` hasta que diga «Frases sin traducir: 0» y valida el JSON.

Al hacer push, el workflow «Rehacer informes» regenera los informes y sus PDF en un par de minutos.

## 5 bis. Precios objetivo de los analistas

No hay ninguna API gratuita con precios objetivo (Finnhub y Alpha Vantage los cobran), así que los apuntas tú tras los resultados, cuando los analistas revisan sus objetivos:

1. Busca el consenso actual en una fuente fiable y reciente (Investing.com, MarketBeat, TipRanks, Nasdaq, prensa financiera con la cifra de cada banco). Debe ser **posterior a la nota de resultados**.
2. Escribe directamente en `manual/<T>.json` (es un dato de mercado, no criterio del usuario): `precio_objetivo_medio`, `precio_objetivo_bajo`, `precio_objetivo_alto`, `num_analistas` si lo da la fuente, `fecha` («12-nov-2026») y `fuente` (medio y fecha; si los extremos son de bancos concretos, nómbralos).
3. Añade al final de `historial_objetivo` la pareja `["AAAA-MM-DD", media]` si la media cambió. No borres los puntos anteriores: la web los usa para comparar la evolución del consenso con la de tu valor.
4. Si no encuentras una fuente que te convenza, no lo cambies: la web ya avisa de que el dato es antiguo.
5. Va en el mismo commit que la propuesta.

## 6. Guardar

1. Escribe `propuestas/<T>.json` y actualiza `propuestas/_estado.json` → `revisado.<T> = {accn, fecha}`.
2. Valida que los JSON son correctos (`python -m json.tool`), también `i18n/notas_es.json` si lo tocaste.
3. Commit en `main` (propuesta y traducciones juntas): `Propuesta: <T> tras resultados <periodo>` y push. La web y el aviso por email se actualizan solos.

## 7. Otras presentaciones: 10-Q, 10-K, notas de prensa y llamadas

La revisión no se limita al 8-K de resultados. En cada ejecución, y para cada compañía, mira también estas cuatro cosas. Si hay algo nuevo y material, añade los cambios a `propuestas/<T>.json`; si ya existe, súmalos sin quitar los que había (si un campo se repite, gana el más reciente), une las `fuentes` y amplía el `resumen`.

### 7.1 Nuevo 10-Q o 10-K

- Compara `data/<T>.json → ultimo_informe.accn` con `propuestas/_estado.json → informe.<T>.accn`. Si son distintos, es un informe periódico nuevo sin revisar.
- Lee el documento (`ultimo_informe.url_documento`), sobre todo:
  - **MD&A** (*Management's Discussion and Analysis*, Item 2 del 10-Q y Item 7 del 10-K): explicación de la dirección sobre ingresos, márgenes y segmentos, tendencias, liquidez y fuentes de capital, capex previsto, recompras y dividendos, compromisos y cualquier previsión.
  - **Notas a los estados financieros** (*footnotes*): deuda y vencimientos, segmentos, ingresos pendientes de reconocer (RPO o *backlog*), compromisos y contingencias, litigios, impuestos, remuneración en acciones, adquisiciones o desinversiones y hechos posteriores al cierre.
  - **Factores de riesgo** (Item 1A): riesgos nuevos o cambiados frente al informe anterior.
  - Las cifras definitivas: si difieren de la nota de prensa, dilo.
- `motivo`: «10-Q del 3T26 (presentado el 9-nov-2026)» o el equivalente. Campos típicos: `overview.keyFacts`, `fin_manual.q` (solo series que la SEC no publica; el resto de Finanzas lo pone el robot), `business.clients`, `risks`, `mgmt.call.cap`, `ajustes_posteriores` (hechos posteriores al cierre, en la nota «Subsequent events» o en «Noteworthy developments») y los supuestos del DCF que cambien.
- Al terminar, guarda `informe.<T> = {accn, fecha, formulario}` en `propuestas/_estado.json`.

### 7.2 Notas de prensa y otros 8-K

- En `https://data.sec.gov/submissions/CIK<10 dígitos>.json` (cabecera User-Agent «Valorador smaosviviendas@gmail.com»), busca los 8-K presentados dentro de la ventana (las últimas 24 h; el martes, 72 h) que no sean el de resultados ya revisado: Item 1.01 (contratos), 2.01 (compras y ventas), 2.03 (deuda nueva), 5.02 (cambios en la dirección), 7.01 y 8.01 (notas de prensa y otros hechos), etc.
- Mira también la sala de prensa de la web de inversores de la compañía en la misma ventana.
- Solo cuenta si es material, con el criterio de `ACTUALIZACION_COMPLETA.md`, apartado 5, punto 3. `motivo`: «Nota de prensa del <fecha>: <titular corto>».

### 7.3 Llamada con analistas (*earnings call*)

- Si al revisar los resultados aún no estaba publicada la transcripción, anótalo en `propuestas/_estado.json → llamada_pendiente.<T> = {accn, desde}`.
- En cada ejecución, busca la transcripción de las compañías en `llamada_pendiente` (web de inversores, The Motley Fool u otras fuentes de `claude/fuentes-de-prensa.md`). Cuando la encuentres, completa `mgmt.call` (`dir`, `ret`, `guia`, `cap`, `nota`), con las respuestas a los analistas que cambien la lectura, y si hace falta `growth.guidance` y `verdict.watch`. Después quita la entrada de `llamada_pendiente`.
- Si en 7 días no aparece, quítala igualmente y dilo en el resumen.

### 7.4 Comentarios de la dirección fuera de resultados

Presentaciones en conferencias de inversores, *investor day* y cartas a accionistas dentro de la ventana: solo si cambian la guía, la estrategia o la asignación de capital. Van en `mgmt.*` y `growth.guidance`, con enlace y fecha.

Si no hay nada nuevo en ninguna de las cuatro, no se hace nada con esa compañía. Commit: `Propuesta: <T> tras <10-Q 3T26 | nota de prensa | llamada 3T26>`.

## 8. Verificación y aplicación automática (parte C)

Cuando ya está escrita la propuesta del día (resultados, 10-Q/10-K, otros 8-K, llamadas e internet), se verifica y se aplica lo que sea un hecho comprobado. El objetivo: que al usuario solo le lleguen sus decisiones de criterio y lo que el robot no haya podido comprobar.

### 8.1 Hecho o criterio

Marca cada cambio con `tipo`:

| `tipo` | Campos | Qué pasa |
|---|---|---|
| `"hecho"` | `overview.keyFacts`, `overview.catalysts`, `overview.summary`, `meta.asOf`, `meta.nextEarnings`, `meta.employees`, `business.model`, `business.customers`, `business.customerTypes`, `business.clients`, `business.segments`, `business.segNote`, `growth.guidance`, `growth.tam`, `mgmt.call`, `mgmt.people`, `mgmt.vote`, `mgmt.alloc`, `fin_manual`, `sources.docs`, `sources.news`, `social.*`, `ajustes_posteriores` | Se aplica solo si pasa la verificación |
| `"criterio"` | Todo lo demás: `v.*` (supuestos del DCF), `verdict.*`, `risks`, `moat.*`, `overview.thesis`, `business.quality`, `business.phase*`, `growth.score`, `growth.scoreNote`, `growth.drivers`, `mgmt.scores`, `mgmt.note`, `peers` | Lo decide el usuario |

Un hecho es lo que dice un documento (una cifra, una fecha, una guía, un nombramiento, una cita de la dirección). Si el texto incluye una valoración tuya («la guía es conservadora», «el riesgo sube»), sepáralo: el dato va como hecho y la valoración en un campo de criterio. El script ignora el `tipo` si el campo no está en la lista de hechos: lo trata como criterio.

### 8.2 Avisos de calidad del dato

Para cada aviso de `data/<T>.json → avisos` (nivel `aviso` o `error`) y de la web (modelo frente a SEC) que no esté en `analysis/<T>.json → avisos_aprobados`, intenta explicarlo con los documentos oficiales:

- **Cruza dos fuentes:** la cifra XBRL frente a la nota de resultados (Exhibit 99.1) o el propio 10-Q/10-K. Si coinciden, la cifra es buena.
- **Cuadres:** activo = pasivo + patrimonio neto + minoritarios; los cuatro trimestres suman el año (`resultados.*.trimestral` frente a `anual`).
- **Saltos:** busca la causa en el MD&A y en las notas (coberturas a valor de mercado, compras, ventas de negocio, reexpresiones, estacionalidad).

Si queda explicado con un documento, añádelo a `avisos_resueltos`: `{codigo, nivel, mensaje, comprobacion, fuente: {t, u, d}}`, con `codigo`, `nivel` y `mensaje` **copiados exactos** del aviso y en `comprobacion` las cifras que lo explican (p. ej. «Nota 4 del 10-Q: la valoración a mercado de las coberturas suma −1.735 M$ en 2T22; los ingresos por contratos con clientes solo bajan un 4%»). Si no puedes explicarlo, no lo incluyas: le llegará al usuario.

Las notas técnicas (nivel `info`) no hace falta resolverlas: la web ya no las enseña en la cabecera.

### 8.3 Qué criterio se propone y cuándo

- **Supuestos del DCF (`v.*`):** solo si mueven el valor por acción un 5% o más. Mídelo con `node scripts/impacto_dcf.mjs <T>` (usa el mismo motor que la web); el script de aplicación vuelve a medirlo y descarta lo que no llegue.
- **Riesgos, MOAT, veredicto, tesis y puntuaciones:** solo con una novedad material (criterio de `ACTUALIZACION_COMPLETA.md`, apartado 5, punto 3).
- **Cuándo le llega al usuario:**
  - Con resultados o un 10-Q/10-K nuevo (`urgente: true`): ese mismo día.
  - Con una novedad grave (`urgente: true`): ese mismo día. Grave es un movimiento del precio de más del 10% en un día con causa clara, un cambio de guía, una compra o venta relevante, la salida del consejero delegado o del director financiero, o lo que vigila `seguimientos.json` (p. ej. el préstamo del DOE a Vistra). También, sin marcarlo, cuando los supuestos mueven el valor un 10% o más.
  - Todo lo demás: a la cola semanal (`propuestas/_cola/<T>.json`), que el script publica el sábado en una sola propuesta por compañía.

### 8.4 Ajustes por hechos posteriores

Si después del cierre del último 10-Q/10-K hay hechos que cambian acciones, caja o deuda (compras pagadas, emisiones o amortizaciones de deuda o de preferentes, ampliaciones), propón `ajustes_posteriores` con la lista completa: `{"k": "debt" | "cash" | "shares", "delta": <millones, con signo>, "base_accn": <data/<T>.json → ultimo_informe.accn>, "porque": "…", "fuente": {t, u, d}, "fecha": "<hoy>"}`. Usa solo cifras de la SEC o de la compañía; si una cifra es aproximada («hasta 1.250 M$»), dilo en `porque`. La web suma el ajuste al dato de la SEC y, cuando llega el siguiente informe, deja de aplicarlo; el script lo quita del análisis. Conserva los ajustes que fijó el usuario (`origen: "usuario"`) salvo que un documento nuevo los contradiga.

### 8.5 Verificación con un segundo agente

Lanza un agente nuevo (herramienta Agent, `subagent_type: "general-purpose"`) que **no** haya redactado la propuesta, con este encargo: para cada compañía con `propuestas/<T>.json`, y para cada cambio con `tipo: "hecho"` sin `procesado` y cada entrada de `avisos_resueltos`:

1. Abrir la fuente citada (`fuente.u`; si sec.gov no es accesible, la misma nota en la web de la compañía, Business Wire o PR Newswire).
2. Comprobar que **cada número, fecha y nombre** del `valor` (o de la `comprobacion`) aparece en la fuente o en `data/<T>.json`, con el mismo significado, y que el texto no afirma nada que la fuente no diga.
3. Escribir en el cambio `"verificacion": {"ok": true|false, "nota": "<qué comprobó o qué no cuadra, una línea>"}`. Con una sola cifra que no cuadre, `ok: false`. Para `avisos_resueltos`, si no cuadra, quitar la entrada y decirlo en el resumen.

El agente solo escribe el campo `verificacion` (y quita avisos no comprobados): no cambia valores ni añade cambios.

### 8.6 Aplicar y guardar

1. `python scripts/aplicar_cambios.py --todas` (el sábado, `--todas --sabado`). Imprime por compañía qué se ha aplicado, qué falla la verificación, qué queda para hoy, qué va a la cola y qué se ha descartado.
2. Valida los JSON tocados con `python -m json.tool` y ejecuta `python -m pytest -q tests/test_aplicar_cambios.py`.
3. Commit en `main`: `Aplicado automáticamente: <T1> (<n> cambios), <T2> (…)` y, si quedan propuestas o cola, `Propuestas: …`. Push.

