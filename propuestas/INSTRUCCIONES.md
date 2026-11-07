# Revisión tras resultados: cómo preparar una propuesta

Estas instrucciones las sigue la tarea programada «Revisión tras resultados» (y cualquiera que prepare una propuesta a mano).
La propuesta **nunca** modifica `analysis/`: el usuario la revisa en la web, elige qué cambios aplica y los guarda él.

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

Cada cambio lleva un `porque` de una línea. Los listados se proponen completos (sustituyen al actual).

## 4. Formato de `propuestas/<T>.json`

```json
{
  "ticker": "RDDT",
  "creada": "2026-11-01",
  "motivo": "Resultados del 3T26 (8-K del 29-oct-2026)",
  "informe_accn": "0001713445-26-000114",
  "resumen": "Tres o cuatro frases: qué ha pasado, qué cambia en la tesis y qué cambios propones.",
  "fuentes": [{"t": "Nota de resultados 3T26 (8-K, Ex. 99.1)", "u": "https://www.sec.gov/..."}],
  "cambios": [
    {"campo": "overview.thesis", "valor": "…", "porque": "…"}
  ]
}
```

## 5. Traducir la nota al español

El informe de resultados (resultados.html y su PDF) copia de la nota los titulares («Lo destacado según la compañía»), la guía y la cita de la dirección. Las filas de tablas y las horquillas de guía se traducen solas; las frases, no.

1. Ejecuta `python -m fetcher.traduccion`: lista, por compañía, las frases sin traducir del último informe.
2. Añade cada una a `i18n/notas_es.json` → `t`, con el texto original **exacto** como clave (cópialo de la salida, sin tocar espacios ni comillas) y la traducción como valor.
3. Traducción fiel y en español claro: no resumas ni añadas nada. Cifras en formato español («1.400 M$», «4,30 $», «3T26»); nombres propios y de productos sin traducir; las llamadas a notas al pie como «(1)». Si el original está cortado, termina con «…».
4. Vuelve a ejecutar `python -m fetcher.traduccion` hasta que diga «Frases sin traducir: 0» y valida el JSON.

Al hacer push, el workflow «Rehacer informes» regenera los informes y sus PDF en un par de minutos.

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
- `motivo`: «10-Q del 3T26 (presentado el 9-nov-2026)» o el equivalente. Campos típicos: `overview.keyFacts`, `fin_manual.q` (solo series que la SEC no publica; el resto de Finanzas lo pone el robot), `business.clients`, `risks`, `mgmt.call.cap`, `v.debt`, `v.cash`, `v.shares` y los supuestos del DCF que cambien.
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
