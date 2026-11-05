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

**3. Crea las claves de precios (gratuitas).**
- **Histórico de cotizaciones (Twelve Data):** regístrate en <https://twelvedata.com> (plan *Basic*), copia tu *API key* y créala como secret `TWELVEDATA_API_KEY`. Sin ella, la web funciona pero no muestra la evolución del precio ni los múltiplos históricos.
- **Cotización y recomendaciones (Finnhub):**
- Regístrate en <https://finnhub.io/register> y copia la *API key* de tu panel.
- *Settings → Secrets and variables → Actions → pestaña **Secrets** → **New repository secret***
- Nombre: `FINNHUB_API_KEY`, valor: la clave.
- Sin esta clave todo funciona salvo el precio, y la web lo avisa.
- **Reacción en after-hours y premercado (Alpaca, opcional):** abre una cuenta gratuita en <https://app.alpaca.markets/signup> (no hace falta depositar dinero; vale la cuenta de prueba, *Paper*). En el panel, *API Keys → Generate New Keys*, y crea dos secrets: `ALPACA_API_KEY_ID` (la *Key ID*) y `ALPACA_API_SECRET_KEY` (la *Secret Key*). Con ellas, el informe de resultados muestra la reacción de la acción fuera de horario (después del cierre y antes de la apertura, con 15 minutos de retraso) en lugar de «pendiente». Sin ellas, la reacción aparece al día siguiente con el cierre.
- **Noticias con sentimiento (Marketaux y Alpha Vantage, opcionales):** amplían la prensa financiera más allá de Finnhub (Benzinga, Motley Fool, Zacks, CNBC…).
  - Marketaux: regístrate en <https://www.marketaux.com/register>, copia tu *API token* y créalo como secret `MARKETAUX_API_KEY` (plan gratuito: 100 consultas al día).
  - Alpha Vantage: pide la clave gratuita en <https://www.alphavantage.co/support/#api-key> y créala como secret `ALPHAVANTAGE_API_KEY` (plan gratuito: 25 consultas al día; da el sentimiento de cada noticia sobre la compañía).
  - Sin ellas todo funciona igual, con Finnhub, los medios del sector y los 8-K. Para comprobarlas, lanza el workflow **Probar fuentes de noticias**.

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

## Añadir una compañía

1. En GitHub, pestaña **Actions** → **Añadir compañía** (columna izquierda) → botón **Run workflow**. También puedes llegar desde la web: selector de compañías → **＋ Añadir compañía**.
2. Escribe el **ticker** (por ejemplo `MSFT`; para clases con punto vale `BRK.B`). *Nombre* y *color* son opcionales: si los dejas vacíos, el nombre se toma de la SEC (sin «Inc.», «Corp.»…) y el color de marca se saca del logo.
3. Pulsa **Run workflow**. En unos 3 minutos el círculo se pone verde y, tras la publicación automática, la compañía aparece en la web.

Qué hace el robot (`fetcher/add_company.py`):

- Resuelve el CIK con <https://www.sec.gov/files/company_tickers.json>. Si el ticker no existe, o la compañía presenta 20-F/40-F (emisor extranjero, normalmente IFRS), **no añade nada**: la ejecución termina en rojo, el resumen explica el motivo y se abre un Issue.
- Añade la compañía al final de `companies.json` (ticker, nombre, CIK, color y monograma).
- Descarga sus datos como cada noche (SEC, precio, histórico, logo, segmentos, directivos, riesgos del 10-K) y crea `analysis/<TICKER>.json` y `manual/<TICKER>.json`.
- Prepara el punto de partida del DCF con las cifras reales de los últimos 12 meses: ingresos base, crecimiento a partir del CAGR de 3 años moderándose, margen EBITDA, amortizaciones, capex, pago en acciones, tipo impositivo efectivo (entre 15% y 25%) y BPA. WACC 9%, crecimiento perpetuo 3% y múltiplos estándar. Acciones, caja y deuda siguen a la SEC. La web marca la compañía como «recién añadida» hasta que rellenes «Análisis a».
- Hace un commit `Alta de compañía: <TICKER>`. Si el ticker ya estaba en la lista, solo actualiza sus datos.

