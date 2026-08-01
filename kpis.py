"""
2nd Brain — KPIs Personales (sin IA)

Computa los KPIs de VIDA (no de salud del sistema: eso es linter.py) y los
escribe como sección gestionada "📈 KPIs Personales" en el dashboard de Notion.

Fuentes:
  - Instagram   → campo "Instagram (h)" de Weekly Self-Assessment [DB] (manual)
  - Gratitud    → Diario de Gratitud [DB] (días con entrada en la semana)
  - Claude      → checkbox diario en la página de Planificación Semanal
  - Checks      → to_do de la Planificación Semanal, bloque personal vs Facephi

Solo lee; la única escritura es su propio bloque del dashboard. Coste: 0 tokens de IA.
"""

import os
import sys
from datetime import date, datetime, timedelta

import requests

# ── Configuración ──────────────────────────────────────────────────────────────

NOTION_TOKEN      = os.environ["NOTION_TOKEN"]
WEEKLY_DB_ID      = "4e203fe2bba44bbb9be4be71eb669098"   # Weekly Self-Assessment [DB]
GRATITUD_DB_ID    = "c726a373ea4e49bf8b85197ae0cddebd"   # Diario de Gratitud [DB]
PLANNING_PAGE_ID  = "2ed9982c113c809a9186eca7c1f79385"   # Sistema: Planificación Semanal
DASHBOARD_PAGE_ID = "35f9982c113c8125afebc842bef78dae"   # 📊 Dashboard (Main KPIs)
KPIS_DB_ID        = "3ae9982c113c80719d03e543f608f4c2"   # KPIs [DB] — definiciones
READINGS_DB_ID    = "c72ead033113467fad46bc8dc0de71d3"   # KPI Readings [DB] — serie temporal

SENTINEL   = "📈 KPIs Personales"          # título del bloque gestionado (editable por Javi)
FIRMA      = "por kpis.py"                 # marca en el contenido: ancla real, no la toca nadie

# Nombres exactos de las filas en KPIs [DB] que este script alimenta.
KPI_GRATITUD = "Días con entrada en Diario de Gratitud"
KPI_CLAUDE   = "Días trabajando en proyectos personales"
KPI_CHECKS_P = "Checks sistema semanal (personal)"
KPI_CHECKS_F = "Checks sistema semanal (Facephi)"
KPI_INSTA    = "Horas de Instagram"

# Objetivos (espejo de config/areas.yaml — si cambian allí, cambian aquí)
META_GRATITUD = 3   # días/semana con entrada
META_CLAUDE   = 4   # días/semana con trabajo en proyectos personales
META_CHECKS   = 5   # días/semana con el bloque personal completo

DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
# Un to_do cuyo texto contenga esto cuenta como "día usando Claude".
CLAUDE_MARKERS = ("proyecto personal", "claude")

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

# ── Notion: lectura ─────────────────────────────────────────────────────────────

def query_db(db_id):
    rows, cursor = [], None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        r = requests.post(f"https://api.notion.com/v1/databases/{db_id}/query",
                          headers=NOTION_HEADERS, json=payload)
        if not r.ok:
            print(f"❌ Notion error {r.status_code}: {r.text}")
        r.raise_for_status()
        data = r.json()
        rows.extend(data.get("results", []))
        if not data.get("has_more"):
            return rows
        cursor = data.get("next_cursor")


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


def plain(block, kind):
    return "".join(i["plain_text"] for i in block.get(kind, {}).get("rich_text", [])).strip()

# ── Semana de referencia ────────────────────────────────────────────────────────

def semana_referencia(today=None):
    """Lunes y domingo de la semana a reportar.

    El cron corre el lunes de madrugada: ese día lo interesante es la semana
    que acaba de cerrar, no la que empieza vacía. El resto de días, la actual.
    """
    today = today or date.today()
    ref = today - timedelta(days=3) if today.weekday() == 0 else today
    lunes = ref - timedelta(days=ref.weekday())
    return lunes, lunes + timedelta(days=6)

