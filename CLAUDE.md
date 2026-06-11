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
- `diagnostico.py` — verificación de conectividad con Notion (no modifica nada)

## Stack
- **GitHub Actions** — ejecuta `agent.py` vía `workflow_dispatch`
- **Python** — `anthropic` (SDK oficial) + `requests` (Notion) + `pyyaml`
- **Notion API** — base de datos de tareas
- **Anthropic API** — modelo `claude-sonnet-4-6` con structured outputs (JSON garantizado)

## Secrets en GitHub Actions
- `NOTION_TOKEN` — API key de la integración "2nd Brain Agent" en Notion
- `ANTHROPIC_API_KEY` — API key de Anthropic (workspace: Javi's Individual Org)
- `NOTION_TASKS_DB_ID` — opcional; `agent.py` tiene el ID por defecto

## Notion — Tasks DB
- **DB ID (REST):** `067cbf54b7e741b09e059291a44a31c1`
- **Collection ID:** `e0d47d5f-f0fd-4024-8f6a-e3bfa1bd2d71` (≠ REST ID)

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

## Modelo de IA
`claude-sonnet-4-6` (el anterior `claude-sonnet-4-20250514` se retira el
15 de junio de 2026). Para reducir costes se puede cambiar a `claude-haiku-4-5`.