Para **quitar** una compañía, borra su línea de `companies.json` (los archivos de `data/`, `analysis/` y `manual/` pueden quedarse como archivo histórico o borrarse).

## Comparativa con competidores e informe PDF

- **Comparativa con competidores** (pestaña *Valoración*): capitalización, crecimiento de ingresos, márgenes bruto, operativo y de FCF, PER, precio/ventas, EV/EBITDA, rentabilidad por FCF y deuda neta/EBITDA de la compañía frente a cada competidor y a su mediana, con colores (mejor o peor en más de un 15%), un gráfico de crecimiento frente a múltiplo y lo que valdría con el EV/EBITDA de la mediana. Las cifras de los competidores salen de la SEC con las mismas reglas (se recalculan una vez por semana) y el precio de Finnhub cada noche. Los que presentan 20-F no se comparan.
- **Lista de competidores:** la de `analysis/<TICKER>.json` → `"peers"` (tu criterio; se edita en la web con «Editar», un ticker por línea) o, si está vacía, la de Finnhub (misma industria). Los cambios se aplican en la siguiente actualización nocturna.
- **Informe PDF:** botón «Informe PDF» en la barra superior. Muestra una vista de informe (portada con cifras clave, tesis y conclusión, y después todas las secciones con sus gráficos, cada una en página nueva) y «Imprimir / Guardar PDF» abre el diálogo del navegador: elige «Guardar como PDF». Los controles, las listas largas plegadas, las redes sociales y el glosario no se imprimen.

## Seguimiento, avisos y guardar desde la web

- **Seguimiento** (botón en la barra superior, o `valorador.html#seguimiento`): todas las compañías en una tabla ordenable con precio y variación del día, valor razonable, potencial, distancia a tu precio de compra, recomendación, puntuación, PER, crecimiento, próximos resultados, antigüedad del análisis y avisos. Arriba, cuántas están en zona de compra, cuántas presentan resultados en 14 días y qué análisis toca revisar. Pulsa una fila para abrir la compañía.
- **Avisos por email.** Tras cada actualización nocturna, `fetcher/alerts.py` compara los datos nuevos con los del día anterior y, si hay algo, abre un Issue con la etiqueta `aviso` que GitHub te envía por correo: cotización que entra en tu zona de compra («comprar por debajo de» del Veredicto), 10-Q/10-K u 8-K de resultados nuevos, compras de directivos en mercado, movimientos de más del 8% en el día, resultados en los próximos 2 días y análisis de más de 90 días. Cada aviso se envía una sola vez (estado en `data/_avisos_estado.json`). Si no te llegan, revisa en GitHub *Settings → Notifications* que el email esté activado para *Issues* y que sigues el repositorio (*Watch*). Cierra los Issues cuando los leas.
- **Guardar desde la web.** En «Mi análisis» → *Guardar directamente en GitHub*, pega una vez un token fine-grained con acceso solo a este repositorio y permiso *Contents: Read and write* (los pasos están en la propia web). Se guarda solo en ese navegador. Desde entonces la franja de cambios muestra «Guardar en GitHub», que hace el commit de `analysis/<TICKER>.json` (opcionalmente con «Análisis a» = hoy); la web publicada se actualiza en 1–2 minutos y la versión entra en el historial de veredictos. Si caduca o lo pierdes, se crea otro igual; «Olvidar el token» lo borra del navegador.

## Revisión tras resultados (propuestas)

Cuando una compañía presenta resultados, una tarea programada de Claude (cada mañana laborable) lee la nota de resultados y la llamada con analistas y deja una **propuesta** en `propuestas/<TICKER>.json`, siguiendo `propuestas/INSTRUCCIONES.md`. Nunca modifica `analysis/`.

- La web muestra un aviso «Propuesta de actualización» en la compañía. «Revisar la propuesta» enseña cada cambio con lo que hay ahora, lo propuesto y por qué; marca los que quieras y «Aplicar los marcados como borrador». Revisa en la web, retoca con «Editar» y guarda con «Guardar en GitHub»: al guardar, la propuesta se borra sola. «Descartar la propuesta» la elimina sin aplicar nada.
- Te llega también un aviso por email («Propuesta de actualización de …»).
- `propuestas/_estado.json` guarda el último 8-K de resultados revisado por compañía, para no repetir propuestas.