# ── KPI 1: Instagram ────────────────────────────────────────────────────────────

def kpi_instagram(lunes):
    """Última medición vs media de las 4 semanas previas."""
    puntos = []
    for row in query_db(WEEKLY_DB_ID):
        props = row["properties"]
        horas = props.get("Instagram (h)", {}).get("number")
        fecha = (props.get("Date", {}).get("date") or {}).get("start")
        if horas is not None and fecha:
            puntos.append((datetime.fromisoformat(fecha[:10]).date(), horas))
    puntos.sort()

    if not puntos:
        return {"estado": "sin_datos"}

    fecha_ult, horas_ult = puntos[-1]
    previos = [h for f, h in puntos[:-1]][-4:]
    media = sum(previos) / len(previos) if previos else None
    return {
        "estado": "ok",
        "fecha": fecha_ult,
        "horas": horas_ult,
        "media_previa": media,
        "delta": (horas_ult - media) if media is not None else None,
    }

# ── KPI 2: Gratitud ─────────────────────────────────────────────────────────────

def kpi_gratitud(lunes, domingo):
    """Días distintos con entrada dentro de la semana de referencia."""
    dias = set()
    total = 0
    for row in query_db(GRATITUD_DB_ID):
        fecha = (row["properties"].get("Fecha", {}).get("date") or {}).get("start")
        if not fecha:
            continue
        d = datetime.fromisoformat(fecha[:10]).date()
        total += 1
        if lunes <= d <= domingo:
            dias.add(d)
    return {"dias": len(dias), "total_historico": total}

# ── KPIs 3 y 4: plantilla semanal ───────────────────────────────────────────────

def parse_semana_actual():
    """Lee la sección de la semana en curso de la Planificación Semanal.

    La página lista las semanas como heading_3 ("### Semana ..."), la más
    reciente arriba. Dentro, cada día es un heading_4 y sus to_do se dividen en
    bloque personal / bloque Facephi por un divider.

    Devuelve por día: (personal_ok, personal_total, facephi_ok, facephi_total)
    y el nº de días marcados como trabajo en proyectos personales.
    """
    bloques = list_block_children(PLANNING_PAGE_ID)

    # Localiza el inicio de la semana más reciente.
    inicio = None
    for i, b in enumerate(bloques):
        if b["type"] == "heading_3" and plain(b, "heading_3").lower().startswith("semana"):
            inicio = i
            titulo = plain(b, "heading_3")
            break
    if inicio is None:
        return None

    dias, claude_dias = {}, 0
    dia_actual, seccion = None, "personal"

    for b in bloques[inicio + 1:]:
        t = b["type"]
        if t == "heading_3":            # empieza la semana anterior → paramos
            break
        if t == "heading_4":
            texto = plain(b, "heading_4")
            dia_actual = next((d for d in DIAS if texto.lower().startswith(d.lower())), None)
            seccion = "personal"
            if dia_actual:
                dias.setdefault(dia_actual, {"personal": [0, 0], "facephi": [0, 0]})
            continue
        if t == "divider":
            seccion = "facephi"
            continue
        if t == "to_do" and dia_actual:
            checked = b["to_do"].get("checked", False)
            texto = plain(b, "to_do").lower()
            dias[dia_actual][seccion][1] += 1
            if checked:
                dias[dia_actual][seccion][0] += 1
                if any(m in texto for m in CLAUDE_MARKERS):
                    claude_dias += 1

    return {"titulo": titulo, "dias": dias, "claude_dias": claude_dias}

# ── KPI Readings: escritura de la serie temporal ────────────────────────────────

def kpi_index():
    """{nombre: page_id} de las filas de KPIs [DB]."""
    idx = {}
    for row in query_db(KPIS_DB_ID):
        nombre = "".join(i["plain_text"] for i in
                         row["properties"].get("Nombre", {}).get("title", [])).strip()
        if nombre:
            idx[nombre] = row["id"]
    return idx


