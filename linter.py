"""
2nd Brain - Linter de Tareas (Capa 1, sin IA)
Lee la Tasks DB y reporta problemas de higiene: tareas mal cumplimentadas,
estancadas, sin área, huérfanas o fallidas. NO usa la API de Anthropic — solo
lee Notion y escupe un informe. Coste: 0 tokens de IA.

Con `--dashboard` además ESCRIBE una sección "Salud del Sistema" (computada,
idempotente) dentro del dashboard "Goals & KPIs" existente en Notion. Esa es la
única escritura del script y no toca las tareas: gestiona un único toggle propio.
"""

import os
import sys
from collections import Counter
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

# Dashboard unificado: la sección operativa se inyecta DENTRO de esta página
# (la misma "📊 Goals & KPIs Dashboard"), como un toggle gestionado e idempotente.
DASHBOARD_PAGE_ID = "35f9982c113c8125afebc842bef78dae"
SENTINEL          = "🔧 Salud del Sistema (2nd Brain)"   # marca del bloque gestionado

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
    "goal":     "Goals (Long Term) [DB]",
    "project":  "Projects [DB]",
    "attempts": "Attempts",
}

# ── Notion: lectura de tareas ───────────────────────────────────────────────────

def check_identity():
    """Confirma qué integración de Notion está conectada (heredado de diagnostico.py)."""
    r = requests.get("https://api.notion.com/v1/users/me", headers=NOTION_HEADERS)
    if not r.ok:
        print(f"❌ Notion auth error {r.status_code}: {r.text}")
    r.raise_for_status()
    print(f"🔌 Conectado a Notion como: {r.json().get('name', 'desconocido')}")

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
        "id":       task["id"],
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

# ── Áreas ───────────────────────────────────────────────────────────────────────

_norm = lambda i: i.replace("-", "")


def load_areas():
    with open(REPO_ROOT / "config" / "areas.yaml") as f:
        return yaml.safe_load(f)


def active_area_ids(areas):
    return {_norm(c["notion_page_id"]) for c in areas.values()
            if c.get("active") and c.get("notion_page_id")}


def area_name_map(areas):
    return {_norm(c["notion_page_id"]): c["name"] for c in areas.values()
            if c.get("notion_page_id")}

# ── Informe por stdout ──────────────────────────────────────────────────────────

def report(title, items):
    print(f"\n{'─' * 50}")
    print(f"{title}: {len(items)}")
    for t in items[:LIST_CAP]:
        print(f"   • {t['title']}")
    if len(items) > LIST_CAP:
        print(f"   … y {len(items) - LIST_CAP} más")

# ── Notion: bloques y escritura del dashboard (sección gestionada idempotente) ───

def _rt(content, bold=False):
    return {"type": "text", "text": {"content": content[:2000]},
            "annotations": {"bold": bold}}

def _h2(text):
    return {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [_rt(text)]}}

def _p(text, bold=False):
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [_rt(text, bold)]}}