## Informe de resultados (PDF por presentación)

Cada vez que una compañía presenta resultados se genera un informe de 3 páginas A4 en `resultados.html` y su PDF en `data/resultados/<TICKER>/<periodo>.pdf`:

1. **Resultados frente a estimaciones.** Ingresos, segmento clave, beneficio operativo, beneficio neto y BPA: reportado, estimado, diferencia, *Beat/Miss* e interanual. Debajo, la guía para el siguiente periodo frente a lo esperado, cuatro claves del trimestre, la cotización de 12 meses (capitalización, mínimo, máximo), la cita de la dirección y la reacción en bolsa.
2. **El trimestre por dentro.** Crecimiento por línea de negocio (si la compañía lo publica), margen operativo, *run-rate* del segmento que más crece, ingresos trimestrales con su crecimiento interanual, **calidad del beneficio** (beneficio neto frente a caja operativa, capex y flujo de caja libre de los últimos 5 trimestres), **estructura de costes** en % de los ingresos frente al año anterior y **retribución al accionista** (recompras, dividendos, dilución y pago en acciones). Todo del XBRL de la SEC; si algo no cabe en el A4, se omite el bloque menos importante.
3. **Lectura del trimestre y guía.** Tu resumen de la presentación (Directiva → `mgmt.call`) o, si aún no lo has revisado, la propuesta pendiente; lo destacado (frases y tabla de cifras) y la guía de la nota **traducidos al español**; fuentes con enlace.

**El día de resultados**, en la web: *Más → Informe de resultados* (o el enlace «Informe de resultados (PDF)» del resumen del último trimestre) → **⟳ Actualizar resultados**. Lanza el Action solo para esa compañía (SEC, precio, informe y PDF) y avisa cuando termina (3–5 minutos). El token guardado en el navegador necesita, además de *Contents*, el permiso **Actions: Read and write**. Sin token, el botón explica cómo lanzarlo a mano: *Actions → Actualizar datos → Run workflow* con el ticker en «Tickers». Si no pulsas nada, la actualización nocturna lo genera igualmente.

De dónde sale cada cifra:

| Bloque | Fuente |
|---|---|
| Cifras del trimestre | XBRL del 10-Q/10-K. El día de resultados aún no hay 10-Q: se leen las tablas de la nota (8-K, Exhibit 99.1) y el informe sale marcado **provisional**. Cuando llega el 10-Q (Amazon al día siguiente; Broadcom, 1–2 semanas después), la actualización nocturna lo sustituye por las cifras definitivas y rehace el PDF. |
| Segmentos y *run-rate* | XBRL con dimensiones. La primera vez se leen unos 14 informes (≈4 años) y se guardan en `data/resultados/<T>/_segmentos.json`; después se añade cada trimestre nuevo. |
| Estimaciones de ingresos y BPA | Finnhub (gratis). Como Finnhub solo enseña el próximo trimestre, cada noche de los 30 días previos se guarda una foto del consenso en `data/estimaciones/<T>/<fecha>.json` (con sus revisiones). |
| Estimaciones de EBIT, segmentos y guía | No hay fuente gratuita: se escriben a mano en `manual/<T>.json` → `estimaciones_resultados` (desde la propia página del informe, panel «Estimaciones para el próximo informe», con *Guardar en GitHub*). Lo manual manda sobre Finnhub. |
| BPA ajustado | Si el consenso de Finnhub está en BPA ajustado (non-GAAP) y difiere del contable, el *Beat/Miss* se calcula en la base del consenso y la tabla muestra los dos. |
| Guía | Horquillas leídas del texto de la nota; se compara su punto medio con tu estimación o, para las ventas, con el consenso del trimestre siguiente guardado la primera vez que se genera el informe. |
| Reacción en bolsa | Cierre del día de resultados frente al siguiente (si presentan tras el cierre) o del día anterior frente al de resultados (antes de la apertura), con el histórico de Twelve Data. Hasta que existe ese cierre, se usa la cotización fuera de horario de Alpaca (after-hours y premercado, SIP con 15 min de retraso; secrets `ALPACA_API_KEY_ID` y `ALPACA_API_SECRET_KEY`) o la de Finnhub, y se marca provisional. |
| Traducción de la nota | Las filas de tablas y las horquillas de la guía se traducen solas con un glosario (`fetcher/traduccion.py`). Las frases, con `i18n/notas_es.json`, que rellena la tarea «Revisión tras resultados» (o tú a mano); lo pendiente se ve en inglés con la marca «sin traducir». `python -m fetcher.traduccion` lista lo que falta. |