def readings_de_fecha(fecha):
    """ids de KPI que YA tienen lectura en esa fecha (para no duplicar)."""
    ya = set()
    for row in query_db(READINGS_DB_ID):
        props = row["properties"]
        f = (props.get("Fecha", {}).get("date") or {}).get("start")
        if f and f[:10] == fecha.isoformat():
            for rel in props.get("KPI", {}).get("relation", []):
                ya.add(rel["id"].replace("-", ""))
    return ya


def crear_reading(kpi_id, nombre, fecha, valor, nota=None):
    props = {
        "Registro": {"title": [{"text": {"content": f"{nombre} · {fecha.isoformat()}"[:2000]}}]},
        "Fecha":    {"date": {"start": fecha.isoformat()}},
        "KPI":      {"relation": [{"id": kpi_id}]},
        "Valor":    {"number": valor},
    }
    if nota:
        props["Notas"] = {"rich_text": [{"text": {"content": nota[:2000]}}]}
    r = requests.post("https://api.notion.com/v1/pages", headers=NOTION_HEADERS,
                      json={"parent": {"database_id": READINGS_DB_ID}, "properties": props})
    if not r.ok:
        print(f"❌ Error creando lectura '{nombre}': {r.status_code} {r.text}")
    r.raise_for_status()


def valores_de_la_semana(insta, grat, semana):
    """Qué se puede medir esta semana y qué no.

    Higiene de datos: si faltan días en la plantilla, los KPIs que salen de ella
    quedan incompletos. Preferimos un hueco en la serie a un dato falso, así que
    esos se omiten con motivo en vez de escribirse.
    """
    escribir, omitir = [], []

    # Gratitud: fuente independiente (su propia DB) → siempre medible.
    escribir.append((KPI_GRATITUD, float(grat["dias"]), None))

    # Instagram: manual; solo si Javi ha rellenado el campo.
    if insta["estado"] == "ok":
        escribir.append((KPI_INSTA, float(insta["horas"]), None))
    else:
        omitir.append((KPI_INSTA, "sin dato en Weekly Self-Assessment"))

    # Los 3 que salen de la plantilla semanal exigen la semana completa.
    if not semana:
        for k in (KPI_CHECKS_P, KPI_CHECKS_F, KPI_CLAUDE):
            omitir.append((k, "no se encontró la sección de la semana"))
        return escribir, omitir

    dias = semana["dias"]
    if len(dias) < 7:
        motivo = f"semana incompleta ({len(dias)}/7 días en la plantilla)"
        for k in (KPI_CHECKS_P, KPI_CHECKS_F, KPI_CLAUDE):
            omitir.append((k, motivo))
        return escribir, omitir

    completos = sum(1 for v in dias.values()
                    if v["personal"][1] and v["personal"][0] == v["personal"][1])
    fac_ok  = sum(v["facephi"][0] for v in dias.values())
    fac_tot = sum(v["facephi"][1] for v in dias.values())
    escribir.append((KPI_CHECKS_P, float(completos), "días con el bloque personal completo"))
    escribir.append((KPI_CHECKS_F, round(100 * fac_ok / fac_tot, 1) if fac_tot else 0.0, "% de checks"))
    escribir.append((KPI_CLAUDE, float(semana["claude_dias"]), None))
    return escribir, omitir


def sincronizar_readings(lunes, insta, grat, semana):
    """Escribe las lecturas de la semana. Idempotente: no duplica si ya existen."""
    idx = kpi_index()
    ya  = readings_de_fecha(lunes)
    escribir, omitir = valores_de_la_semana(insta, grat, semana)

    creadas, saltadas, sin_kpi = [], [], []
    for nombre, valor, nota in escribir:
        kpi_id = idx.get(nombre)
        if not kpi_id:
            sin_kpi.append(nombre)
            continue
        if kpi_id.replace("-", "") in ya:
            saltadas.append(nombre)
            continue
        crear_reading(kpi_id, nombre, lunes, valor, nota)
        creadas.append((nombre, valor))
    return {"creadas": creadas, "saltadas": saltadas, "omitidas": omitir, "sin_kpi": sin_kpi}


