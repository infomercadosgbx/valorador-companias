# Tarea programada: estructura (desde el 13-nov-2026)

La tarea «Valorador · revisión tras resultados y novedades» corre **de martes a viernes a las 07:41 (Madrid)**, después del robot de datos de cada noche. El lunes no corre: los datos del viernes por la noche los recoge el martes. Tiene tres partes, y cada cosa se hace **una sola vez**:

| Parte | Cuándo | Qué | Instrucciones |
|---|---|---|---|
| **A · Lo oficial** | Cada día (mar–vie) | Detectar y leer lo nuevo de la SEC y de la compañía; actualizar las pestañas que afecte | `INSTRUCCIONES.md`, apartados 1–7 (lista 7.5) |
| **B · Auditoría de datos** | Cada día (mar–vie) | Revisar lo que hizo A y las cifras del robot; aplicar solo lo verificado | `INSTRUCCIONES.md`, apartado 8 |
| **C · Repaso a fondo y mercado** | Una vez por semana por compañía (`companies.json → repaso`) | Webs oficiales, prensa, alertas de Gmail, analistas y redes; todas las pestañas al día | `ACTUALIZACION_COMPLETA.md`, apartados 5 y 7 |
| **Cierre semanal** | Viernes, al final | Publicar la cola de decisiones del usuario y la comparación DCF / analistas | `ACTUALIZACION_COMPLETA.md`, apartado 8 |

Compañías: solo las **activas** de `companies.json`. Las archivadas no se tocan. Las nuevas o reactivadas reciben el primer día el repaso completo (`ACTUALIZACION_COMPLETA.md`, apartado 0 bis).

## A · Lo oficial (cada día)

1. **Detectar qué hay nuevo** (barato, sin leer documentos): por compañía, `data/<T>.json` frente a `propuestas/_estado.json` — 8-K de resultados, 10-Q/10-K, otros 8-K, `presentaciones_sec`, formularios 4 fuera de plan, sala de prensa (`noticias` con `via` «Sala de prensa de la compañía»), `seguimientos`. Y `python scripts/senales.py --alarma --json` (movimientos de un día ≥ 10 % o seguimientos con cierre, cancelación o riesgo).
2. **Leer solo lo nuevo** y actualizar las pestañas que afecte: nota de resultados, presentación trimestral y llamada (Finanzas, Crecimiento, Directiva, tesis, veredicto); 10-Q/10-K (MD&A, notas, riesgos, hechos posteriores → `ajustes_posteriores`); otros 8-K y notas de prensa oficiales.
3. **Tras resultados**: revisión completa de la compañía con sus documentos oficiales de resultados (nota, presentación, llamada, 10-Q/10-K), traducción de la nota y consenso de analistas. Sus webs oficiales y la prensa se miran en su parte C de esa semana.
4. **Alarma**: si una compañía tiene una alarma y hoy no es su día de C, revisión corta de la causa (una o dos búsquedas, alertas de Gmail que la nombren, la fuente oficial que lo confirme).
5. Sin nada nuevo en una compañía: «oficial al día» en el resumen y nada más.

## B · Auditoría de datos (cada día)

1. **Verificación independiente** (apartado 8.5) de todo lo propuesto hoy por A y C: un agente que no ha redactado nada abre cada fuente y comprueba cada cifra, fecha y nombre.
2. **Calidad del dato** (8.2): avisos nuevos del robot y diferencias de más del 20 % entre el modelo y la SEC, explicados con el 10-Q/10-K o la nota de resultados.
3. **Supuestos del DCF** (8.3): solo si mueven el valor un 5 % o más (`node scripts/impacto_dcf.mjs <T>`).
4. **Aplicar** (`python scripts/aplicar_cambios.py --todas`; el viernes `--todas --cierre`), registro de fuentes, commit y resumen.

## C · Repaso a fondo y mercado (una vez por semana por compañía)

Las compañías cuyo `companies.json → repaso` es hoy (`python scripts/senales.py --repaso --json`), con ventana de 7 días:

1. **Webs oficiales** (`companies.json → webs_oficiales`): productos, presentación a inversores, día del inversor, casos de clientes, pipeline → Negocio, MOAT y Crecimiento.
2. **Mercado**: prensa financiera y sectorial, alertas de Gmail que la nombren, competidores, analistas (consenso en `manual/<T>.json`) y redes solo para el tono.
3. **Todas las pestañas al día** con los datos oficiales que A ha ido subiendo y B ha comprobado durante la semana: tesis (sin precio), textos del veredicto, noticias de impacto (`sources.news`), riesgos.
4. Cierra con `meta.asOf` y **`meta.repasoFondo`** = hoy (la web lo enseña como «repaso a fondo hoy / hace X días») y `python scripts/senales.py --marcar <T>`.