Formato de `estimaciones_resultados` (cifras en millones de dólares; BPA en $/acción; lo que no tengas, `null`):

```json
"estimaciones_resultados": [
  {"periodo": "4T26", "fuente": "Investing", "fecha": "1-feb-2027",
   "ingresos_M": null, "bpa": null, "beneficio_operativo_M": 33100,
   "segmentos_M": {"Amazon Web Services Segment": 49800},
   "guia_ingresos_M": 262000, "guia_beneficio_operativo_M": null,
   "segmento_clave": ""}
]
```

El PDF solo se regenera si el informe cambia (huella en `data/resultados/<T>/index.json`), así que no se acumulan PDF repetidos.

**Cambios que no vienen de la SEC.** Cuando guardas tu resumen de la presentación (`analysis/`), tus estimaciones (`manual/`) o una traducción (`i18n/notas_es.json`), el workflow **Rehacer informes** regenera en un par de minutos el informe y el PDF de esa compañía, sin descargar de nuevo la SEC. También se puede lanzar a mano (*Actions → Rehacer informes → Run workflow*).

## La web

`valorador.html` carga `companies.json` y, para cada compañía, `data/<TICKER>.json` (cifras de la SEC y cotización), `analysis/<TICKER>.json` (tu criterio) y `manual/<TICKER>.json` (precios objetivo). No guarda nada en ningún servidor.

