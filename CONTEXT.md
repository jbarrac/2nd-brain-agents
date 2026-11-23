# 2nd Brain — Contexto del sistema

Sistema personal de organización de Javi. La raíz en Notion se llama
**"2nd AI Brain (Life OS)"** y se divide en tres capas:

| Capa | Qué es | Ritmo |
|---|---|---|
| 🧠 **2nd Brain** | Conocimiento: principios, identidad, aprendizajes, specs de cómo debe comportarse cada sistema o agente. | Se escribe cuando aprendes algo |
| 📋 **LifeOS** | Ejecución: Goals, Projects, Tasks, Habits, autoevaluaciones y KPIs. Fuente de verdad única de tareas. | Cambia a diario |
| 🗄️ **2NB Databases** | Contenedor de las 11 bases de datos. Sin lógica propia. | Estable |

Los agentes y automatizaciones leen y escriben en **LifeOS**. El **2nd Brain**
es solo lectura para ellos: aporta contexto, no recibe trabajo transaccional.

## Bases de datos

| DB | Rol | ¿La usa el código? |
|---|---|---|
| **Tasks [DB]** | Backlog de ejecución. | `brief.py`, `linter.py`, `groomer.py` |
| **Life Areas [DB]** | Las 7 áreas de vida. Cada tarea pertenece a una. | `brief.py` (vía `areas.yaml`) |
| **Goals (Long Term) [DB]** | Objetivos por área. | `linter.py` (huérfanas), `brief.py` (prioriza los Goals en curso) |
| **Projects [DB]** | Proyectos por área, cuelgan de Goals. | `linter.py` (huérfanas) |
| **Coaching Assessment [DB]** (antes "Weekly Self-Assessment") | Autoevaluación semanal (Health/Mental/Social/...). Su campo `Instagram (h)` se retiró al renombrar (09/08/2026): Instagram pasó a ser 100% manual vía KPI Readings, `kpis.py` ya no lee esta DB. | — |
| **Diario de Gratitud [DB]** | Una entrada por día de gratitud. | `kpis.py` |
| **KPIs [DB]** | Definición de cada KPI (`Clave`, Target, Frecuencia, Fuente, Estado). | `kpis.py` |
| **KPI Readings** | Serie temporal de lecturas por KPI. | `kpis.py` |
| **Dashboard Layout [DB]** | Qué KPI se pinta, cómo y en qué orden. Desacopla presentación de definición. | `kpis.py` |
| **Mindset [DB]** | Principios y creencias. Capa de conocimiento. | — |
| **Habits [DB]** | Hábitos. **Reservada para la futura app**; no la consume nada aún y no se borra. | — |

Jerarquía: `Life Areas → Goals → Projects → Tasks`. Las relaciones son
recíprocas y están completas.

## Campos de Tasks [DB]

`Task` (title) · `Status` (Not Started / In Progress / Done / Blocked / Parked) ·
`Type` (🤖 Agent / ⚙️ Semi / 👤 Manual) · `Priority` (🔴 Alta / 🟡 Media / 🟢 Baja) ·
`Context` · `Output (Expected)` · `Agent Result ` · `Life Area (Link)` ·
`Goals (Long Term) [DB]` · `Projects [DB]` · `Link` · `Attempts` · `Last Attempt`

## Las 7 áreas de vida

Internal (🔧, la meta-capa que mantiene el propio sistema), Professional,
Health, Mental, Finance, Social, Free Time. Solo **Internal** está `active: true`
en `config/areas.yaml`; las demás se activan al cerrar sus KPIs.

## Convenciones

- Idioma de los outputs: español. Nombres de entidades y campos: inglés.
- Todas las DBs llevan sufijo `[DB]` en el título.
- Lo que prepares se pinta en la **Página Fija** de la semana, que Javi abre
  cada día — no en `Agent Result `, que ya no lee nadie desde que se retiró
  `agent.py`. Sé conciso y accionable.
- `Status = Parked` significa «ahora no»: esas tareas no entran en el Foco
  semanal. Son un descarte deliberado de Javi, no un olvido.
- Desde el 14-nov-2026 **nada ejecuta tareas de principio a fin**. El lunes,
  `brief.py` elige 3 tareas del backlog y prepara su primer paso en la Página
  Fija; ejecutarlas es de Javi. El campo `Type` sigue describiendo cuánto puede
  automatizarse cada tarea, pero ya no decide quién la coge.
- Todo corre sin supervisión vía GitHub Actions: si falta información, es mejor
  decir qué falta que inventarla.
- Presupuesto de complejidad (ver `areas.yaml`): máx 3 workflows, 5 scripts,
  1 DB nueva por trimestre. Toda mejora que lo exceda debe proponer qué eliminar.
