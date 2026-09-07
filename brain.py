"""
2nd Brain — CLI unificado de modos (sin IA)

Un solo punto de entrada para los dos rituales del sistema:

    python brain.py week status     # foto de la semana + preflight de cierre
    python brain.py week fix        # checklist accionable de lo que falta
    python brain.py week close      # lecturas + dashboard + archivo
    python brain.py week open       # reset + renombrado de la Página Fija
    python brain.py dash status     # qué se pintaría, sin tocar Notion
    python brain.py dash update     # repinta las dos secciones del dashboard

No duplica lógica: orquesta `kpis.py` y `linter.py`, que siguen siendo
ejecutables por separado exactamente igual que antes.

Orden del ritual semanal (lunes):
    week status  →  week fix  →  week close  →  week open

`close` es idempotente (kpis.py ya se protege de cierres repetidos y
`archivar_semana` no duplica). `open` es el ÚNICO destructivo: se niega a
correr si la semana anterior no está archivada, salvo `--force`.
"""

import sys
from datetime import date, timedelta

try:
    import kpis
except KeyError:
    sys.exit("❌ Falta la variable de entorno NOTION_TOKEN.\n"
             "   Local:  export NOTION_TOKEN=secret_...\n"
             "   CI:     ya está como secret del repo.")

# Coaching Assessment [DB] (antes «Weekly Self-Assessment»): la retro semanal.
# El código NO la escribe nunca — solo comprueba si existe la entrada de la
# semana, porque una reflexión redactada por una máquina no es una reflexión.
RETRO_DB_ID = "4e203fe2bba44bbb9be4be71eb669098"

BLOQUE = "─" * 60


def _url(page_id):
    return f"https://app.notion.com/p/{page_id.replace('-', '')}"


def _lunes_anterior(today=None):
    """Lunes de la semana YA CERRADA, mirando desde cualquier día. Distinto de
    kpis.semana_referencia(), que solo mira atrás si hoy es lunes."""
    today = today or date.today()
    return today - timedelta(days=today.weekday()) - timedelta(days=7)


def _entrada_retro(lunes, domingo):
    """¿Hay entrada de retro para la semana? (None si la DB no es accesible.)

    Defensivo a propósito: esta DB la renombra y remodela Javi a mano, así que
    el chequeo no puede tumbar el resto del diagnóstico. Busca cualquier
    propiedad de tipo date en la fila, sin depender del nombre del campo.
    """
    try:
        filas = kpis.query_db(RETRO_DB_ID)
    except Exception:
        return None
    for row in filas:
        for prop in row["properties"].values():
            if prop.get("type") != "date":
                continue
            fecha = (prop.get("date") or {}).get("start")
            if not fecha:
                continue
            d = kpis.datetime.fromisoformat(fecha[:10]).date()
            if lunes <= d <= domingo:
                return True
    return False


def _tiene_checks(semana, dia):
    """¿Ese día tiene algún to_do? Un día sin nada NO aparece en semana['dias']
    (parse_semana_actual solo devuelve los heading_2 con hijos), así que
    'ausente' y 'vacío' son el mismo caso y hay que tratarlos igual."""
    v = semana["dias"].get(dia)
    return bool(v and (v["personal"][1] or v["facephi"][1]))


# ── Diagnóstico: una sola pasada, dos renderizados (status y fix) ──────────────