- **Fuente y fecha de cada cifra.** Junto a cada cifra importante aparece su origen («SEC 10-Q · 29-oct-26», «Finnhub · 30-oct-26» o «manual»). Al pasar el ratón se ve la etiqueta XBRL y el periodo; al hacer clic se abre el filing en EDGAR. La pestaña *Fuentes* tiene la tabla completa, el último 10-Q/10-K, el 8-K de resultados y su Exhibit 99.1.
- **Finanzas.** Tabla con conmutador *Cifras / % de ingresos / Crecimiento*, evolución de márgenes (bruto, EBITDA, operativo, neto y FCF), sección *Deuda y solvencia* (deuda al cierre de cada ejercicio, deuda neta, deuda neta/EBITDA, cobertura de intereses, liquidez y calendario de vencimientos del último informe) y *Ratios* (ROE, ROA, ROIC, ROCE, CROIC, deuda/capital, liquidez corriente, prueba ácida, BPA, valor contable por acción y múltiplos al precio actual). EBITDA = beneficio operativo + amortizaciones; el bruto, si la compañía no lo etiqueta, = ingresos − coste de ventas. La deuda no incluye arrendamientos.
- **Bonos y tipo de deuda.** El robot lee además el XBRL completo (con dimensiones) del último 10-K y de los 10-Q posteriores (`fetcher/bonds.py`) y guarda cada emisión vigente en `data/<TICKER>.json` → `bonos`: nombre, tipo (bono senior, convertible, garantizada, préstamo, línea de crédito, papel comercial…), cupón o diferencial si es variable, vencimiento, nominal en su divisa e importe en libros. La web muestra el coste efectivo de la deuda (intereses / deuda media), el cupón y el vencimiento medios ponderados, la deuda en otras divisas, la composición por tipo y, si las emisiones cubren al menos el 70% de la deuda, un calendario de vencimientos reconstruido que incluye la deuda emitida después del 10-K. Cada empresa etiqueta a su manera: unas por bono (AppLovin, Broadcom, Vistra) y otras por emisión en varios tramos sin cupón ni vencimiento (Amazon, Alphabet); en ese caso la web lo indica.
- **Calendario de vencimientos del 10-K.** Si sus tramos suman menos del 85% de la deuda actual, la web avisa de que la deuda emitida después no aparece hasta el siguiente informe anual.
- **Métricas y su construcción.** Cada métrica lleva un botón *i* que abre su ficha: qué mide, fórmula, cálculo con las cifras de la compañía (numerador y denominador con su enlace a la SEC), cómo leerla y en qué se diferencia de otras fuentes. La pestaña *Fuentes* tiene el glosario completo. Están repartidas por la pregunta que responden: márgenes, caja y ratios históricos en *Finanzas*; CAGR de ingresos, BPA y FCF frente a tu modelo y al precio en *Crecimiento*; ROIC, ROCE y ROE frente al WACC en *MOAT*; retribución al accionista (recompras, dividendos, pago en acciones, dilución) en *Directiva*; semáforo de riesgo financiero en *Riesgos*; y múltiplos de precio (real frente a tu modelo) en *Valoración*. Los splits que los informes antiguos no reexpresan se detectan y ajustan (Broadcom 10×1), y el capex que una empresa deja de etiquetar por inmaterial se asume 0 con aviso (AppLovin).
- **Valoración.** Arriba, a todo el ancho: *Precio: de dónde viene y hacia dónde puede ir* (cotización de 1, 3 o 5 años y, a la derecha, el precio de cada escenario de tu modelo, el valor ponderado y el consenso a tu horizonte de inversión, con la zona de compra sombreada) y *Múltiplos al precio actual* (hoy, media, mínimo y máximo históricos, percentil y tu modelo, con la gráfica del PER o del precio/ventas en el tiempo). Debajo de los resultados del DCF, *Supuestos del modelo: qué supones y qué implica*: crecimiento, margen EBITDA, WACC y valor terminal, cada uno con qué significa, con qué compararlo (datos reales de la compañía), una valoración automática (conservador / en línea / ambicioso) y el efecto de cambiarlo en el valor; el resto, plegado en *Supuestos detallados*. Al final, la *Sensibilidad del DCF* en dos versiones: WACC × crecimiento perpetuo y crecimiento × margen, con el potencial de cada casilla y una lectura con tus cifras.
- **Avisos.** Bajo la cabecera de cada compañía hay una franja con los avisos del Action y los que calcula la web: si la deuda, la caja o las acciones de tu modelo difieren más de un 20% del dato de la SEC, aparece un aviso y, en *Valoración*, el botón «Usar dato SEC».
- **Supuestos que siguen a la SEC.** Si en `analysis/<TICKER>.json` no pones `v.shares`, `v.cash` o `v.debt`, el DCF usa el último dato de la SEC y se actualiza solo cada noche.
- **Editar tu análisis.** «Editar» funciona como antes, pero los cambios se guardan como borrador en tu navegador. Para publicarlos, pulsa «Descargar <TICKER>.json» y súbelo a la carpeta `analysis/` del repositorio (*Add file → Upload files*, sustituyendo el archivo). La web te lleva a esa página de GitHub.
- **Cambios del valorador antiguo.** Si editaste algo en la versión anterior, en ella pulsa «Datos → Copiar JSON» y pégalo en «Mi análisis → Importar como borradores».
- **En local**, abre la carpeta con `python -m http.server` y entra en `http://localhost:8000/valorador.html` (abriendo el archivo con doble clic el navegador bloquea la lectura de los JSON).

## Precio en vivo durante la sesión (opcional)

El cierre de cada noche sigue siendo el dato guardado en `data/`. Además, mientras Wall Street está abierto (9:30–16:00 en Nueva York; 15:30–22:00 en España, salvo las semanas de cambio de hora), la web pide la cotización cada minuto a un **Cloudflare Worker** tuyo, que consulta Finnhub con la clave guardada como secreto. La clave nunca llega al navegador.

