# 2nd Brain Agents

## Proyecto
Agente ejecutor que lee tareas de Notion, ejecuta UNA por invocación con Claude
(Anthropic API) y escribe el resultado de vuelta en Notion. GitHub Actions como
scheduler (solo manual por ahora, sin cron).

## Arquitectura
- `agent.py` — loop del agente (query → lock → ejecutar → escribir resultado)
- `prompts/executor.md` — prompt parametrizado con variables `{{...}}`
- `config/areas.yaml` — misión/KPIs/constraints por área + `notion_page_id` y flag `active`
- `CONTEXT.md` — contexto del sistema inyectado como `{{CONTEXT_MD}}` en el prompt
- `linter.py` — Capa 1 de grooming: informe de higiene del backlog (tareas sin
  Context/Output, sin área, huérfanas, estancadas, fallidas). Sin IA. Solo lectura,
  salvo con `--dashboard`, que refresca la sección "Salud del Sistema" en Notion.
  Absorbió el antiguo `diagnostico.py` (identidad de la integración + desglose por estado).
- `groomer.py` — Capa 2 (F1): redacta Context/Output de las tareas 🔴 Alta que los
  tengan **vacíos** y los escribe marcados `[🤖 borrador IA – revisar]`. Nunca
  sobrescribe ni toca Type/Status/relaciones; si no puede redactar con fundamento
  devuelve NEEDS_INPUT. Soporta `--dry-run`.
- `kpis.py` — KPIs de **vida** (no de salud del sistema: eso es `linter.py`).
  Sin IA. Lee Weekly Self-Assessment [DB], Diario de Gratitud [DB] y la página
  "Sistema: Planificación Semanal"; escribe la sección gestionada
  "📈 KPIs Personales" en el dashboard. Lo invoca `linter.yml` con `--write`.

## Workflows (presupuesto Internal: máx 3 — al límite)
- `scheduler.yml` — executor (`agent.py`). Solo `workflow_dispatch`.
- `linter.yml` — higiene + dashboard (`linter.py`) **y KPIs (`kpis.py --write`)**.
  Cron lunes 05:00 UTC.
- `groomer.yml` — borradores (`groomer.py`), con input `dry_run`.

## Dónde va cada cosa

| Capa | Herramienta | Qué vive ahí | ¿Fuente de verdad? |
|---|---|---|---|
| Automatización | Este repo (`2nd-brain-agents`) | scripts, workflows, prompts, `areas.yaml` | ✅ |
| Doc del sistema | `CLAUDE.md` + `CONTEXT.md` | arquitectura, IDs, campos, quirks | ✅ |
| Ejecución | Notion → 📋 **LifeOS** | Goals, Projects, Tasks, Habits, KPIs, Weekly | ✅ |
| Conocimiento | Notion → 🧠 **2nd Brain** | principios, identidad, Mindset, aprendizajes | ✅ |
| Desarrollo | Claude Code (terminal) | editar este repo | ❌ efímero |
| Pensar / decidir | Claude Chat, Cowork | conversación | ❌ efímero |

**Regla:** si una decisión sobrevive al chat, se escribe en `CLAUDE.md` o en
Notion **en esa misma sesión**. Si no está aquí o en Notion, no existe.
Nada de documentos de handoff entre chats: caducan y desorientan.

## Stack
- **GitHub Actions** — ejecuta `agent.py` vía `workflow_dispatch`
- **Python** — `anthropic` (SDK oficial) + `requests` (Notion) + `pyyaml`
- **Notion API** — base de datos de tareas
- **Anthropic API** — modelo `claude-sonnet-4-6` con structured outputs (JSON garantizado)