def series_por_kpi():
    """{kpi_id: [(fecha, valor), …] desc}. Una sola pasada por la DB."""
    series = {}
    for row in query_db(READINGS_DB_ID):
        props = row["properties"]
        f = (props.get("Fecha", {}).get("date") or {}).get("start")
        v = props.get("Valor", {}).get("number")
        if not f or v is None:
            continue
        for rel in props.get("KPI", {}).get("relation", []):
            series.setdefault(rel["id"].replace("-", ""), []).append(
                (datetime.fromisoformat(f[:10]).date(), v))
    for k in series:
        series[k].sort(reverse=True)
    return series

# ── Bloques Notion ──────────────────────────────────────────────────────────────

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


def bloques_serie(sync, idx):
    """Estado actual de la serie temporal de cada KPI gestionado.

    Reporta el ESTADO (última lectura y tendencia), no solo lo que hizo esta
    ejecución: si la lectura ya existía, los números deben verse igualmente.
    """
    b = [_h2("🗂️ Serie temporal · KPI Readings")]
    series = series_por_kpi()
    nuevas = {n for n, _ in sync["creadas"]}

    for nombre in (KPI_GRATITUD, KPI_CLAUDE, KPI_CHECKS_P, KPI_CHECKS_F, KPI_INSTA):
        kpi_id = idx.get(nombre)
        serie = series.get(kpi_id.replace("-", ""), []) if kpi_id else []
        marca = "  ✳️ nueva" if nombre in nuevas else ""
        if not serie:
            b.append(_bullet(f"{nombre}: sin lecturas todavía"))
            continue
        fecha, valor = serie[0]
        chispa = sparkline([v for _, v in reversed(serie[-8:])])
        if len(serie) > 1:
            d = valor - serie[1][1]
            flecha = "▲" if d > 0 else ("▼" if d < 0 else "=")
            b.append(_bullet(
                f"{nombre}: {chispa}  {valor:g} ({fecha:%d/%m})  ·  {flecha} {abs(d):g} vs "
                f"{serie[1][0]:%d/%m}  ·  {len(serie)} lecturas{marca}"))
        else:
            b.append(_bullet(f"{nombre}: {valor:g} ({fecha:%d/%m})  ·  primera lectura{marca}"))

    if sync["omitidas"]:
        b.append(_callout(
            "No medibles esta semana — se deja hueco en la serie en vez de un dato falso:\n"
            + "\n".join(f"• {n} — {motivo}" for n, motivo in sync["omitidas"]), "⚠️"))
    if sync["sin_kpi"]:
        b.append(_callout("Sin fila en KPIs [DB] (no se puede registrar): "
                          + ", ".join(sync["sin_kpi"]), "🔴"))
    return b


