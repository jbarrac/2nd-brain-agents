"""
2nd Brain - Linter de Tareas (Capa 1, sin IA)
Lee la Tasks DB y reporta problemas de higiene: tareas mal cumplimentadas,
estancadas, sin área, huérfanas o fallidas. NO modifica nada y NO usa la API
de Anthropic — solo lee Notion y escupe un informe. Coste: 0 tokens de IA.
"""

import os
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

# ── Configuración ──────────────────────────────────────────────────────────────

REPO_ROOT    = Path(__file__).parent
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
TASKS_DB_ID  = os.environ.get("NOTION_TASKS_DB_ID") or "067cbf54b7e741b09e059291a44a31c1"
STALE_DAYS   = 7        # umbral de "In Progress estancada"
LIST_CAP     = 10       # máx. de títulos listados por categoría

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

# Mismo mapa de campos que agent.py (si renombras en Notion, actualiza ambos).
FIELDS = {
    "task":     "Task",
    "status":   "Status",
    "type":     "Type",
    "priority": "Priority",
    "context":  "Context",
    "output":   "Output (Expected)",
    "area":     "Life Area (Link)",
    "goal":     "Goal",
    "project":  "Project",
    "attempts": "Attempts",
}

# ── Notion ─────────────────────────────────────────────────────────────────────

def fetch_all_tasks():
    """Pagina la Tasks DB completa (Notion devuelve máx 100 por página)."""
    tasks, cursor = [], None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        r = requests.post(
            f"https://api.notion.com/v1/databases/{TASKS_DB_ID}/query",
            headers=NOTION_HEADERS, json=payload,
        )
        if not r.ok:
            print(f"❌ Notion error {r.status_code}: {r.text}")
        r.raise_for_status()
        data = r.json()
        tasks.extend(data.get("results", []))
        if not data.get("has_more"):
            return tasks
        cursor = data.get("next_cursor")


def parse(task):
    props = task["properties"]

    def text(prop):
        return "".join(i["plain_text"] for i in props.get(prop, {}).get("rich_text", [])).strip()

    def select(prop):
        s = props.get(prop, {}).get("select")
        return s["name"] if s else None

    def relation(prop):
        return [r["id"] for r in props.get(prop, {}).get("relation", [])]

    title = "".join(i["plain_text"] for i in props.get(FIELDS["task"], {}).get("title", [])).strip()
    return {
        "title":    title or "(sin título)",
        "url":      task["url"],
        "status":   select(FIELDS["status"]),
        "type":     select(FIELDS["type"]),
        "priority": select(FIELDS["priority"]),
        "context":  text(FIELDS["context"]),
        "output":   text(FIELDS["output"]),
        "area_ids": relation(FIELDS["area"]),
        "goal_ids": relation(FIELDS["goal"]),
        "proj_ids": relation(FIELDS["project"]),
        "attempts": props.get(FIELDS["attempts"], {}).get("number") or 0,
        "edited":   task["last_edited_time"],
    }


def days_since(iso):
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - dt).days

# ── Áreas activas ──────────────────────────────────────────────────────────────

def load_active_area_ids():
    with open(REPO_ROOT / "config" / "areas.yaml") as f:
        areas = yaml.safe_load(f)
    norm = lambda i: i.replace("-", "")
    active = {norm(c["notion_page_id"]) for c in areas.values() if c.get("active") and c.get("notion_page_id")}
    return active

# ── Informe ────────────────────────────────────────────────────────────────────

def report(title, items):
    print(f"\n{'─' * 50}")
    print(f"{title}: {len(items)}")
    for t in items[:LIST_CAP]:
        print(f"   • {t['title']}")
    if len(items) > LIST_CAP:
        print(f"   … y {len(items) - LIST_CAP} más")


def main():
    print("=" * 50)
    print(f"🧹 2nd Brain — Linter de Tareas — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)

    tasks = [parse(t) for t in fetch_all_tasks()]
    active_areas = load_active_area_ids()
    open_tasks = [t for t in tasks if t["status"] in ("Not Started", "In Progress")]
    print(f"📋 Tareas totales: {len(tasks)}  |  abiertas (Not Started / In Progress): {len(open_tasks)}")

    # ── Foco: prioridad alta (Capa 2 empieza aquí) ────────────────────────────
    high = sorted([t for t in open_tasks if t["priority"] == "🔴 Alta"], key=lambda t: t["title"])
    print(f"\n{'═' * 50}")
    print(f"🔴 PRIORIDAD ALTA — revisión ({len(high)} abiertas)")
    print(f"{'═' * 50}")
    for t in high:
        gaps = []
        if not t["context"]:
            gaps.append("sin Context")
        if not t["output"]:
            gaps.append("sin Output")
        if not t["goal_ids"] and not t["proj_ids"]:
            gaps.append("huérfana")
        print(f"   {'✅ OK    ' if not gaps else '⚠️  ' + ', '.join(gaps)} — {t['title']}")

    no_context   = [t for t in open_tasks if not t["context"]]
    no_output    = [t for t in open_tasks if not t["output"]]
    no_area      = [t for t in open_tasks if not t["area_ids"]]
    orphan       = [t for t in open_tasks if not t["goal_ids"] and not t["proj_ids"]]
    stale        = [t for t in tasks if t["status"] == "In Progress" and days_since(t["edited"]) > STALE_DAYS]
    failed       = [t for t in tasks if t["attempts"] >= 3]
    agent_inactive = [
        t for t in open_tasks
        if t["type"] == "🤖 Agent" and t["area_ids"]
        and not any(i.replace("-", "") in active_areas for i in t["area_ids"])
    ]

    report("📝 Sin Context (mal cumplimentadas)", no_context)
    report("🎯 Sin Output esperado", no_output)
    report("🗺️  Sin área (Life Area Link)", no_area)
    report("🔗 Huérfanas (sin Goal ni Project)", orphan)
    report(f"⏳ In Progress estancadas (> {STALE_DAYS} días)", stale)
    report("💥 Fallidas (Attempts ≥ 3)", failed)
    report("🚫 Agent en área inactiva (el executor las bloqueará)", agent_inactive)

    total_issues = sum(len(x) for x in (no_context, no_output, no_area, orphan, stale, failed, agent_inactive))
    print(f"\n{'=' * 50}")
    print(f"{'✅ Backlog limpio.' if total_issues == 0 else f'⚠️  {total_issues} señales de higiene encontradas.'}")
    print("ℹ️  Informe de solo lectura — no se ha modificado nada en Notion.")
    print("=" * 50)


if __name__ == "__main__":
    main()
