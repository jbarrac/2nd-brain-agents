"""Verificación offline de brief.py — no toca Notion ni gasta API.

    python3 tests/test_brief.py

Cubre dos cosas:

1. Las reglas de selección del Foco (cupos, exclusiones, orden).
2. LA INVARIANTE IMPORTANTE: que las casillas del «Foco de la semana» NO
   cuentan en el KPI `checks_semanal`. No se sostiene por un filtro explícito
   sino por la forma del parser: `kpis.parse_semana_actual()` solo baja a los
   `heading_2` cuyo texto empieza por un día de la semana. Si alguien mueve el
   Foco DENTRO de un día, o cambia el parser, el KPI se falsea en silencio y
   este test es lo único que lo caza.

NOTION_TOKEN es un dummy y `list_block_children` va monkeypatcheado: nada sale
a la red.
"""
import os
import sys
import types
from pathlib import Path

os.environ.setdefault("NOTION_TOKEN", "dummy-para-el-test")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# El test no hace red ni lee YAML: si las libs no están en este python, basta
# con un stub para que los imports de brief/kpis no revienten.
for _mod in ("requests", "yaml"):
    try:
        __import__(_mod)
    except ModuleNotFoundError:
        sys.modules[_mod] = types.ModuleType(_mod)

import brief      # noqa: E402
import kpis       # noqa: E402

AREA_INTERNA = "3329982c113c80049e1ffe949345cab4"
AREA_OTRA    = "3309982c113c80a68468cf4f48d0a9c1"
GOAL_IP      = "3309982c-113c-81b9-87be-f82d93eec225"
GOAL_IP2     = "3309982c-113c-81b9-87be-000000000002"

fallos = []


def check(nombre, cond):
    print(f"  {'✅' if cond else '❌'} {nombre}")
    if not cond:
        fallos.append(nombre)


def t(titulo, status="Not Started", prio="🟡 Media", areas=(), goals=(), creada="2026-01-01"):
    return {"id": titulo, "url": f"https://n/{titulo}", "titulo": titulo, "status": status,
            "type": "👤 Manual", "priority": prio, "context": "", "output": "",
            "areas": list(areas), "goals": list(goals), "creada": creada}


# ── 1. Reglas de selección ────────────────────────────────────────────────────
print("\n1. Selección")

# Claves normalizadas (sin guiones), igual que las devuelve brief.goals_en_curso().
goals_ip = {brief._norm(GOAL_IP): "Goal en curso",
            brief._norm(GOAL_IP2): "Otro goal en curso"}

tareas = [
    t("parked",       status="Parked",  prio="🔴 Alta"),
    t("done",         status="Done",    prio="🔴 Alta"),
    t("blocked",      status="Blocked", prio="🔴 Alta"),
    t("[Eliminar] x", prio="🔴 Alta"),
    t("con-goal-baja", prio="🟢 Baja", goals=[GOAL_IP]),
    t("mismo-goal",    prio="🔴 Alta", goals=[GOAL_IP]),
    t("otro-goal",     prio="🟢 Baja", goals=[GOAL_IP2]),
    t("alta-sin-goal", prio="🔴 Alta"),
    t("media-antigua", prio="🟡 Media", creada="2025-01-01"),
    t("media-nueva",   prio="🟡 Media", creada="2026-06-01"),
]

elegidas, descartadas = brief.seleccionar(tareas, goals_ip, AREA_INTERNA, n=3)
titulos = [e["titulo"] for e in elegidas]
print(f"     elegidas: {titulos}")

check("excluye Parked / Done / Blocked",
      not ({"parked", "done", "blocked"} & set(titulos)))
check("excluye los títulos [Eliminar]", "[Eliminar] x" not in titulos)
check("prefiere Goal en curso: 'otro-goal' (🟢 Baja) entra antes que 'alta-sin-goal' (🔴 Alta)",
      titulos.index("otro-goal") < titulos.index("alta-sin-goal"))
check("dentro del mismo Goal gana la de más prioridad",
      "mismo-goal" in titulos and "con-goal-baja" not in titulos)
check("descarta por cupo de Goal con su motivo",
      any(x["titulo"] == "con-goal-baja" and "Goal" in m for x, m in descartadas))
check("devuelve exactamente 3", len(elegidas) == 3)

solo_internas = [t("interna-1", prio="🔴 Alta", areas=[AREA_INTERNA]),
                 t("interna-2", prio="🔴 Alta", areas=[AREA_INTERNA]),
                 t("externa",   prio="🟢 Baja", areas=[AREA_OTRA])]
el2, _ = brief.seleccionar(solo_internas, {}, AREA_INTERNA, n=3)
check("máximo 1 tarea del área Internal",
      sum(1 for x in el2 if AREA_INTERNA in x["areas"]) == 1)
check("si hay menos candidatas que n, devuelve las que haya", len(el2) == 2)

el3, _ = brief.seleccionar([t("media-nueva", prio="🟡 Media", creada="2026-06-01"),
                            t("media-antigua", prio="🟡 Media", creada="2025-01-01"),
                            t("alta", prio="🔴 Alta")], {}, AREA_INTERNA, n=2)
check("ordena Alta antes que Media, y a igualdad la más antigua",
      [x["titulo"] for x in el3] == ["alta", "media-antigua"])


# ── 2. El Foco NO contamina checks_semanal ────────────────────────────────────
print("\n2. KPI checks_semanal")


def todo(texto, checked):
    return {"id": texto, "type": "to_do",
            "to_do": {"checked": checked, "rich_text": [{"plain_text": texto}]}}


FOCO = {"id": "foco", "type": "callout", "has_children": True,
        "callout": {"rich_text": [{"plain_text": "🎯 Foco de la semana · W46-2026"}]}}

CABECERA = {"id": "h3", "type": "heading_3",
            "heading_3": {"rich_text": [{"plain_text": "Semana 10NOV2026 · W46-2026"}]}}


def dia(nombre):
    return {"id": nombre, "type": "heading_2", "has_children": True,
            "heading_2": {"rich_text": [{"plain_text": f"{nombre} 10"}]}}


HIJOS = {
    # 3 casillas SIN marcar: si el parser las viera, el total subiría de 3 a 6.
    "foco":   [todo("tarea del foco 1", False), todo("tarea del foco 2", False),
               todo("tarea del foco 3", False)],
    "Lunes":  [todo("check personal", True), {"id": "div", "type": "divider"},
               todo("check facephi", True)],
    "Martes": [todo("otro personal", True)],
}


def medir(con_foco):
    pagina = [CABECERA] + ([FOCO] if con_foco else []) + [dia("Lunes"), dia("Martes")]
    kpis.list_block_children = (
        lambda bid: pagina if bid == kpis.PLANNING_PAGE_ID else HIJOS.get(bid, []))
    s = kpis.parse_semana_actual()
    total = sum(v["personal"][1] + v["facephi"][1] for v in s["dias"].values())
    hechos = sum(v["personal"][0] + v["facephi"][0] for v in s["dias"].values())
    return hechos, total, len(s["dias"])


sin_foco, con_foco = medir(False), medir(True)
print(f"     sin Foco: {sin_foco}   con Foco: {con_foco}   (hechos, total, días)")
check("checks_semanal da EXACTAMENTE lo mismo con y sin la sección", sin_foco == con_foco)
check("el parser no cuenta las 3 casillas del Foco", con_foco[1] == 3)
check("sigue viendo los días reales", con_foco[2] == 2)

print("\n" + ("❌ FALLOS: " + ", ".join(fallos) if fallos else "✅ Todo correcto"))
sys.exit(1 if fallos else 0)