def build_blocks(lunes, domingo, insta, grat, semana, sync, idx):
    now = datetime.now()
    b = [_p(f"Actualizado automáticamente por kpis.py · {now:%Y-%m-%d %H:%M}  ·  "
            f"semana {lunes:%d/%m} – {domingo:%d/%m}")]

    # KPI 1 — Instagram
    b.append(_h2("📱 Uso de Instagram · Free Time"))
    if insta["estado"] == "sin_datos":
        b.append(_callout("Sin datos aún — rellena \"Instagram (h)\" en Weekly "
                          "Self-Assessment con las horas del Screen Time del iPhone.", "⏳"))
    else:
        d = insta["delta"]
        if d is None:
            b.append(_callout(f"{insta['horas']:.1f} h ({insta['fecha']:%d/%m}) — "
                              f"primera medición, aún sin base de comparación.", "⏳"))
        else:
            emoji = "🟢" if d < 0 else ("🟡" if d == 0 else "🔴")
            signo = "▼" if d < 0 else ("=" if d == 0 else "▲")
            b.append(_callout(
                f"{insta['horas']:.1f} h esta semana  ·  {signo} {abs(d):.1f} h vs "
                f"media previa ({insta['media_previa']:.1f} h)", emoji))

    # KPI 2 — Gratitud
    b.append(_h2("🙏 Diario de Gratitud · Mental"))
    n = grat["dias"]
    b.append(_callout(f"{n}/7 días con entrada esta semana (objetivo ≥ {META_GRATITUD})",
                      "🟢" if n >= META_GRATITUD else ("🟡" if n > 0 else "🔴")))
    b.append(_bullet(f"Histórico acumulado: {grat['total_historico']} entradas"))

    # KPIs 3 y 4 — plantilla semanal
    b.append(_h2("✅ Sistema Semanal · Internal"))
    if not semana:
        b.append(_callout("No se encontró ninguna sección \"Semana …\" en la página de "
                          "Planificación Semanal.", "🔴"))
        return b + bloques_serie(sync, idx)

    dias = semana["dias"]
    presentes = len(dias)
    per_ok  = sum(v["personal"][0] for v in dias.values())
    per_tot = sum(v["personal"][1] for v in dias.values())
    fac_ok  = sum(v["facephi"][0]  for v in dias.values())
    fac_tot = sum(v["facephi"][1]  for v in dias.values())
    dias_completos = sum(1 for v in dias.values()
                         if v["personal"][1] and v["personal"][0] == v["personal"][1])

    pct = lambda ok, tot: round(100 * ok / tot) if tot else 0
    b.append(_callout(
        f"Bloque personal: {per_ok}/{per_tot} checks ({pct(per_ok, per_tot)}%)  ·  "
        f"{dias_completos} días completos (objetivo ≥ {META_CHECKS})",
        "🟢" if dias_completos >= META_CHECKS else ("🟡" if dias_completos else "🔴")))
    b.append(_callout(
        f"Bloque Facephi: {fac_ok}/{fac_tot} checks ({pct(fac_ok, fac_tot)}%)",
        "🟢" if pct(fac_ok, fac_tot) >= 70 else ("🟡" if fac_ok else "🔴")))

    # KPI Claude
    c = semana["claude_dias"]
    b.append(_callout(f"{c}/7 días con trabajo en proyectos personales "
                      f"(objetivo ≥ {META_CLAUDE})",
                      "🟢" if c >= META_CLAUDE else ("🟡" if c else "🔴")))

    # Aviso de integridad: si faltan días, el porcentaje no es comparable.
    if presentes < 7:
        b.append(_callout(
            f"Solo {presentes}/7 días presentes en «{semana['titulo']}» — los días "
            f"borrados no se pueden contar. Para que la métrica sea fiable, conserva "
            f"la semana completa hasta el lunes.", "⚠️"))
    b.append(_bullet("Días presentes: " + (", ".join(d for d in DIAS if d in dias) or "ninguno")))
    return b + bloques_serie(sync, idx)

# ── Panel de tarjetas (lo primero que se ve al abrir la página) ─────────────────

FIRMA_TARJETAS = "Panel actualizado por kpis.py"

# (KPI, etiqueta corta, emoji, sufijo, objetivo) — objetivo None = "menos es mejor".
TARJETAS = [
    (KPI_GRATITUD, "Gratitud",         "🙏", "/7", META_GRATITUD),
    (KPI_CLAUDE,   "Proy. personales", "💻", "/7", META_CLAUDE),
    (KPI_CHECKS_P, "Checks personal",  "✅", "/7", META_CHECKS),
    (KPI_CHECKS_F, "Checks Facephi",   "💼", "%",  70),
    (KPI_INSTA,    "Instagram",        "📱", " h", None),
]


def sparkline(valores):
    """Serie como barras de texto. Funciona en plan free: no son imágenes."""
    if not valores:
        return ""
    barras = "▁▂▃▄▅▆▇█"
    lo, hi = min(valores), max(valores)
    if hi == lo:
        return barras[3] * len(valores)
    return "".join(barras[min(7, int((v - lo) / (hi - lo) * 7.999))] for v in valores)


def _tarjeta(etiqueta, emoji, texto, color):
    return {"object": "block", "type": "callout", "callout": {
        "rich_text": [_rt(texto)],
        "icon": {"type": "emoji", "emoji": emoji},
        "color": color,
    }}