def _bullet(text):
    return {"object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [_rt(text)]}}

def _callout(text, emoji):
    return {"object": "block", "type": "callout",
            "callout": {"rich_text": [_rt(text)], "icon": {"type": "emoji", "emoji": emoji}}}


def list_block_children(block_id):
    children, cursor = [], None
    while True:
        params = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        r = requests.get(f"https://api.notion.com/v1/blocks/{block_id}/children",
                         headers=NOTION_HEADERS, params=params)
        r.raise_for_status()
        data = r.json()
        children.extend(data.get("results", []))
        if not data.get("has_more"):
            return children
        cursor = data.get("next_cursor")


def append_children(block_id, blocks):
    r = requests.patch(f"https://api.notion.com/v1/blocks/{block_id}/children",
                       headers=NOTION_HEADERS, json={"children": blocks})
    if not r.ok:
        print(f"❌ Notion append error {r.status_code}: {r.text}")
    r.raise_for_status()
    return r.json()


def delete_block(block_id):
    r = requests.delete(f"https://api.notion.com/v1/blocks/{block_id}", headers=NOTION_HEADERS)
    r.raise_for_status()


def find_managed_toggle(page_id):
    """Localiza nuestro toggle gestionado por su marca SENTINEL (o None)."""
    for b in list_block_children(page_id):
        if b.get("type") == "toggle":
            txt = "".join(i["plain_text"] for i in b["toggle"].get("rich_text", []))
            if txt.startswith(SENTINEL):
                return b["id"]
    return None


def build_dashboard_blocks(stats):
    """Construye los bloques Notion de la sección 'Salud del Sistema'."""
    now = datetime.now()
    blocks = [_p(f"Actualizado automáticamente por linter.py · {now:%Y-%m-%d %H:%M}")]

    # 1) Semáforo KPIs Internal (criterios de areas.yaml → internal.kpis)
    blocks.append(_h2("🚦 Semáforo KPIs · Internal"))
    semaforo = [
        (stats["blocked"] < 5, f"Tareas Blocked < 5  →  {stats['blocked']}"),
        (stats["stale"] == 0,  f"0 tareas In Progress > 7d  →  {stats['stale']}"),
    ]
    for ok, label in semaforo:
        blocks.append(_callout(label, "🟢" if ok else "🔴"))
    # Frescura: un dashboard 'push' NO puede autodeclararse fresco — si el cron se
    # para, nada reescribe este bloque para ponerlo en rojo. Lo honesto es mostrar
    # la fecha real; si al mirarla supera los 7 días, el refresco automático falló.
    blocks.append(_callout(
        f"Última actualización: {now:%Y-%m-%d %H:%M}  ·  refresco automático cada lunes (cron). "
        f"Si esta fecha supera los 7 días, el cron ha fallado → revisar GitHub Actions.",
        "ℹ️"))

    # 2) Salud del backlog
    blocks.append(_h2("🩺 Salud del backlog"))
    blocks.append(_bullet(f"Tareas totales: {stats['total']}  ·  abiertas: {stats['open']}"))
    blocks.append(_bullet(
        f"Blocked: {stats['blocked']}  ·  estancadas >7d: {stats['stale']}  ·  "
        f"fallidas (Attempts≥3): {stats['failed']}"))
    blocks.append(_bullet(
        f"Sin Context: {stats['no_context']}  ·  sin Output: {stats['no_output']}  ·  "
        f"sin área: {stats['no_area']}"))
    score = stats["score"]
    score_emoji = "🟢" if score == 0 else ("🟡" if score < 20 else "🔴")
    blocks.append(_callout(
        f"Score de higiene: {score} señales" + (" — backlog limpio ✅" if score == 0 else ""),
        score_emoji))

    # 3) Trazabilidad
    blocks.append(_h2("🔗 Trazabilidad"))
    linked = stats["open"] - stats["orphan"]
    pct = round(100 * linked / stats["open"]) if stats["open"] else 0
    trz_emoji = "🟢" if pct >= 70 else ("🟡" if pct >= 40 else "🔴")
    blocks.append(_callout(
        f"{linked}/{stats['open']} tareas abiertas enlazadas a Goal/Project ({pct}%)  ·  "
        f"{stats['orphan']} huérfanas", trz_emoji))

    # 4) Distribución
    blocks.append(_h2("📊 Distribución"))
    blocks.append(_p("Por Status (todas):", bold=True))
    for k, v in stats["by_status"].items():
        blocks.append(_bullet(f"{k or '(sin status)'}: {v}"))
    blocks.append(_p("Por Type (abiertas):", bold=True))
    for k, v in stats["by_type"].items():
        blocks.append(_bullet(f"{k or '(sin type)'}: {v}"))
    blocks.append(_p("Por Área (abiertas):", bold=True))
    for k, v in stats["by_area"].items():
        blocks.append(_bullet(f"{k}: {v}"))

    return blocks


def write_dashboard(stats):
    """Escribe/refresca la sección gestionada dentro del dashboard existente.
    Idempotente: un único toggle marcado con SENTINEL cuyos hijos se reemplazan
    en cada ejecución. Nunca toca las vistas nativas de Goals/bienestar."""
    report_blocks = build_dashboard_blocks(stats)
    toggle_id = find_managed_toggle(DASHBOARD_PAGE_ID)
    if toggle_id:
        for child in list_block_children(toggle_id):
            delete_block(child["id"])
        append_children(toggle_id, report_blocks)
        print(f"♻️  Dashboard actualizado (toggle existente {toggle_id}).")
    else:
        toggle = {
            "object": "block", "type": "toggle",
            "toggle": {"rich_text": [_rt(SENTINEL)], "children": report_blocks},
        }
        append_children(DASHBOARD_PAGE_ID, [toggle])
        print("✨ Dashboard creado (nuevo toggle 'Salud del Sistema').")
    print(f"🔗 https://app.notion.com/p/{DASHBOARD_PAGE_ID}")

# ── Main ─────────────────────────────────────────────────────────────────────────

def main():
    write = "--dashboard" in sys.argv

    print("=" * 50)
    print(f"🧹 2nd Brain — Linter de Tareas — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)

    check_identity()
    tasks = [parse(t) for t in fetch_all_tasks()]
    areas = load_areas()
    active_areas = active_area_ids(areas)
    names = area_name_map(areas)
    open_tasks = [t for t in tasks if t["status"] in ("Not Started", "In Progress")]
    print(f"📋 Tareas totales: {len(tasks)}  |  abiertas (Not Started / In Progress): {len(open_tasks)}")

    by_status = Counter(t["status"] or "(sin estado)" for t in tasks)
    print("   " + "  ·  ".join(f"{s}: {n}" for s, n in sorted(by_status.items())))

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

    # ── Foco: tareas 🤖 Agent con Context/Output incompletos (worklist Capa 2) ──
    agent_gaps = [t for t in open_tasks if t["type"] == "🤖 Agent" and (not t["context"] or not t["output"])]
    print(f"\n{'═' * 50}")
    print(f"🤖 AGENT con Context/Output incompletos ({len(agent_gaps)})")
    print(f"{'═' * 50}")
    for t in agent_gaps:
        miss = " + ".join(m for m, ok in (("Context", t["context"]), ("Output", t["output"])) if not ok)
        print(f"   • [falta {miss}] {t['title']}")
        print(f"     {t['url']}")

    no_context   = [t for t in open_tasks if not t["context"]]
    no_output    = [t for t in open_tasks if not t["output"]]
    no_area      = [t for t in open_tasks if not t["area_ids"]]
    orphan       = [t for t in open_tasks if not t["goal_ids"] and not t["proj_ids"]]
    stale        = [t for t in tasks if t["status"] == "In Progress" and days_since(t["edited"]) > STALE_DAYS]
    failed       = [t for t in tasks if t["attempts"] >= 3]
    blocked      = [t for t in tasks if t["status"] == "Blocked"]
    agent_inactive = [
        t for t in open_tasks
        if t["type"] == "🤖 Agent" and t["area_ids"]
        and not any(_norm(i) in active_areas for i in t["area_ids"])
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
    print("ℹ️  Informe de solo lectura — no se ha modificado ninguna tarea.")
    print("=" * 50)

    # ── Dashboard (única escritura, opt-in con --dashboard) ────────────────────
    if not write:
        return

    def area_label(t):
        if not t["area_ids"]:
            return "(sin área)"
        return names.get(_norm(t["area_ids"][0]), "(otra área)")

    stats = {
        "total":      len(tasks),
        "open":       len(open_tasks),
        "blocked":    len(blocked),
        "stale":      len(stale),
        "failed":     len(failed),
        "no_context": len(no_context),
        "no_output":  len(no_output),
        "no_area":    len(no_area),
        "orphan":     len(orphan),
        "score":      total_issues,
        "by_status":  dict(Counter(t["status"] for t in tasks).most_common()),
        "by_type":    dict(Counter(t["type"] for t in open_tasks).most_common()),
        "by_area":    dict(Counter(area_label(t) for t in open_tasks).most_common()),
    }
    print(f"\n📊 Escribiendo dashboard en Notion…")
    write_dashboard(stats)


if __name__ == "__main__":
    main()