def diagnostico():
    lunes, domingo = kpis.semana_referencia()
    es_lunes = date.today().weekday() == 0

    grat = kpis.kpi_gratitud(lunes, domingo)
    semana = kpis.parse_semana_actual()

    huecos = []      # lo que falta y se puede rellenar → alimenta `week fix`
    avisos = []      # contexto, no accionable

    if grat["dias"] < kpis.META_GRATITUD:
        huecos.append({
            "que": f"Gratitud: {grat['dias']}/{kpis.META_GRATITUD} días (meta semanal)",
            "donde": "Diario de Gratitud [DB]",
            "url": _url(kpis.GRATITUD_DB_ID),
            "como": f"Añade {kpis.META_GRATITUD - grat['dias']} entrada(s) con Fecha "
                    f"dentro de {lunes:%d/%m}–{domingo:%d/%m}.",
        })

    dias_vacios = []
    if not semana:
        huecos.append({
            "que": "No se encontró la Página Fija de la semana",
            "donde": "Planificación Semanal (Current Week)",
            "url": _url(kpis.PLANNING_PAGE_ID),
            "como": "Comprueba que los días son heading_2 con toggle y los to_do van dentro.",
        })
    else:
        # Un día "vacío" es tanto el que no tiene to_do como el que ni siquiera
        # aparece en la página (parse_semana_actual solo devuelve los heading_2
        # con hijos, así que un día sin nada NO está en el dict).
        # Solo cuentan los días ya transcurridos: en mitad de semana, los días
        # futuros están vacíos por definición y avisar de ellos es ruido.
        transcurridos = kpis.DIAS if es_lunes else kpis.DIAS[:date.today().weekday() + 1]
        dias_vacios = [d for d in transcurridos if not _tiene_checks(semana, d)]
        if dias_vacios:
            huecos.append({
                "que": f"{len(dias_vacios)} día(s) sin ningún check: {', '.join(dias_vacios)}",
                "donde": semana["titulo"],
                "url": _url(kpis.PLANNING_PAGE_ID),
                "como": "Rellena o marca los días que sí hiciste antes de cerrar.",
            })
        if semana["claude_dias"] < kpis.META_CLAUDE:
            avisos.append(f"Proyectos personales: {semana['claude_dias']}/{kpis.META_CLAUDE} "
                          f"días (por debajo de la meta — dato, no error)")

    retro = _entrada_retro(lunes, domingo)
    if retro is False:
        huecos.append({
            "que": "Retro semanal sin escribir",
            "donde": "Coaching Assessment [DB]",
            "url": _url(RETRO_DB_ID),
            "como": "Escríbela tú: el sistema no la redacta. Es el único hueco que no se automatiza.",
        })
    elif retro is None:
        avisos.append("Retro semanal: no se pudo consultar la DB (¿sin acceso la integración?)")

    # Preflight de cierre: qué lecturas semanales entrarían hoy.
    idx = kpis.kpi_index()
    ya = kpis.readings_de_fecha(lunes)
    lecturas = []
    for clave in (kpis.CLAVE_GRATITUD, kpis.CLAVE_CHECKS, kpis.CLAVE_CLAUDE,
                  kpis.CLAVE_ENTRENAMIENTO, kpis.CLAVE_TAREAS):
        info = idx.get(clave)
        if not info:
            lecturas.append((clave, "❌ sin fila en KPIs [DB]"))
        elif info["id"].replace("-", "") in ya:
            lecturas.append((clave, "⏭️  ya registrada esta semana"))
        elif clave != kpis.CLAVE_GRATITUD and not es_lunes:
            lecturas.append((clave, "⏸️  solo se registra en lunes (hoy la página está a medias)"))
        else:
            lecturas.append((clave, "✅ se creará al cerrar"))

    archivada = kpis.existe_archivo(kpis._titulo_archivo(lunes))

    return {
        "lunes": lunes, "domingo": domingo, "es_lunes": es_lunes,
        "grat": grat, "semana": semana, "dias_vacios": dias_vacios,
        "huecos": huecos, "avisos": avisos,
        "lecturas": lecturas, "archivada": archivada,
        "cerrada": all(e.startswith("⏭️") for _, e in lecturas),
    }


def _cabecera(d, titulo):
    print(BLOQUE)
    print(f"{titulo} — semana {d['lunes']:%d/%m/%Y} – {d['domingo']:%d/%m/%Y}"
          f"  ({kpis._semana_iso(d['lunes'])})")
    print(BLOQUE)


def week_status():
    d = diagnostico()
    _cabecera(d, "📅 2nd Brain — Estado de la semana")

    g = d["grat"]
    marca = "✅" if g["dias"] >= kpis.META_GRATITUD else "⚠️ "
    print(f"{marca} Gratitud            {g['dias']}/{kpis.META_GRATITUD} días "
          f"({g['total_historico']} entradas históricas)")

    if d["semana"]:
        s = d["semana"]
        per_ok = sum(v["personal"][0] for v in s["dias"].values())
        per_tot = sum(v["personal"][1] for v in s["dias"].values())
        fac_ok = sum(v["facephi"][0] for v in s["dias"].values())
        fac_tot = sum(v["facephi"][1] for v in s["dias"].values())
        con_contenido = sum(1 for dia in kpis.DIAS if _tiene_checks(s, dia))
        marca = "✅" if con_contenido == 7 else "⚠️ "
        print(f"{marca} Página Fija         {con_contenido}/7 días con contenido — «{s['titulo']}»")
        print(f"   · personal {per_ok}/{per_tot}   · facephi {fac_ok}/{fac_tot}   "
              f"· proyectos personales {s['claude_dias']}/7   "
              f"· entrenamientos {s['entrenamiento_dias']}/7")
    else:
        print("❌ Página Fija         no encontrada")

    print(f"\n🗄️  Archivo de la semana: {'✅ ya archivada' if d['archivada'] else '⏳ pendiente (lo hace `week close`)'}")
    print("\n📊 Lecturas que entrarían al cerrar:")
    for clave, estado in d["lecturas"]:
        print(f"   {estado:<48} {clave}")

    if d["avisos"]:
        print("\nℹ️  Contexto:")
        for a in d["avisos"]:
            print(f"   · {a}")

    print()
    if d["cerrada"]:
        print("✅ Esta semana YA está cerrada. El siguiente paso es `week open`.")
    elif d["huecos"]:
        print(f"⚠️  {len(d['huecos'])} hueco(s) antes de cerrar. Ejecuta `brain.py week fix` para verlos.")
    else:
        print("✅ Sin huecos. Lista para `week close`.")
    return 0