- La cabecera muestra «● en vivo · 16:42» y la variación de la sesión; la lista de seguimiento, la cartera, la capitalización, los múltiplos y el potencial del DCF se recalculan con ese precio. Las cifras de la SEC no cambian.
- Fuera de sesión deja de preguntar. Si el último cierre de Finnhub es más reciente que el de `data/` (entre las 22:00 y la ejecución nocturna), la web lo usa y lo marca «Finnhub · cierre».
- Si el Worker no responde, la etiqueta pasa a «sin conexión» y la web vuelve al cierre de `data/`. Reintenta cada 2 minutos.
- Si la pestaña está en segundo plano no hace peticiones.
- El Worker guarda cada cotización 30 s en memoria: con 10 compañías son unas 10 llamadas por minuto a Finnhub aunque tengas la web abierta en varios dispositivos (el plan gratuito permite 60).
- Solo responde a peticiones de tu web (`https://infomercadosgbx.github.io`). Es una protección básica: si la clave se agotara por un uso ajeno, cámbiala en Finnhub y en el secreto del Worker.

### Puesta en marcha (unos 5 minutos)

1. En el panel de Cloudflare: *Workers & Pages → Create → Create Worker*. Nombre: `valorador-precio`. Pulsa *Deploy*.
2. *Edit code*: borra el contenido, pega el de [`worker/precio.js`](worker/precio.js) y pulsa *Deploy*.
3. En el Worker, *Settings → Variables and Secrets → Add*: tipo **Secret**, nombre `FINNHUB_API_KEY`, valor tu clave de Finnhub (la misma del secret de GitHub). Guarda con *Deploy*.
4. Copia la dirección del Worker, del tipo `https://valorador-precio.<tu-subdominio>.workers.dev`. Si la abres en el navegador verás «Origen no permitido»: es lo esperado.
5. En GitHub edita [`ajustes.json`](ajustes.json) y pon esa dirección en `precio_vivo_url`. Al hacer commit se vuelve a publicar la web.

Si sirves la web desde otro dominio, añádelo en el Worker como variable de texto `ORIGENES` (varios separados por comas). Para desactivarlo, deja `precio_vivo_url` vacío.

## Mercado hoy (menú principal)

Encima de las tarjetas del menú principal hay una franja con indicadores básicos del mercado. La escribe el workflow **Mercado hoy** (`.github/workflows/mercado-hoy.yml`) en `data/_mercado_hoy.json` dos veces cada día laborable: a las 15:07 UTC (FRED ya tiene el cierre del día anterior y, los jueves, la AAII su encuesta) y a las 23:47 UTC (tras el cierre). Va aparte de la actualización de compañías: si una de estas fuentes falla, los datos de la SEC no se ven afectados.

| Indicador | Fuente | Frecuencia |
|---|---|---|
| S&P 500, Nasdaq, VIX, petróleo WTI, diferencial high yield | FRED (Reserva Federal de St. Louis) | Cierre diario, con un día de retraso; el WTI, con dos o tres |
| Bono de EE. UU. a 5 y 10 años | Departamento del Tesoro (curva diaria) | Cierre diario |
| HYG, LQD, KRE, MSCI World (ETF URTH), Corea (ETF EWY) | Finnhub | Cierre diario y **en vivo** durante la sesión con el Worker |
| EUR/USD, oro, bitcoin | Twelve Data | Diario |
| Estrés financiero | OFR (Oficina de Investigación Financiera del Tesoro) | Diario, con dos días hábiles de retraso |
| Encuesta AAII | aaii.com (el propio emisor) | Semanal (jueves) |
| Miedo y codicia (índice propio) | Calculado con FRED y el Cboe | Diario |
| NAAIM, miedo y codicia de CNN, MOVE | **Manual** (no tienen fuente gratuita) | Cuando los apuntes |

Durante la sesión, el S&P 500 y el Nasdaq muestran además la variación en vivo de SPY y QQQ al lado del cierre oficial. No hace falta tocar el Worker: ya acepta cualquier ticker.

