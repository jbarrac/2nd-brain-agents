"""
2nd Brain - Agente Ejecutor de Tareas
Ejecuta UNA tarea Type=🤖 Agent por invocación:
lee Tasks de Notion, la ejecuta con Claude (prompts/executor.md + config/areas.yaml)
y escribe el resultado de vuelta en Notion.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml
from anthropic import Anthropic

# ── Configuración ──────────────────────────────────────────────────────────────

REPO_ROOT     = Path(__file__).parent
NOTION_TOKEN  = os.environ["NOTION_TOKEN"]
# `or` (no `.get` default): el workflow pasa el secret aunque no exista, dejando
# la variable como string vacío en vez de ausente.
TASKS_DB_ID   = os.environ.get("NOTION_TASKS_DB_ID") or "067cbf54b7e741b09e059291a44a31c1"
MODEL         = "claude-sonnet-4-6"
MAX_ATTEMPTS  = 3
RESULT_LIMIT  = 2000   # límite de un bloque rich_text en Notion

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

# ── Mapa de campos Notion ─────────────────────────────────────────────────────
# Si renombras un campo en Notion, actualiza SOLO aquí.
FIELDS = {
    "task":         "Task",
    "status":       "Status",
    "type":         "Type",
    "priority":     "Priority",
    "context":      "Context",
    "output":       "Output (Expected)",
    "result":       "Agent Result ",   # Notion lo creó con espacio al final
    "area":         "Life Area (Link)",
    "attempts":     "Attempts",
    "last_attempt": "Last Attempt",
}

# Schema del JSON de respuesta del executor (structured outputs)
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["DONE", "NEEDS_INPUT", "BLOCKED"]},
        "result": {"type": "string"},
        "proposed_tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title":    {"type": "string"},
                    "type":     {"type": "string", "enum": ["👤 Manual", "⚙️ Semi"]},
                    "context":  {"type": "string"},
                    "priority": {"type": "string", "enum": ["🔴 Alta", "🟡 Media", "🟢 Baja"]},
                },
                "required": ["title", "type", "context", "priority"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["status", "result", "proposed_tasks"],
    "additionalProperties": False,
}

# ── Notion helpers ─────────────────────────────────────────────────────────────

def notion(method, path, payload=None):
    response = requests.request(
        method, f"https://api.notion.com/v1/{path}",
        headers=NOTION_HEADERS, json=payload,
    )
    if not response.ok:
        print(f"❌ Notion error {response.status_code}: {response.text}")
    response.raise_for_status()
    return response.json()


def get_pending_tasks():
    """Status=Not Started, Type=🤖 Agent, Attempts < 3 (o vacío)."""
    payload = {
        "filter": {
            "and": [
                {"property": FIELDS["status"], "select": {"equals": "Not Started"}},
                {"property": FIELDS["type"],   "select": {"equals": "🤖 Agent"}},
                {"or": [
                    {"property": FIELDS["attempts"], "number": {"less_than": MAX_ATTEMPTS}},
                    {"property": FIELDS["attempts"], "number": {"is_empty": True}},
                ]},
            ]
        }
    }
    return notion("POST", f"databases/{TASKS_DB_ID}/query", payload).get("results", [])


def pick_top_task(tasks):
    """Priority (🔴>🟡>🟢) y, a igualdad, la más antigua primero."""
    priority_order = {"🔴 Alta": 0, "🟡 Media": 1, "🟢 Baja": 2, None: 3}

    def sort_key(t):
        p = t["properties"].get(FIELDS["priority"], {}).get("select")
        return (priority_order.get(p["name"] if p else None, 3), t["created_time"])

    return sorted(tasks, key=sort_key)[0]


def extract_task_data(task):
    props = task["properties"]

    def text(prop):
        items = props.get(prop, {}).get("rich_text", [])
        return "".join(i["plain_text"] for i in items)

    def select(prop):
        s = props.get(prop, {}).get("select")
        return s["name"] if s else None

    title_items = props.get(FIELDS["task"], {}).get("title", [])
    area_ids = [r["id"] for r in props.get(FIELDS["area"], {}).get("relation", [])]

    return {
        "id":       task["id"],
        "title":    "".join(i["plain_text"] for i in title_items) or "Sin título",
        "type":     select(FIELDS["type"]),
        "priority": select(FIELDS["priority"]),
        "context":  text(FIELDS["context"]),
        "output":   text(FIELDS["output"]),
        "area_ids": area_ids,
        "attempts": props.get(FIELDS["attempts"], {}).get("number") or 0,
    }


def update_task(task_id, properties):
    notion("PATCH", f"pages/{task_id}", {"properties": properties})


def lock_task(task_id):
    """Anti-duplicados: In Progress + Last Attempt=now antes de ejecutar."""
    update_task(task_id, {
        FIELDS["status"]: {"select": {"name": "In Progress"}},
        FIELDS["last_attempt"]: {"date": {"start": datetime.now(timezone.utc).isoformat()}},
    })


def write_result(task_id, status_name, result_text, emoji="🤖"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    header = f"{emoji} Agente — {timestamp}\n{'─' * 40}\n"
    full_result = header + result_text[:RESULT_LIMIT - len(header)]
    update_task(task_id, {
        FIELDS["status"]: {"select": {"name": status_name}},
        FIELDS["result"]: {"rich_text": [{"type": "text", "text": {"content": full_result}}]},
    })


def task_exists(title):
    payload = {"filter": {"property": FIELDS["task"], "title": {"equals": title}}}
    return bool(notion("POST", f"databases/{TASKS_DB_ID}/query", payload).get("results"))


def create_proposed_tasks(proposals, area_ids):
    """Crea las proposed_tasks que no existan. Nunca crea tareas Type=🤖."""
    for p in proposals:
        if "🤖" in p.get("type", ""):
            print(f"⚠️  Propuesta con Type=🤖 descartada: {p.get('title')}")
            continue
        title = p.get("title", "").strip()
        if not title:
            continue
        if task_exists(title):
            print(f"↩️  Propuesta ya existe, no se duplica: {title}")
            continue
        properties = {
            FIELDS["task"]:     {"title": [{"type": "text", "text": {"content": title}}]},
            FIELDS["type"]:     {"select": {"name": p.get("type", "👤 Manual")}},
            FIELDS["status"]:   {"select": {"name": "Not Started"}},
            FIELDS["priority"]: {"select": {"name": p.get("priority", "🟢 Baja")}},
            FIELDS["context"]:  {"rich_text": [{"type": "text", "text": {"content": p.get("context", "")[:RESULT_LIMIT]}}]},
        }
        if area_ids:
            properties[FIELDS["area"]] = {"relation": [{"id": i} for i in area_ids]}
        notion("POST", "pages", {"parent": {"database_id": TASKS_DB_ID}, "properties": properties})
        print(f"➕ Tarea propuesta creada: {title}")

# ── Áreas y prompt ─────────────────────────────────────────────────────────────

def load_areas():
    with open(REPO_ROOT / "config" / "areas.yaml") as f:
        return yaml.safe_load(f)


def resolve_area(area_ids, areas):
    """Mapea la relación Life Area (Link) a su bloque de areas.yaml."""
    normalized = {i.replace("-", "") for i in area_ids}
    for key, cfg in areas.items():
        if cfg.get("notion_page_id", "").replace("-", "") in normalized:
            return key, cfg
    return None, None


def render_prompt(task, area_cfg):
    template = (REPO_ROOT / "prompts" / "executor.md").read_text()
    context_md = (REPO_ROOT / "CONTEXT.md").read_text()
    replacements = {
        "{{CONTEXT_MD}}":           context_md,
        "{{AREA_NAME}}":            area_cfg["name"],
        "{{AREA_MISSION}}":         area_cfg["mission"].strip(),
        "{{AREA_KPIS}}":            area_cfg["kpis"].strip(),
        "{{AREA_CONSTRAINTS}}":     area_cfg["constraints"].strip(),
        "{{TASK_TITLE}}":           task["title"],
        "{{TASK_TYPE}}":            task["type"] or "",
        "{{TASK_CONTEXT}}":         task["context"] or "Sin contexto adicional",
        "{{TASK_OUTPUT_EXPECTED}}": task["output"] or "No especificado",
    }
    for key, value in replacements.items():
        template = template.replace(key, value)
    return template

# ── Claude ─────────────────────────────────────────────────────────────────────

def execute_with_claude(prompt):
    client = Anthropic()  # ANTHROPIC_API_KEY del entorno
    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={"format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    )
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)

# ── Manejo de errores ──────────────────────────────────────────────────────────

def handle_failure(task, error):
    attempts = task["attempts"] + 1
    print(f"💥 Error en intento {attempts}/{MAX_ATTEMPTS}: {error}")
    if attempts >= MAX_ATTEMPTS:
        write_result(task["id"], "Blocked", f"Error tras {MAX_ATTEMPTS} intentos: {error}", emoji="🚫")
        update_task(task["id"], {FIELDS["attempts"]: {"number": attempts}})
    else:
        update_task(task["id"], {
            FIELDS["status"]:   {"select": {"name": "Not Started"}},
            FIELDS["attempts"]: {"number": attempts},
        })

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'=' * 50}")
    print(f"🤖 Agente arrancando — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'=' * 50}")

    tasks = get_pending_tasks()
    print(f"📋 Tareas 🤖 Agent pendientes: {len(tasks)}")
    if not tasks:
        print("✨ Nada pendiente. El sistema está al día.")
        return

    task = extract_task_data(pick_top_task(tasks))
    print(f"\n🎯 Tarea: {task['title']}  |  {task['type']}  |  {task['priority']}")

    lock_task(task["id"])

    areas = load_areas()
    area_key, area_cfg = resolve_area(task["area_ids"], areas)
    if area_cfg is None:
        write_result(task["id"], "Blocked",
                     "La tarea no tiene Life Area (Link) reconocida. Asigna un área para que el agente pueda ejecutarla.",
                     emoji="🚫")
        return
    if not area_cfg.get("active"):
        write_result(task["id"], "Blocked",
                     f"El área {area_cfg['name']} está inactiva (KPIs pendientes en T2–T7). Actívala en config/areas.yaml.",
                     emoji="🚫")
        return

    try:
        print(f"⚙️  Ejecutando con Claude ({MODEL}, área {area_cfg['name']})...")
        reply = execute_with_claude(render_prompt(task, area_cfg))
    except Exception as e:
        handle_failure(task, e)
        sys.exit(1)

    status_map = {"DONE": "Done", "NEEDS_INPUT": "Blocked", "BLOCKED": "Blocked"}
    emoji_map  = {"DONE": "✅", "NEEDS_INPUT": "❓", "BLOCKED": "🚫"}
    agent_status = reply["status"]
    print(f"\n📝 Status: {agent_status}\n{reply['result'][:300]}...")

    write_result(task["id"], status_map[agent_status], reply["result"], emoji=emoji_map[agent_status])
    create_proposed_tasks(reply.get("proposed_tasks", []), task["area_ids"])

    print(f"\n✅ Ciclo completado.\n")


if __name__ == "__main__":
    main()
