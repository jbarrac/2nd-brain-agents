# 2nd Brain Agents

## Proyecto
Agentes autónomos que leen tareas de Notion, las ejecutan con Claude (Anthropic API), y escriben el resultado de vuelta en Notion. GitHub Actions como scheduler.

## Stack
- **GitHub Actions** — ejecuta `agent.py` (solo manual por ahora, sin cron)
- **Python** — scripts del agente
- **Notion API** — base de datos de tareas (gratis, sin límite relevante)
- **Anthropic API** — cerebro del agente (pago por uso, ~$0.01/ejecución con Sonnet)

## Secrets en GitHub Actions
- `NOTION_TOKEN` — API key de la integración "2nd Brain Agent" en Notion
- `ANTHROPIC_API_KEY` — API key de Anthropic (workspace: Javi's Individual Org)

## Notion — Tasks DB
- **DB ID:** `067cbf54b7e741b09e059291a44a31c1`
- **Collection ID:** `e0d47d5f-f0fd-4024-8f6a-e3bfa1bd2d71`

### Campos vinculados al código
Los nombres de campos de Notion están centralizados en el diccionario `FIELDS` al inicio de `agent.py`. Si renombras un campo en Notion, actualiza **solo** el valor correspondiente en `FIELDS`.

| Clave en FIELDS | Nombre actual en Notion | Tipo | Uso |
|---|---|---|---|
| `task` | `Task` | title | Título de la tarea |
| `status` | `Status` | select | Filtro (Not Started) + actualización (In Progress) |
| `type` | `Type` | select | Filtro (excluye Manual) + lógica Agent vs Semi |
| `priority` | `Priority` | select | Ordenación (Alta > Media > Baja) |
| `context` | `Context` | text | Se envía a Claude como contexto |
| `output` | `Output (Expected)` | text | Se envía a Claude como output esperado |
| `result` | `Agent Result ` | text | Donde se escribe el resultado (**tiene espacio al final**) |

### Valores esperados en selects
- **Status:** Not Started, In Progress, Done, Blocked
- **Type:** Agent, Semi, Manual (con emojis)
- **Priority:** Alta, Media, Baja (con emojis)

## Modelo de IA
Actualmente usa `claude-sonnet-4-20250514`. Para reducir costes se puede cambiar a Haiku.

## Flujo del agente
1. Lee tareas de Notion con Status=Not Started y Type!=Manual
2. Selecciona la más prioritaria
3. Envía título + contexto + output esperado a Claude API
4. Escribe resultado en "Agent Result " y cambia Status a "In Progress"