**Miedo y codicia propio.** Sigue la receta del índice de CNN con los componentes que tienen fuente oficial: impulso (S&P 500 frente a su media de 125 sesiones), volatilidad (VIX frente a su media de 50), demanda de bonos basura (diferencial high yield menos el de grado de inversión), demanda de refugio (bolsa frente al bono a 10 años en 20 sesiones) y ratio put/call del Cboe (media de 5 sesiones). Cada componente se puntúa de 0 a 100 según su percentil en los dos últimos años (el put/call, por tramos fijos: 1,15 o más = 0; 0,75 o menos = 100) y el índice es la media. Faltan los dos componentes de amplitud de la NYSE, que no tienen fuente gratuita, así que el número no coincide exactamente con el de CNN. Tramos: menos de 25 miedo extremo, 25–45 miedo, 45–55 neutral, 55–75 codicia, más de 75 codicia extrema.

**Valores manuales.** El dato actual de la NAAIM es de pago (la web pública lo da con tres meses de retraso), CNN no tiene API y el MOVE es de ICE. Se apuntan con el botón **✎ Apuntar valores** de la franja (guarda en `manual/_mercado.json` si tienes GitHub conectado en ⚙ Ajustes) o editando ese archivo. Si un día no se puede leer la AAII, también se apunta ahí y la web usa el dato más reciente.

### Puesta en marcha (2 minutos)