def construir_tarjetas(series, idx):
    """Una tarjeta por KPI gestionado, en columnas."""
    columnas = []
    for nombre, etiqueta, emoji, sufijo, objetivo in TARJETAS:
        kpi_id = idx.get(nombre)
        serie = series.get(kpi_id.replace("-", ""), []) if kpi_id else []

        if not serie:
            texto = f"{etiqueta}\n—\nsin datos"
            color = "gray_background"
        else:
            fecha, valor = serie[0]
            # La serie viene desc; para el sparkline la queremos cronológica.
            cronologica = [v for _, v in reversed(serie[-8:])]
            chispa = sparkline(cronologica)

            if len(serie) > 1:
                d = valor - serie[1][1]
                flecha = "▲" if d > 0 else ("▼" if d < 0 else "=")
                delta = f"{flecha} {abs(d):g}"
            else:
                delta = "1ª lectura"

            if objetivo is None:                      # menos es mejor (Instagram)
                ok = len(serie) > 1 and valor < serie[1][1]
            else:
                ok = valor >= objetivo
            color = "green_background" if ok else "red_background"
            texto = (f"{etiqueta}\n{valor:g}{sufijo}\n{chispa}\n{delta} · {fecha:%d/%m}")

        columnas.append({"object": "block", "type": "column",
                         "column": {"children": [_tarjeta(etiqueta, emoji, texto, color)]}})

    return [
        {"object": "block", "type": "column_list", "column_list": {"children": columnas}},
        _p(f"{FIRMA_TARJETAS} · {datetime.now():%Y-%m-%d %H:%M}"),
    ]


def write_tarjetas(bloques):
    """Reemplaza el panel y lo deja arriba del todo. Idempotente.

    El panel gestionado son 2 bloques adyacentes: el column_list y el párrafo de
    firma que va justo detrás. La firma hace de ancla y de sello de frescura.
    """
    hijos = list_block_children(DASHBOARD_PAGE_ID)

    for i, b in enumerate(hijos):
        if b["type"] == "paragraph" and FIRMA_TARJETAS in plain(b, "paragraph"):
            requests.delete(f"https://api.notion.com/v1/blocks/{b['id']}",
                            headers=NOTION_HEADERS).raise_for_status()
            if i > 0 and hijos[i - 1]["type"] == "column_list":
                requests.delete(f"https://api.notion.com/v1/blocks/{hijos[i-1]['id']}",
                                headers=NOTION_HEADERS).raise_for_status()
            print("♻️  Panel anterior eliminado.")
            break

    ancla = list_block_children(DASHBOARD_PAGE_ID)[0]["id"]   # tras la cita de intro
    r = requests.patch(f"https://api.notion.com/v1/blocks/{DASHBOARD_PAGE_ID}/children",
                       headers=NOTION_HEADERS,
                       json={"children": bloques, "after": ancla})
    if not r.ok:
        print(f"❌ Error escribiendo el panel: {r.status_code} {r.text}")
    r.raise_for_status()
    print("✨ Panel de tarjetas publicado arriba del dashboard.")

# ── Escritura idempotente en el dashboard ───────────────────────────────────────

def find_managed_toggle():
    """Localiza el bloque gestionado en el dashboard.

    Ancla primaria: el título. Ancla secundaria: la FIRMA que el propio script
    escribe en su primer párrafo — sobrevive a que se renombre o se convierta el
    título en un enlace, que es justo lo que pasó el 31/07/2026.
    """
    for b in list_block_children(DASHBOARD_PAGE_ID):
        if b["type"] != "toggle":
            continue
        if SENTINEL in plain(b, "toggle"):
            return b["id"]
        if b.get("has_children"):
            for hijo in list_block_children(b["id"])[:3]:
                if hijo["type"] == "paragraph" and FIRMA in plain(hijo, "paragraph"):
                    return b["id"]
    return None


