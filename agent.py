"""
2nd Brain - Agente Ejecutor de Tareas
Corre cada hora. Lee Tasks de Notion, ejecuta las que puede, prepara las que no.
"""

import os
import json
import requests
from datetime import datetime

# ── Configuración ──────────────────────────────────────────────────────────────

NOTION_TOKEN     = os.environ["NOTION_TOKEN"]
ANTHROPIC_KEY    = os.environ["ANTHROPIC_API_KEY"]
TASKS_DB_ID      = os.environ["NOTION_TASKS_DB_ID"]

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

# ── Notion: leer tareas ────────────────────────────────────────────────────────

def get_pending_tasks():
    """Lee todas las tareas Not Started y que NO sean Manual."""
    url = f"https://api.notion.com/v1/databases/{TASKS_DB_ID}/query"
    payload = {
        "filter": {
            "and": [
                {"property": "Status",  "select": {"equals": "Not Started"}},
                {"property": "Done",    "checkbox": {"equals": False}},
                {"property": "Type",    "select": {"does_not_equal": "👤 Manual"}},
            ]
        },
        "sorts": [
            {"property": "Priority", "direction": "ascending"}
        ]
    }
    response = requests.post(url, headers=NOTION_HEADERS, json=payload)
    response.raise_for_status()
    return response.json().get("results", [])


def get_top_task(tasks):
    """Devuelve la tarea más prioritaria."""
    priority_order = {"🔴 Alta": 0, "🟡 Media": 1, "🟢 Baja": 2, None: 3}
    def sort_key(t):
        p = t["properties"].get("Priority", {}).get("select")
        return priority_order.get(p["name"] if p else None, 3)
    return sorted(tasks, key=sort_key)[0] if tasks else None


def extract_task_data(task):
    """Extrae los campos relevantes de una tarea de Notion."""
    props = task["properties"]
    def text(prop):
        items = props.get(prop, {}).get("rich_text", [])
        return "".join(i["plain_text"] for i in items) if items else ""
    def select(prop):
        s = props.get(prop, {}).get("select")
        return s["name"] if s else None
    def title():
        items = props.get("Task", {}).get("title", [])
        return "".join(i["plain_text"] for i in items) if items else "Sin título"

    return {
        "id":       task["id"],
        "title":    title(),
        "type":     select("Type"),
        "priority": select("Priority"),
        "context":  text("Context"),
        "output":   text("Output (Expected)"),
    }

# ── Claude: ejecutar tarea ─────────────────────────────────────────────────────

def execute_with_claude(task):
    """Llama a Claude para que ejecute o prepare la tarea."""
    tipo = task["type"]

    if tipo == "🤖 Agent":
        instruccion = (
            "Eres un agente autónomo del 2nd Brain. Tu misión es EJECUTAR la tarea completamente. "
            "Produce el output pedido de forma directa, lista para usar. Sin explicaciones extra."
        )
    else:  # ⚙️ Semi
        instruccion = (
            "Eres un agente autónomo del 2nd Brain. Tu misión es PREPARAR la tarea al máximo. "
            "Haz todo lo que puedas sin intervención humana y deja claro cuál es el único paso "
            "que queda para el humano. Sé concreto y breve."
        )

    prompt = f"""Tarea: {task['title']}
Contexto: {task['context'] or 'Sin contexto adicional'}
Output esperado: {task['output'] or 'No especificado'}

Ejecuta ahora."""

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1000,
            "system": instruccion,
            "messages": [{"role": "user", "content": prompt}],
        }
    )
    response.raise_for_status()
    return response.json()["content"][0]["text"]

# ── Notion: actualizar tarea ───────────────────────────────────────────────────

def update_task(task_id, result_text, task_type):
    """Escribe el resultado en Notion y actualiza el estado."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    emoji = "🤖" if task_type == "🤖 Agent" else "⚙️"
    action = "Ejecutado" if task_type == "🤖 Agent" else "Preparado"

    full_result = f"{emoji} {action} por agente — {timestamp}\n{'─'*40}\n{result_text}"

    url = f"https://api.notion.com/v1/pages/{task_id}"
    payload = {
        "properties": {
            "Status": {"select": {"name": "In Progress"}},
            "Agent Result ": {
                "rich_text": [{"type": "text", "text": {"content": full_result[:2000]}}]
            }
        }
    }
    response = requests.patch(url, headers=NOTION_HEADERS, json=payload)
    response.raise_for_status()
    print(f"✅ Tarea actualizada en Notion: {task_id}")

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*50}")
    print(f"🤖 Agente arrancando — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    tasks = get_pending_tasks()
    print(f"📋 Tareas pendientes encontradas: {len(tasks)}")

    if not tasks:
        print("✨ Nada pendiente. El sistema está al día.")
        return

    task_raw = get_top_task(tasks)
    task = extract_task_data(task_raw)

    print(f"\n🎯 Tarea seleccionada:")
    print(f"   Título:   {task['title']}")
    print(f"   Tipo:     {task['type']}")
    print(f"   Prioridad:{task['priority']}")

    print(f"\n⚙️  Ejecutando con Claude...")
    result = execute_with_claude(task)
    print(f"\n📝 Resultado:\n{result[:300]}...")

    update_task(task["id"], result, task["type"])
    print(f"\n✅ Ciclo completado.\n")


if __name__ == "__main__":
    main()