1. Crea una clave gratuita de FRED en [fredaccount.stlouisfed.org/apikeys](https://fredaccount.stlouisfed.org/apikeys) (pide registrarse con un email).
2. En GitHub: *Settings → Secrets and variables → Actions → New repository secret*. Nombre `FRED_API_KEY`, valor la clave. Sin ella también funciona (usa la descarga CSV oficial de FRED), pero la API es más estable.
3. *Actions → Mercado hoy → Run workflow*. Al terminar, recarga la web.

Las fuentes que no respondan aparecen en un aviso plegable al pie de la franja y en el log del Action; se mantiene el último dato que sí se leyó, marcado «sin actualizar».

## Qué hace cada noche

1. Ejecuta los tests. Si fallan, no se toca ningún dato.
2. Para cada compañía de `companies.json`: descarga `companyfacts` y `submissions` de data.sec.gov, aplica las reglas de extracción, valida y escribe `data/<TICKER>.json`.
3. Pide precio y recomendaciones de analistas a Finnhub.
4. Hace commit solo si cambió algún archivo (el sello de hora no cuenta como cambio).
5. Si la SEC no devuelve nada para alguna compañía, el Action termina en rojo y abre un Issue (o comenta en el que ya esté abierto) con el error. Las demás compañías se actualizan igualmente.

**Días de resultados.** Además, el mismo workflow se ejecuta de lunes a viernes a las 7:37 y 9:22 h de Nueva York (antes de la apertura) y a las 16:41 h (tras el cierre), pero solo actualiza las compañías que presentan ese día según el calendario de Finnhub (o las que presentaron el día anterior tras el cierre, para recoger el premercado). Si no presenta ninguna, termina sin hacer nada. Así el informe, su PDF y la reacción fuera de horario se generan solos; el botón «⟳ Actualizar resultados» sigue sirviendo para adelantarlo.

## Estructura

| Ruta | Qué es | ¿Quién lo edita? |
|---|---|---|
| `companies.json` | Única lista de compañías: ticker, nombre, CIK, color, monograma | Tú (o el alta automática, fase 3) |
| `data/<TICKER>.json` | Datos automáticos con fuente de cada cifra | **Solo el Action. Nunca a mano.** |
| `data/index.json` | Resumen de todas las compañías para la web | Solo el Action |
| `analysis/<TICKER>.json` | Tus supuestos y textos: DCF, scorecard, veredicto, directiva, MOAT, riesgos, última presentación de resultados (`mgmt.call`) y series por segmento que la SEC no publica (`fin_manual`) | Tú, versionado en git |
| `analysis/_plantilla.json` | Análisis en blanco para compañías nuevas | — |
| `manual/<TICKER>.json` | Consenso de precios objetivo y estimaciones de resultados introducidos a mano (la web lo marca «manual») | Tú |
| `data/resultados/<TICKER>/` | Informe de resultados de cada presentación (JSON y PDF) e histórico de segmentos | Solo el Action |
| `data/estimaciones/<TICKER>/` | Foto del consenso de Finnhub antes de cada presentación | Solo el Action |
| `resultados.html` | El informe de resultados (pantalla, impresión y PDF) | — |
| `fetcher/` | Código Python (solo biblioteca estándar) | — |
| `tests/` | Tests sintéticos de cada regla y tests de aceptación con fixtures reales | — |
| `valorador.html` | La web | — |
| `ajustes.json` | Ajustes de la web: dirección del Worker de precio en vivo | Tú |
| `data/_mercado_hoy.json` | Indicadores de «Mercado hoy» | Solo el Action |
| `manual/_mercado.json` | Prima de riesgo del WACC y valores manuales de «Mercado hoy» (NAAIM, CNN, MOVE) | Tú (o el botón «Apuntar valores») |
| `worker/` | Cloudflare Worker del precio en vivo (se pega en Cloudflare, no se publica en Pages) | — |

## Fuentes de datos

- **Cifras financieras:** solo SEC EDGAR (`data.sec.gov/api/xbrl/companyfacts` y `data.sec.gov/submissions`), con User-Agent identificado, como máximo 5 peticiones por segundo y reintentos con espera creciente.
- **Precio:** Finnhub, endpoints `/quote` y `/stock/metric` (rango de 52 semanas) (API oficial, plan gratuito de 60 llamadas por minuto). Proveedor abstraído en `fetcher/prices.py`; para cambiarlo basta con otra clase `PriceProvider`.
- **Consenso:** las recomendaciones (compra/mantener/venta) llegan de Finnhub `/stock/recommendation`, gratuito. Los **precios objetivo** son de pago en Finnhub, así que van en `manual/<TICKER>.json` y la web los marcará como «manual».
- **Mercado hoy:** FRED, Tesoro, OFR, Cboe, Finnhub y Twelve Data por sus API o descargas oficiales. La única lectura de una página web es la encuesta de la AAII en aaii.com, que es quien publica el dato; si falla, se apunta a mano.
- No se hace scraping de webs de terceros.

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

## Noticias

Cada noche, la pestaña Fuentes reúne hasta 30 titulares del último mes de cuatro orígenes, sin leer ninguna web:

| Origen | Qué aporta | Cómo se obtiene |
|---|---|---|
| Prensa financiera | Yahoo Finance, Seeking Alpha, Benzinga, Motley Fool, Zacks, CNBC… | APIs de Finnhub, Marketaux y Alpha Vantage (estas dos, opcionales y con sentimiento) |
| Medios del sector | Utility Dive, World Nuclear News, The Next Platform, Data Center Dynamics, AdExchanger, Digiday, Oil & Gas Journal, Food Dive… | Feed RSS que publica cada medio, filtrado por el nombre de la compañía y sus alias |
| Notas de prensa | Business Wire, PR Newswire, GlobeNewswire | Feed RSS de cada agencia; solo cuenta si la compañía está en el titular |
| Oficial | 8-K presentados a la SEC, con su tema en español | `submissions` de EDGAR (sin peticiones extra) |

- **Qué medios lee cada compañía:** campos `medios` (ids de `fetcher/news.py`) y `alias` (otros nombres: Google, AWS, VMware…) de `companies.json`. Al dar de alta una compañía se le asignan medios según su sector (código SIC); puedes cambiarlos a mano.
- **Sin duplicados y con variedad:** la misma noticia en dos medios cuenta una vez (gana el medio original sobre Yahoo), y cada medio tiene un tope (Yahoo 10, el resto 6).
- **Se acumula:** los feeds RSS solo muestran lo último, así que lo encontrado se conserva noche a noche durante 30 días.
- **Si un medio falla,** la compañía no recibe avisos: el estado de cada feed queda en `data/_noticias_estado.json`. El workflow **Probar fuentes de noticias** muestra qué feeds responden y qué titulares encuentran para un ticker.
- **Reuters, FT, Bloomberg, WSJ e Investing** no ofrecen API ni RSS públicos para esto. Sus artículos se leen para escribir el análisis con tu sesión iniciada en el navegador de la app de escritorio (ver `claude/fuentes-de-prensa.md` en el proyecto), y en la web quedan los enlaces «Buscar en…».