def week_fix():
    d = diagnostico()
    _cabecera(d, "🩹 2nd Brain — Qué falta antes de cerrar")

    if not d["huecos"]:
        print("✅ Nada que corregir. Puedes cerrar con `brain.py week close`.\n")
        return 0

    print("Este modo NO escribe en Notion: te dice exactamente qué falta y dónde.\n"
          "Los datos de la semana los pones tú — inventarlos rompería la serie.\n")
    for i, h in enumerate(d["huecos"], 1):
        print(f"{i}. {h['que']}")
        print(f"   dónde  {h['donde']}")
        print(f"   cómo   {h['como']}")
        print(f"   link   {h['url']}\n")
    print("Cuando esté, vuelve a pasar `brain.py week status` y luego `week close`.")
    return 1        # exit≠0: hay trabajo pendiente (útil si algún día se encadena)


def _correr(modulo, *flags):
    """Ejecuta el main() de kpis/linter con los flags dados. Comparten el patrón
    de leer sys.argv directamente; se lo sustituimos y lo restauramos."""
    guardado = sys.argv
    sys.argv = [modulo.__file__, *flags]
    try:
        modulo.main()
    finally:
        sys.argv = guardado


def week_close():
    d = diagnostico()
    if d["huecos"]:
        print(f"⚠️  Cerrando con {len(d['huecos'])} hueco(s) sin resolver "
              f"(`week fix` los lista). El cierre continúa: registra lo que hay.\n")
    # El archivo va PRIMERO y siempre (aunque no sea lunes): es la red de
    # seguridad antes de tocar nada. `archivar_semana` no duplica.
    print("🗄️  Archivando la semana bajo # Histórico …")
    kpis.archivar_semana(d["lunes"])
    print()
    dash_update()
    print("\n✅ Semana cerrada. Revisa el dashboard y, cuando estés conforme, "
          "abre la nueva con `brain.py week open`.")
    return 0


def week_open(force=False):
    lunes_cerrado = _lunes_anterior()
    nombre = kpis._titulo_archivo(lunes_cerrado)
    if not kpis.existe_archivo(nombre) and not force:
        print(f"🛑 No existe el archivo «{nombre}».")
        print("   `week open` REEMPLAZA la Página Fija: sin archivo, esa semana se pierde.")
        print("   Cierra primero (`brain.py week close`) o fuerza con `--force` si sabes lo que haces.")
        return 1
    if force:
        print("⚠️  --force: se abre la semana sin verificar el archivo.")
    _correr(kpis, "--reset-semana")
    print("\n✅ Semana nueva abierta. Empieza a rellenar la Página Fija.")
    return 0


def dash_status():
    print("📊 Dashboard — qué se pintaría (sin escribir)\n")
    import linter
    _correr(linter)
    print()
    _correr(kpis)
    return 0


def dash_update():
    import linter
    print("🔧 Sección «Salud del Sistema» …")
    _correr(linter, "--dashboard")
    print("\n📈 Sección «KPIs Personales» …")
    _correr(kpis, "--write", "--no-archivo")
    return 0


MODOS = {
    ("week", "status"): week_status,
    ("week", "fix"):    week_fix,
    ("week", "close"):  week_close,
    ("week", "open"):   week_open,
    ("dash", "status"): dash_status,
    ("dash", "update"): dash_update,
}

USO = """2nd Brain — modos

  week status    foto de la semana + preflight de cierre (no escribe)
  week fix       checklist de lo que falta, con enlaces (no escribe)
  week close     lecturas + dashboard + archivo (idempotente)
  week open      reset + renombrado de la Página Fija  [--force]
  dash status    qué se pintaría, sin tocar Notion
  dash update    repinta Salud del Sistema + KPIs Personales

Ritual del lunes:  week status → week fix → week close → week open
"""


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    if len(args) != 2 or (args[0], args[1]) not in MODOS:
        print(USO)
        return 2
    fn = MODOS[(args[0], args[1])]
    return fn(force=force) if fn is week_open else fn()


if __name__ == "__main__":
    sys.exit(main() or 0)