def write_section(blocks):
    toggle_id = find_managed_toggle()

    if toggle_id:
        for hijo in list_block_children(toggle_id):
            requests.delete(f"https://api.notion.com/v1/blocks/{hijo['id']}",
                            headers=NOTION_HEADERS).raise_for_status()
        r = requests.patch(f"https://api.notion.com/v1/blocks/{toggle_id}/children",
                           headers=NOTION_HEADERS, json={"children": blocks})
        accion = f"actualizado (toggle {toggle_id})"
    else:
        toggle = {"object": "block", "type": "toggle",
                  "toggle": {"rich_text": [_rt(SENTINEL)], "children": blocks}}
        r = requests.patch(f"https://api.notion.com/v1/blocks/{DASHBOARD_PAGE_ID}/children",
                           headers=NOTION_HEADERS, json={"children": [toggle]})
        accion = "creado (nuevo toggle)"
    if not r.ok:
        print(f"❌ Notion write error {r.status_code}: {r.text}")
    r.raise_for_status()
    print(f"♻️  Bloque '{SENTINEL}' {accion}.")

# ── Main ────────────────────────────────────────────────────────────────────────

def main():
    write = "--write" in sys.argv
    lunes, domingo = semana_referencia()

    print("=" * 55)
    print(f"📈 2nd Brain — KPIs Personales — semana {lunes:%d/%m/%Y} – {domingo:%d/%m/%Y}")
    print("=" * 55)

    insta  = kpi_instagram(lunes)
    grat   = kpi_gratitud(lunes, domingo)
    semana = parse_semana_actual()

    if insta["estado"] == "sin_datos":
        print("📱 Instagram: sin datos (rellena 'Instagram (h)' en Weekly Self-Assessment)")
    else:
        print(f"📱 Instagram: {insta['horas']:.1f} h  (media previa: "
              f"{insta['media_previa'] if insta['media_previa'] is None else round(insta['media_previa'],1)})")
    print(f"🙏 Gratitud: {grat['dias']}/7 días esta semana  ·  {grat['total_historico']} entradas históricas")

    if not semana:
        print("✅ Sistema semanal: ⚠️  no se encontró sección 'Semana …'")
    else:
        dias = semana["dias"]
        per_ok  = sum(v["personal"][0] for v in dias.values())
        per_tot = sum(v["personal"][1] for v in dias.values())
        fac_ok  = sum(v["facephi"][0]  for v in dias.values())
        fac_tot = sum(v["facephi"][1]  for v in dias.values())
        print(f"✅ «{semana['titulo']}» — {len(dias)}/7 días presentes")
        print(f"   personal: {per_ok}/{per_tot}  ·  facephi: {fac_ok}/{fac_tot}  ·  "
              f"claude: {semana['claude_dias']}/7")
        if len(dias) < 7:
            print(f"   ⚠️  faltan {7 - len(dias)} días (borrados) — métrica incompleta")

    if not write:
        print("\nℹ️  Modo lectura. Usa --write para publicar en el dashboard.")
        return

    print("\n🗂️  Sincronizando KPI Readings…")
    sync = sincronizar_readings(lunes, insta, grat, semana)
    for nombre, valor in sync["creadas"]:
        print(f"   ✅ lectura creada — {nombre}: {valor:g}")
    for nombre in sync["saltadas"]:
        print(f"   ⏭️  ya existía — {nombre}")
    for nombre, motivo in sync["omitidas"]:
        print(f"   ⚠️  omitida — {nombre} ({motivo})")
    for nombre in sync["sin_kpi"]:
        print(f"   ❌ sin fila en KPIs [DB] — {nombre}")

    print("\n📊 Escribiendo en el dashboard…")
    idx = kpi_index()                      # una sola vez: antes se escaneaba dos veces
    write_tarjetas(construir_tarjetas(series_por_kpi(), idx))
    write_section(build_blocks(lunes, domingo, insta, grat, semana, sync, idx))
    print(f"🔗 https://app.notion.com/p/{DASHBOARD_PAGE_ID}")


if __name__ == "__main__":
    main()
