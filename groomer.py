"""
2nd Brain - Groomer de Tareas (Capa 2, F1: redactor de borradores)

Redacta Context/Output de las tareas 🔴 Alta que los tengan VACÍOS y los escribe
marcados como borrador IA para que Javi los revise.

Principio: solo escribe en campos vacíos → es aditivo y reversible, nunca destruye.
NUNCA sobrescribe contenido existente, ni toca Type, Status, Priority o relaciones.
Si no puede redactar con fundamento, devuelve NEEDS_INPUT y pregunta en vez de inventar.

Uso:  python groomer.py [--dry-run]
"""

import json
import os
import sys
from datetime import datetime

import requests
from anthropic import Anthropic

from linter import (FIELDS, NOTION_HEADERS, REPO_ROOT, _norm, check_identity,
                    fetch_all_tasks, load_areas, parse)

# ── Configuración ──────────────────────────────────────────────────────────────

MODEL       = "claude-sonnet-4-6"
MAX_TASKS   = int(os.environ.get("GROOMER_MAX_TASKS") or 5)   # tope de coste por ejecución
MARKER      = "[🤖 borrador IA – revisar] "
FIELD_LIMIT = 1800    # margen bajo el límite de 2000 de un rich_text de Notion

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "status":   {"type": "string", "enum": ["DONE", "NEEDS_INPUT"]},
        "context":  {"type": "string"},
        "output":   {"type": "string"},
        "question": {"type": "string"},
    },
    "required": ["status", "context", "output", "question"],
    "additionalProperties": False,
}

# ── Selección de tareas ────────────────────────────────────────────────────────

def select_targets(tasks):
    """Tareas abiertas, 🔴 Alta, con Context u Output vacíos. Tope MAX_TASKS."""
    targets = [
        t for t in tasks
        if t["status"] in ("Not Started", "In Progress")
        and t["priority"] == "🔴 Alta"
        and (not t["context"] or not t["output"])
    ]
    return sorted(targets, key=lambda t: t["title"])[:MAX_TASKS]


def resolve_area(area_ids, areas):
    normalized = {_norm(i) for i in area_ids}
    for cfg in areas.values():
        if cfg.get("notion_page_id") and _norm(cfg["notion_page_id"]) in normalized:
            return cfg
    return None

# ── Prompt ─────────────────────────────────────────────────────────────────────

def render_prompt(task, area_cfg, missing):
    template = (REPO_ROOT / "prompts" / "groomer.md").read_text()
    context_md = (REPO_ROOT / "CONTEXT.md").read_text()
    area = area_cfg or {}
    replacements = {
        "{{CONTEXT_MD}}":       context_md,
        "{{AREA_NAME}}":        area.get("name", "(sin área asignada)"),
        "{{AREA_MISSION}}":     (area.get("mission") or "(no definida)").strip(),
        "{{AREA_CONSTRAINTS}}": (area.get("constraints") or "(ninguna)").strip(),
        "{{TASK_TITLE}}":       task["title"],
        "{{TASK_TYPE}}":        task["type"] or "(sin tipo)",
        "{{TASK_PRIORITY}}":    task["priority"] or "(sin prioridad)",
        "{{TASK_CONTEXT}}":     task["context"] or "(vacío)",
        "{{TASK_OUTPUT}}":      task["output"] or "(vacío)",
        "{{MISSING_FIELDS}}":   ", ".join(missing),
    }
    for key, value in replacements.items():
        template = template.replace(key, value)
    return template


def draft(prompt):
    client = Anthropic()   # ANTHROPIC_API_KEY del entorno
    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={"format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    )
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)

# ── Escritura en Notion ────────────────────────────────────────────────────────

def build_updates(task, reply):
    """Solo campos que estaban VACÍOS. Doble guarda contra sobrescribir."""
    updates = {}
    if not task["context"] and reply["context"].strip():
        updates[FIELDS["context"]] = MARKER + reply["context"].strip()[:FIELD_LIMIT]
    if not task["output"] and reply["output"].strip():
        updates[FIELDS["output"]] = MARKER + reply["output"].strip()[:FIELD_LIMIT]
    return updates


def write_fields(page_id, updates):
    props = {
        name: {"rich_text": [{"type": "text", "text": {"content": value}}]}
        for name, value in updates.items()
    }
    r = requests.patch(f"https://api.notion.com/v1/pages/{page_id}",
                       headers=NOTION_HEADERS, json={"properties": props})
    if not r.ok:
        print(f"❌ Notion update error {r.status_code}: {r.text}")
    r.raise_for_status()

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    dry = "--dry-run" in sys.argv

    print("=" * 60)
    print(f"🧑‍🌾 2nd Brain — Groomer de Tareas — {datetime.now():%Y-%m-%d %H:%M}")
    print(f"{'🔍 DRY-RUN: no se escribirá nada' if dry else '✍️  Escribirá borradores en Notion'}")
    print("=" * 60)

    check_identity()
    tasks = [parse(t) for t in fetch_all_tasks()]
    areas = load_areas()
    targets = select_targets(tasks)

    print(f"🎯 Tareas 🔴 Alta con huecos a preparar: {len(targets)} (tope {MAX_TASKS})\n")
    if not targets:
        print("✨ Nada que preparar. Las urgentes están cumplimentadas.")
        return

    written, questions, skipped = 0, [], 0

    for task in targets:
        missing = [f for f, ok in (("Context", task["context"]), ("Output (Expected)", task["output"])) if not ok]
        area_cfg = resolve_area(task["area_ids"], areas)
        print(f"── {task['title']}  [falta {' + '.join(missing)}]")

        try:
            reply = draft(render_prompt(task, area_cfg, missing))
        except Exception as e:
            print(f"   💥 Error redactando: {e}\n")
            skipped += 1
            continue

        if reply["status"] == "NEEDS_INPUT":
            question = reply["question"].strip() or "(sin pregunta)"
            questions.append((task["title"], question))
            print(f"   ❓ NEEDS_INPUT: {question}\n")
            continue

        updates = build_updates(task, reply)
        if not updates:
            print("   ⏭️  Sin cambios aplicables (campos ya rellenos).\n")
            skipped += 1
            continue

        for name, value in updates.items():
            print(f"   📝 {name}: {value[:160]}{'…' if len(value) > 160 else ''}")

        if dry:
            print("   🔍 (dry-run, no escrito)\n")
        else:
            write_fields(task["id"], updates)
            written += 1
            print("   ✅ Escrito en Notion\n")

    print("=" * 60)
    print(f"✅ Tareas escritas: {written}  ·  ❓ Necesitan tu input: {len(questions)}  ·  ⏭️  Omitidas: {skipped}")
    if questions:
        print("\n❓ Preguntas para Javi:")
        for title, question in questions:
            print(f"   • {title}\n     → {question}")
    if dry:
        print("\nℹ️  Dry-run: no se ha modificado nada. Relanza sin --dry-run para aplicar.")
    print("=" * 60)


if __name__ == "__main__":
    main()