## Secrets en GitHub Actions
- `NOTION_TOKEN` — API key de la integración "2nd Brain Agent" en Notion
- `ANTHROPIC_API_KEY` — API key de Anthropic (workspace: Javi's Individual Org)
- `NOTION_TASKS_DB_ID` — opcional; `agent.py` tiene el ID por defecto

## Notion — inventario de IDs

Raíz: **2nd AI Brain (Life OS)** `24c9982c-113c-8080-a885-f312d1d965e6`
(bajo el teamspace "Personal Projects"). Cuelgan tres hubs: `2NB Databases`
`3ae9982c-113c-8000-8d1e-fd9978ac918e`, `🧠 2nd Brain`
`3ae9982c-113c-81c7-8f50-c36d1411daa7`, `📋 LifeOS`
`3ae9982c-113c-81ca-85a9-d38d2714ab55`.

### Bases de datos

⚠️ El **REST ID** (el que usa la API) ≠ el **Collection ID** (el que usa el
conector MCP). Los scripts usan siempre el REST ID.

| DB | REST ID | Collection ID |
|---|---|---|
| Tasks | `067cbf54-b7e7-41b0-9e05-9291a44a31c1` | `e0d47d5f-f0fd-4024-8f6a-e3bfa1bd2d71` |
| Life Areas | `9b80e585-dde0-4102-983b-092f6252bffc` | `8b0b26ab-3f9e-4624-bfe8-cc81a011fede` |
| Goals (Long Term) | `4b9b63a4-8054-48bf-834d-981934f05bec` | `550b8100-01b0-4cb0-8a27-37c0a34b6750` |
| Projects | `d387d060-f9f3-416a-ab5c-359b60ce1ce0` | `c775f9a3-d4c2-4008-b1aa-4702228e2ad2` |
| Mindset | `c94bdd1a-863a-49ed-b167-b83de03816fb` | `4a90bb7a-e3f8-4f52-ba31-e89ac6cc88bb` |
| Habits | `5f2c0fcf-148b-4ba5-9495-31f494eefe07` | `30b76421-69d3-4fb7-bbb1-6831df084820` |
| Diario de Gratitud | `c726a373-ea4e-49bf-8b85-197ae0cddebd` | `683b9872-1613-48e7-96be-35cd68b7c747` |
| Weekly Self-Assessment | `4e203fe2-bba4-4bbb-9be4-be71eb669098` | `87afaa10-aa58-43f8-8078-bac412d0e9ab` |

### Páginas que el código escribe o lee

| Página | ID | Quién |
|---|---|---|
| Dashboard (Main KPIs) | `35f9982c-113c-8125-afeb-c842bef78dae` | `linter.py`, `kpis.py` |
| Sistema: Planificación Semanal | `2ed9982c-113c-809a-9186-eca7c1f79385` | `kpis.py` (lectura) |
| 🔧 Internal (2nB) — Life Area | `3329982c-113c-8004-9e1f-fe949345cab4` | `areas.yaml` |

### Campos vinculados al código
Centralizados en el diccionario `FIELDS` de `agent.py`. Si renombras un campo
en Notion, actualiza **solo** el valor correspondiente en `FIELDS`.

| Clave | Nombre en Notion | Tipo | Uso |
|---|---|---|---|
| `task` | `Task` | title | Título |
| `status` | `Status` | select | Filtro + lock + resultado |
| `type` | `Type` | select | Filtro: solo se ejecutan 🤖 Agent |
| `priority` | `Priority` | select | Ordenación (🔴 > 🟡 > 🟢, luego más antigua) |
| `context` | `Context` | text | Input NO confiable para el prompt |
| `output` | `Output (Expected)` | text | Output esperado |
| `result` | `Agent Result ` | text | Resultado (**tiene espacio al final**) |
| `area` | `Life Area (Link)` | relation | Mapea a `config/areas.yaml` vía `notion_page_id` |
| `attempts` | `Attempts` | number | Reintentos; a los 3 → Blocked |
| `last_attempt` | `Last Attempt` | date | Lock anti-duplicados |

### Valores de selects
- **Status:** Not Started, In Progress, Done, Blocked
- **Type:** 🤖 Agent, ⚙️ Semi, 👤 Manual
- **Priority:** 🔴 Alta, 🟡 Media, 🟢 Baja

## Flujo del agente (una invocación)
1. Query: Status=Not Started, Type=🤖 Agent, Attempts < 3 (o vacío)
2. Ordena por Priority y antigüedad; coge la top 1
3. Lock: Status=In Progress + Last Attempt=now
4. Resuelve el área desde `Life Area (Link)`; si no hay área o está inactiva → Blocked + nota
5. Renderiza `prompts/executor.md` (CONTEXT.md + config del área + campos de la tarea)
6. Llama a la API con structured outputs → JSON `{status, result, proposed_tasks}`
7. DONE → Status=Done; NEEDS_INPUT / BLOCKED → Status=Blocked. Resultado en "Agent Result "
8. Crea `proposed_tasks` (verifica por título que no existan; nunca crea Type=🤖)
9. En excepción: Attempts += 1, Status=Not Started; al 3er fallo → Blocked + error

## Quirks conocidos
- El campo `Agent Result ` tiene un **espacio al final** (así lo creó Notion)
- Collection IDs ≠ REST DB IDs
- Límite de un bloque rich_text: 2000 caracteres (se trunca con header incluido)
- **`kpis.py` duplica a mano los objetivos de `config/areas.yaml`**
  (`META_GRATITUD`, `META_CLAUDE`, `META_CHECKS`). Si cambias un KPI en
  `areas.yaml`, cámbialo también ahí. Deuda conocida y aceptada.
- `Tasks [DB]` tiene campos que el código **no** usa: `Link`,
  `Goals (Long Term) [DB]`, `Projects [DB]`. El campo `Section` ya no existe.
- Las vistas de Notion filtradas por relación son solo UI: la API no las ve.
- En `create_pages` las relaciones no se setean; hay que hacer un `update` aparte.

## Modelo de IA
`claude-sonnet-4-6` (el anterior `claude-sonnet-4-20250514` se retira el
15 de junio de 2026). Para reducir costes se puede cambiar a `claude-haiku-4-5`.
