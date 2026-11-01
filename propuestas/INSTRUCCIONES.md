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

## 5. Guardar

1. Escribe `propuestas/<T>.json` y actualiza `propuestas/_estado.json` → `revisado.<T> = {accn, fecha}`.
2. Valida que ambos son JSON correctos (`python -m json.tool`).
3. Commit en `main`: `Propuesta: <T> tras resultados <periodo>` y push. La web y el aviso por email se actualizan solos.
