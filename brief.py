"""
brief.py — «Foco de la semana» en la Página Fija

Sustituye a agent.py como lo que corre cada lunes. El problema que resuelve:
agent.py ejecutaba 1 tarea/semana, solo las Type=🤖 Agent, y dejaba el
resultado en el campo «Agent Result » de Notion, que Javi no abre. Lo que sí
abre cada día es la Página Fija de Planificación Semanal — así que el informe
va ahí.

Cada lunes elige 3 tareas del backlog, prepara el primer paso de cada una con
el modelo, y las pinta en una sección gestionada al principio de la página.

Tres propiedades que hay que mantener al tocar esto:

1. INVISIBLE PARA EL KPI. Las casillas del Foco NO deben contar en
   `checks_semanal`. No hace falta tocar el parseo: `kpis.parse_semana_actual()`
   solo baja a los `heading_2` cuyo texto empieza por un día de la semana, así
   que un bloque de primer nivel (este callout) es invisible para él. Si algún
   día esta sección se mete DENTRO de un día, el KPI se falsea.

2. IDEMPOTENTE POR SEMANA ISO. El callout lleva la semana en el título. Si ya
   existe el de la semana en curso, no se regenera (ni se llama al modelo).
   `--force` lo salta. Por eso correrlo dos veces deja UNA sección, no dos.

3. NO FILTRA CONTENIDO EN CI. El repo es público: en GitHub Actions solo se
   imprimen recuentos e IDs, nunca títulos ni texto de las tareas. El detalle
   completo solo se ve en local.

Uso:
    python brief.py                  # genera y escribe
    python brief.py --dry-run        # solo selección, sin modelo ni escritura
    python brief.py --dry-run --con-modelo   # preview completo, sin escribir
    python brief.py --force          # regenera aunque ya exista la de esta semana
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).parent


def _cargar_env():
    """Carga .env si existe (está en .gitignore).

    DEBE correr antes de `import kpis`, que lee NOTION_TOKEN del entorno al
    importarse y aborta si falta. Por eso brain.py importa `brief` ANTES que
    `kpis`: así este cargador corre primero y no hay que duplicarlo.
    """
    env = RAIZ / ".env"
    if not env.exists():
        return
    for linea in env.read_text().splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        os.environ.setdefault(clave.strip(), valor.strip().strip('"').strip("'"))


_cargar_env()

import requests                      # noqa: E402  (tras _cargar_env, a propósito)
import yaml                          # noqa: E402
import kpis                          # noqa: E402

# ── Configuración ──────────────────────────────────────────────────────────────

TASKS_DB_ID = os.environ.get("NOTION_TASKS_DB_ID") or "067cbf54b7e741b09e059291a44a31c1"
GOALS_DB_ID = "4b9b63a4805448bf834d981934f05bec"

MODEL           = "claude-sonnet-4-6"
N_TAREAS        = 3
MAX_PRIMER_PASO = 600
SENTINEL        = "🎯 Foco de la semana"

# El repo es público: en Actions no se imprime contenido de las tareas.
EN_CI = bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))


def _detalle_error(r):
    """Cómo se reporta un error de la API de Notion.

    En CI, SOLO el código. El cuerpo de un 400 de Notion cita el payload que
    se le mandó —y ese payload lleva los títulos de las tareas y el texto del
    Foco—, así que imprimirlo entero filtraría en unos logs públicos justo lo
    que la invariante 3 protege en el camino normal.
    """
    return str(r.status_code) if EN_CI else f"{r.status_code} {r.text}"

# Estados que nunca son candidatos. `Parked` (añadido el 11-nov-2026) es
# explícitamente «ahora no»: respetarlo es la mitad del valor del Foco.
ESTADOS_CANDIDATOS = ("Not Started", "In Progress")
PREFIJO_DESCARTE   = "[Eliminar]"

ORDEN_PRIORIDAD = {"🔴 Alta": 0, "🟡 Media": 1, "🟢 Baja": 2, None: 3}

FIELDS = {
    "titulo":   "Task",
    "status":   "Status",
    "type":     "Type",
    "priority": "Priority",
    "context":  "Context",
    "output":   "Output (Expected)",
    "area":     "Life Area (Link)",
    "goal":     "Goals (Long Term) [DB]",
}

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "porque":      {"type": "string"},
        "primer_paso": {"type": "string"},
    },
    "required": ["porque", "primer_paso"],
    "additionalProperties": False,
}

_norm = lambda i: (i or "").replace("-", "")

# ── Lectura de Notion ──────────────────────────────────────────────────────────

def _texto(props, campo):
    return "".join(i["plain_text"] for i in props.get(campo, {}).get("rich_text", [])).strip()


def _select(props, campo):
    s = props.get(campo, {}).get("select")
    return s["name"] if s else None


def _relacion(props, campo):
    return [r["id"] for r in props.get(campo, {}).get("relation", [])]


def parse_tarea(page):
    props = page["properties"]
    titulo = "".join(i["plain_text"] for i in props.get(FIELDS["titulo"], {}).get("title", [])).strip()
    return {
        "id":       page["id"],
        "url":      page["url"],
        "titulo":   titulo or "(sin título)",
        "status":   _select(props, FIELDS["status"]),
        "type":     _select(props, FIELDS["type"]),
        "priority": _select(props, FIELDS["priority"]),
        "context":  _texto(props, FIELDS["context"]),
        "output":   _texto(props, FIELDS["output"]),
        "areas":    _relacion(props, FIELDS["area"]),
        "goals":    _relacion(props, FIELDS["goal"]),
        "creada":   page["created_time"],
    }


def goals_en_curso():
    """{id_normalizado: título} de los Goals con Status = In Progress."""
    fuera = {}
    for page in kpis.query_db(GOALS_DB_ID):
        props = page["properties"]
        if _select(props, "Status") != "In Progress":
            continue
        titulo = "".join(i["plain_text"] for i in props.get("Goal", {}).get("title", []))
        fuera[_norm(page["id"])] = titulo.strip() or "(sin título)"
    return fuera


def area_interna():
    """notion_page_id del área Internal, leído de areas.yaml para no duplicarlo."""
    with open(RAIZ / "config" / "areas.yaml") as f:
        areas = yaml.safe_load(f)
    return _norm((areas.get("internal") or {}).get("notion_page_id"))

# ── Selección ──────────────────────────────────────────────────────────────────

def seleccionar(tareas, goals_ip, id_interna, n=N_TAREAS):
    """Elige hasta n tareas. Devuelve (elegidas, descartadas_por_cupo).

    Orden: primero las que cuelgan de un Goal en curso, luego por prioridad, y
    a igualdad la más antigua. Cupos: máx 1 por Goal y máx 1 del área Internal
    — para que el Foco no se convierta en una semana entera de mantenimiento
    del propio sistema, que es justo lo que el backlog tiende a acumular.
    """
    candidatas = [
        t for t in tareas
        if t["status"] in ESTADOS_CANDIDATOS
        and not t["titulo"].startswith(PREFIJO_DESCARTE)
    ]

    def clave(t):
        tiene_goal_ip = any(_norm(g) in goals_ip for g in t["goals"])
        return (0 if tiene_goal_ip else 1,
                ORDEN_PRIORIDAD.get(t["priority"], 3),
                t["creada"])

    elegidas, descartadas = [], []
    goals_usados, usada_interna = set(), False

    for t in sorted(candidatas, key=clave):
        if len(elegidas) == n:
            break
        suyos = {_norm(g) for g in t["goals"]} & set(goals_ip)
        if suyos & goals_usados:
            descartadas.append((t, "ya hay otra tarea de ese Goal"))
            continue
        es_interna = id_interna in {_norm(a) for a in t["areas"]}
        if es_interna and usada_interna:
            descartadas.append((t, "ya hay otra tarea del área Internal"))
            continue
        elegidas.append(t)
        goals_usados |= suyos
        usada_interna = usada_interna or es_interna

    return elegidas, descartadas

# ── Preparación con el modelo ──────────────────────────────────────────────────

def _config_area(areas, ids_area):
    norm = {_norm(a) for a in ids_area}
    for cfg in areas.values():
        if cfg.get("notion_page_id") and _norm(cfg["notion_page_id"]) in norm:
            return cfg
    return {}


def render_prompt(tarea, cfg_area, goal):
    plantilla = (RAIZ / "prompts" / "brief.md").read_text()
    sustituciones = {
        "{{CONTEXT_MD}}":           (RAIZ / "CONTEXT.md").read_text(),
        "{{AREA_NAME}}":            cfg_area.get("name", "(sin área)"),
        "{{AREA_MISSION}}":         (cfg_area.get("mission") or "(no definida)").strip(),
        "{{AREA_CONSTRAINTS}}":     (cfg_area.get("constraints") or "(ninguna)").strip(),
        "{{TASK_TITLE}}":           tarea["titulo"],
        "{{TASK_TYPE}}":            tarea["type"] or "(sin tipo)",
        "{{TASK_PRIORITY}}":        tarea["priority"] or "(sin prioridad)",
        "{{TASK_CONTEXT}}":         tarea["context"] or "(vacío)",
        "{{TASK_OUTPUT_EXPECTED}}": tarea["output"] or "(vacío)",
        "{{TASK_GOAL}}":            goal or "(ninguno)",
    }
    for k, v in sustituciones.items():
        plantilla = plantilla.replace(k, v)
    return plantilla


def preparar(tarea, cfg_area, goal):
    """Una llamada al modelo por tarea. Si falla, la tarea sigue apareciendo en
    el Foco sin primer paso: un informe incompleto es mejor que ninguno."""
    from anthropic import Anthropic
    try:
        respuesta = Anthropic().messages.create(
            model=MODEL,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            output_config={"format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}},
            messages=[{"role": "user", "content": render_prompt(tarea, cfg_area, goal)}],
        )
        datos = json.loads(next(b.text for b in respuesta.content if b.type == "text"))
        return (datos["porque"].strip(), datos["primer_paso"].strip()[:MAX_PRIMER_PASO])
    except Exception as e:
        print(f"   ⚠️  No se pudo preparar el primer paso ({type(e).__name__}).")
        return ("", "")

# ── Pintado en la Página Fija ──────────────────────────────────────────────────

def _titulo_seccion(semana_iso):
    return f"{SENTINEL} · {semana_iso}"


def buscar_seccion():
    """(id, texto) del callout gestionado, o (None, '')."""
    for b in kpis.list_block_children(kpis.PLANNING_PAGE_ID):
        if b["type"] != "callout":
            continue
        texto = kpis.plain(b, "callout")
        if SENTINEL in texto:
            return b["id"], texto
    return None, ""


def _to_do_tarea(tarea):
    """Casilla con el título enlazado a su página en Tasks [DB]."""
    return {"object": "block", "type": "to_do", "to_do": {
        "checked": False,
        "rich_text": [{"type": "text",
                       "text": {"content": tarea["titulo"][:1900], "link": {"url": tarea["url"]}}}],
    }}


def construir_bloques(preparadas, semana_iso):
    """El callout entero, con sus hijos. Se repinta completo en cada ejecución."""
    hijos = [kpis._p(f"Generado {datetime.now():%d/%m/%Y %H:%M} · se regenera cada lunes. "
                     f"Estas casillas no cuentan para el KPI de checks.")]
    for tarea, porque, primer_paso in preparadas:
        hijos.append(_to_do_tarea(tarea))
        if porque:
            hijos.append(kpis._bullet(f"Por qué ahora: {porque}"))
        if primer_paso:
            hijos.append(kpis._bullet(f"Primer paso: {primer_paso}"))
    if not preparadas:
        hijos.append(kpis._p("No hay tareas candidatas esta semana."))

    return {"object": "block", "type": "callout", "callout": {
        "rich_text": [kpis._rt(_titulo_seccion(semana_iso), bold=True)],
        "icon": {"type": "emoji", "emoji": "🎯"},
        "color": "blue_background",
        "children": hijos,
    }}


def escribir_seccion(bloque):
    """Borra la sección anterior (si la hay) y la repinta arriba del todo."""
    anterior, _ = buscar_seccion()
    if anterior:
        r = requests.delete(f"https://api.notion.com/v1/blocks/{anterior}",
                            headers=kpis.NOTION_HEADERS)
        r.raise_for_status()
        print("♻️  Sección anterior eliminada.")

    hijos = kpis.list_block_children(kpis.PLANNING_PAGE_ID)
    cuerpo = {"children": [bloque]}
    if hijos:
        # Justo debajo del título de la semana (heading_3), no al final.
        cuerpo["after"] = hijos[0]["id"]
    r = requests.patch(f"https://api.notion.com/v1/blocks/{kpis.PLANNING_PAGE_ID}/children",
                       headers=kpis.NOTION_HEADERS, json=cuerpo)
    if not r.ok:
        print(f"❌ Error escribiendo el Foco: {_detalle_error(r)}")
    r.raise_for_status()
    print(f"✨ «{SENTINEL}» publicado en la Página Fija.")


def marcar_en_curso(tareas):
    """Pasa las elegidas a In Progress. No toca ningún otro campo."""
    for t in tareas:
        if t["status"] == "In Progress":
            continue
        r = requests.patch(f"https://api.notion.com/v1/pages/{t['id']}",
                           headers=kpis.NOTION_HEADERS,
                           json={"properties": {FIELDS["status"]: {"select": {"name": "In Progress"}}}})
        if not r.ok:
            print(f"❌ Error marcando In Progress: {_detalle_error(r)}")
        r.raise_for_status()

# ── Entrada ────────────────────────────────────────────────────────────────────

def generar(dry_run=False, con_modelo=False, force=False):
    semana_iso = kpis._semana_iso(kpis._lunes_actual())
    print(f"🎯 Foco de la semana — {semana_iso}"
          f"{'  [DRY-RUN: no se escribe nada]' if dry_run else ''}")

    _, texto_actual = buscar_seccion()
    if semana_iso in texto_actual and not force and not dry_run:
        print(f"⏭️  Ya existe el Foco de {semana_iso} — no se regenera "
              f"(no se llama al modelo). Usa --force para rehacerlo.")
        return 0

    tareas = [parse_tarea(p) for p in kpis.query_db(TASKS_DB_ID)]
    goals_ip = goals_en_curso()
    with open(RAIZ / "config" / "areas.yaml") as f:
        areas = yaml.safe_load(f)

    elegidas, descartadas = seleccionar(tareas, goals_ip, area_interna())
    print(f"📋 {len(tareas)} tareas · {len(goals_ip)} Goals en curso · "
          f"{len(elegidas)} elegida(s), {len(descartadas)} descartada(s) por cupo")

    if not elegidas:
        print("✨ No hay candidatas. No se toca la página.")
        return 0

    # En CI no se imprime contenido: el repo es público y los logs también.
    # Sí los IDs: no revelan nada por sí solos y son lo único que permite
    # auditar desde fuera QUÉ eligió el Foco sin volcar los títulos al log.
    if EN_CI:
        print("   elegidas: " + ", ".join(t["id"] for t in elegidas))
    if not EN_CI:
        for i, t in enumerate(elegidas, 1):
            goal = next((goals_ip[_norm(g)] for g in t["goals"] if _norm(g) in goals_ip), None)
            print(f"\n  {i}. {t['titulo']}")
            print(f"     {t['priority'] or 'sin prioridad'} · {t['status']} · "
                  f"Goal en curso: {goal or '—'}")
        for t, motivo in descartadas[:5]:
            print(f"\n  ✗ {t['titulo']}\n     descartada: {motivo}")

    if dry_run and not con_modelo:
        print("\n🔍 Dry-run de selección. Añade --con-modelo para ver también "
              "el primer paso preparado.")
        return 0

    preparadas = []
    for t in elegidas:
        goal = next((goals_ip[_norm(g)] for g in t["goals"] if _norm(g) in goals_ip), None)
        porque, primer_paso = preparar(t, _config_area(areas, t["areas"]), goal)
        preparadas.append((t, porque, primer_paso))
        if not EN_CI:
            print(f"\n  ▸ {t['titulo']}")
            print(f"    porque      {porque or '—'}")
            print(f"    primer paso {primer_paso or '—'}")

    if dry_run:
        print("\n🔍 Dry-run: nada escrito en Notion.")
        return 0

    escribir_seccion(construir_bloques(preparadas, semana_iso))
    marcar_en_curso(elegidas)
    print(f"✅ {len(elegidas)} tarea(s) en In Progress.")
    print(f"🔗 https://app.notion.com/p/{kpis.PLANNING_PAGE_ID}")
    return 0


def main():
    return generar(dry_run="--dry-run" in sys.argv,
                   con_modelo="--con-modelo" in sys.argv,
                   force="--force" in sys.argv)


if __name__ == "__main__":
    sys.exit(main() or 0)
