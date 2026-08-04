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
PLANNING_PAGE_ID  = "3b19982c113c809ea424c4aa600eeb37"   # Planificación Semanal (Current Week)
DASHBOARD_PAGE_ID = "35f9982c113c8125afebc842bef78dae"   # 📊 Dashboard (Main KPIs)
KPIS_DB_ID        = "3ae9982c113c80719d03e543f608f4c2"   # KPIs [DB] — definiciones
READINGS_DB_ID    = "c72ead033113467fad46bc8dc0de71d3"   # KPI Readings [DB] — serie temporal
LAYOUT_DB_ID      = "58ac5bb7580849b69d1f7319559ce1ad"   # Dashboard Layout [DB] — qué se pinta y cómo

SENTINEL   = "📈 KPIs Personales"          # título del bloque gestionado (editable por Javi)
FIRMA      = "por kpis.py"                 # marca en el contenido: ancla real, no la toca nadie

# Ancla = columna `Clave` de KPIs [DB], no el nombre. El nombre es de Javi y lo
# retoca; la Clave es el contrato con este script y no se renombra nunca.
CLAVE_GRATITUD = "gratitud_dias"
CLAVE_CLAUDE   = "proyectos_personales"
CLAVE_CHECKS   = "checks_semanal"    # Javi fusionó personal + Facephi en un KPI
CLAVE_INSTA    = "instagram_horas"

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
    """Lee la página fija de la semana en curso.

    A diferencia del diseño anterior (una página histórica que crecía cada
    semana y Javi podaba a mano, con el riesgo de perder días antes de que
    corriera el cron), esta página es SIEMPRE la misma: el esqueleto de los
    7 días está presente desde el lunes, y kpis.py la resetea el lunes
    siguiente tras extraer el KPI (ver resetear_semana()). Por eso ya no hace
    falta buscar "la sección más reciente" ni avisar de días borrados.

    Cada día es un heading_2 con toggle=true ("## Lunes... {toggle=true}"),
    y sus to_do viven ANIDADOS dentro (hijos del heading, no hermanos) — hay
    que bajar un nivel más que en el diseño anterior. El divider `---` sigue
    separando bloque personal / bloque Facephi dentro de cada día.
    """
    bloques = list_block_children(PLANNING_PAGE_ID)
    titulo = next((plain(b, "heading_3") for b in bloques if b["type"] == "heading_3"),
                  "Semana actual")

    dias, claude_dias, todo_ids = {}, 0, []

    for b in bloques:
        if b["type"] != "heading_2" or not b.get("has_children"):
            continue
        texto = plain(b, "heading_2")
        dia = next((d for d in DIAS if texto.lower().startswith(d.lower())), None)
        if not dia:
            continue

        dias[dia] = {"personal": [0, 0], "facephi": [0, 0]}
        seccion = "personal"
        for hijo in list_block_children(b["id"]):
            if hijo["type"] == "divider":
                seccion = "facephi"
                continue
            if hijo["type"] == "to_do":
                checked = hijo["to_do"].get("checked", False)
                texto_item = plain(hijo, "to_do").lower()
                dias[dia][seccion][1] += 1
                todo_ids.append(hijo["id"])
                if checked:
                    dias[dia][seccion][0] += 1
                    if any(m in texto_item for m in CLAUDE_MARKERS):
                        claude_dias += 1

    if not dias:
        return None
    return {"titulo": titulo, "dias": dias, "claude_dias": claude_dias, "todo_ids": todo_ids}


def resetear_semana(semana):
    """Desmarca todos los checks de la página de la semana, lista para la
    semana siguiente. Solo se llama el lunes y SOLO después de haber
    confirmado que el dato ya quedó guardado en KPI Readings — nunca borra
    antes de guardar. No toca estructura ni texto, solo checked → False."""
    fallos = 0
    for todo_id in semana["todo_ids"]:
        r = requests.patch(f"https://api.notion.com/v1/blocks/{todo_id}",
                           headers=NOTION_HEADERS, json={"to_do": {"checked": False}})
        if not r.ok:
            fallos += 1
            print(f"❌ Error desmarcando {todo_id}: {r.status_code} {r.text}")
    print(f"🧹 Semana reseteada — {len(semana['todo_ids']) - fallos}/{len(semana['todo_ids'])} "
          f"checks desmarcados.")

# ── KPI Readings: escritura de la serie temporal ────────────────────────────────

def kpi_index():
    """{clave: {'id', 'nombre'}} de las filas de KPIs [DB] que tienen Clave.

    Solo entran las filas con `Clave` rellena: es la señal explícita de que el
    dashboard gestiona ese KPI. Sin Clave, el script lo ignora.
    """
    idx = {}
    for row in query_db(KPIS_DB_ID):
        props = row["properties"]
        clave = "".join(i["plain_text"] for i in
                        props.get("Clave", {}).get("rich_text", [])).strip()
        nombre = "".join(i["plain_text"] for i in
                         props.get("Nombre", {}).get("title", [])).strip()
        if clave:
            idx[clave] = {"id": row["id"], "nombre": nombre}
    return idx


def layout_rows(seccion="KPIs Personales"):
    """Filas de Dashboard Layout [DB]: qué KPI se pinta, cómo y en qué orden.

    Decoupled a propósito: esta DB no sabe nada de Clave (eso es el ancla de
    ESCRITURA de sincronizar_readings, sin relación con esto). Aquí solo
    importa la relación KPI → página, para poder mostrar cualquier fila de
    KPIs [DB] con lecturas, tenga Clave o no (p. ej. un KPI manual como
    Rentabilidad Mensual podría añadirse aquí como 'Valor fijo' sin que
    kpis.py sepa calcularlo).
    """
    filas = []
    for row in query_db(LAYOUT_DB_ID):
        props = row["properties"]
        if not props.get("Activo", {}).get("checkbox"):
            continue
        if (props.get("Sección", {}).get("select") or {}).get("name") != seccion:
            continue
        kpi_rel = props.get("KPI", {}).get("relation", [])
        if not kpi_rel:
            continue
        etiqueta = "".join(i["plain_text"] for i in
                           props.get("Etiqueta", {}).get("title", [])).strip()
        icono = "".join(i["plain_text"] for i in
                        props.get("Icono", {}).get("rich_text", [])).strip()
        sufijo = "".join(i["plain_text"] for i in
                         props.get("Sufijo", {}).get("rich_text", [])).strip()
        filas.append({
            "kpi_id":        kpi_rel[0]["id"].replace("-", ""),
            "etiqueta":      etiqueta,
            "icono":         icono or "📊",
            "sufijo":        sufijo,
            "tipo":          (props.get("Tipo", {}).get("select") or {}).get("name", "Tarjeta"),
            "orden":         props.get("Orden", {}).get("number") or 0,
            "menor_es_mejor": bool(props.get("Menor es mejor", {}).get("checkbox")),
            "meta":          props.get("Meta", {}).get("number"),
        })
    filas.sort(key=lambda f: f["orden"])
    return filas


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


def valores_de_la_semana(insta, grat, semana, es_lunes):
    """Qué se puede medir esta semana y qué no.

    Los 2 KPIs que salen de la plantilla semanal (checks, proyectos personales)
    solo se registran el LUNES: es el único día en que la página fija refleja
    una semana ya cerrada. Cualquier otro día, la página está a medias (los
    días futuros existen pero vacíos) — escribirlo sería un dato falso, no
    incompleto. Preferimos un hueco en la serie.
    """
    escribir, omitir = [], []

    # Gratitud: fuente independiente (su propia DB) → siempre medible.
    escribir.append((CLAVE_GRATITUD, float(grat["dias"]), None))

    # Instagram: manual; solo si Javi ha rellenado el campo.
    if insta["estado"] == "ok":
        escribir.append((CLAVE_INSTA, float(insta["horas"]), None))
    else:
        omitir.append((CLAVE_INSTA, "sin dato en Weekly Self-Assessment"))

    if not semana:
        for k in (CLAVE_CHECKS, CLAVE_CLAUDE):
            omitir.append((k, "no se encontró la página de la semana"))
        return escribir, omitir

    if not es_lunes:
        for k in (CLAVE_CHECKS, CLAVE_CLAUDE):
            omitir.append((k, "solo se registra el lunes, al cerrar la semana"))
        return escribir, omitir

    # KPI fusionado: % sobre TODOS los checks de la semana (personal + Facephi).
    dias = semana["dias"]
    ok  = sum(v["personal"][0] + v["facephi"][0] for v in dias.values())
    tot = sum(v["personal"][1] + v["facephi"][1] for v in dias.values())
    escribir.append((CLAVE_CHECKS, round(100 * ok / tot, 1) if tot else 0.0,
                     f"{ok}/{tot} checks (personal + Facephi)"))
    escribir.append((CLAVE_CLAUDE, float(semana["claude_dias"]), None))
    return escribir, omitir


def sincronizar_readings(lunes, insta, grat, semana, es_lunes):
    """Escribe las lecturas de la semana. Idempotente: no duplica si ya existen."""
    idx = kpi_index()
    ya  = readings_de_fecha(lunes)
    escribir, omitir = valores_de_la_semana(insta, grat, semana, es_lunes)

    creadas, saltadas, sin_kpi = [], [], []
    for clave, valor, nota in escribir:
        kpi = idx.get(clave)
        if not kpi:
            sin_kpi.append(clave)
            continue
        if kpi["id"].replace("-", "") in ya:
            saltadas.append((clave, kpi["nombre"]))
            continue
        crear_reading(kpi["id"], kpi["nombre"], lunes, valor, nota)
        creadas.append((clave, valor))
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


def bloques_serie(sync, series):
    """Estado actual de la serie temporal de cada KPI gestionado.

    Reporta el ESTADO (última lectura y tendencia), no solo lo que hizo esta
    ejecución: si la lectura ya existía, los números deben verse igualmente.
    Itera Dashboard Layout [DB], no un tuple hardcodeado: cualquier fila
    Activo aparece aquí, en su orden.
    """
    b = [_h2("🗂️ Serie temporal · KPI Readings")]

    # sincronizar_readings() trabaja por Clave (ancla de escritura); aquí solo
    # se usa kpi_index() para traducir ese resultado a kpi_id y dar nombres
    # legibles en los avisos — no para decidir qué se pinta (eso es Layout).
    idx = kpi_index()
    nuevas_ids = {idx[c]["id"].replace("-", "") for c, _ in sync["creadas"] if c in idx}

    filas = layout_rows()
    if not filas:
        b.append(_bullet("Sin filas activas en Dashboard Layout [DB]."))
    for fila in filas:
        nombre = fila["etiqueta"]
        serie = series.get(fila["kpi_id"], [])
        marca = "  ✳️ nueva" if fila["kpi_id"] in nuevas_ids else ""
        if not serie:
            b.append(_bullet(f"{nombre}: sin lecturas todavía"))
            continue
        fecha, valor = serie[0]
        n_hist = 16 if fila["tipo"] == "Gráfica completa" else 8
        chispa = sparkline([v for _, v in reversed(serie[-n_hist:])])
        if len(serie) > 1:
            d = valor - serie[1][1]
            flecha = "▲" if d > 0 else ("▼" if d < 0 else "=")
            b.append(_bullet(
                f"{nombre}: {chispa}  {valor:g} ({fecha:%d/%m})  ·  {flecha} {abs(d):g} vs "
                f"{serie[1][0]:%d/%m}  ·  {len(serie)} lecturas{marca}"))
        else:
            b.append(_bullet(f"{nombre}: {valor:g} ({fecha:%d/%m})  ·  primera lectura{marca}"))

    if sync["omitidas"]:
        legible = lambda c: idx[c]["nombre"] if c in idx else c
        b.append(_callout(
            "No medibles esta semana — se deja hueco en la serie en vez de un dato falso:\n"
            + "\n".join(f"• {legible(c)} — {motivo}" for c, motivo in sync["omitidas"]), "⚠️"))
    if sync["sin_kpi"]:
        b.append(_callout("Sin fila en KPIs [DB] (no se puede registrar): "
                          + ", ".join(sync["sin_kpi"]), "🔴"))
    return b


def build_blocks(lunes, domingo, insta, grat, semana, sync, series):
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
        return b + bloques_serie(sync, series)

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
    return b + bloques_serie(sync, series)

# ── Panel de tarjetas (lo primero que se ve al abrir la página) ─────────────────

FIRMA_TARJETAS = "Panel actualizado por kpis.py"


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


MAX_POR_FILA = 3   # con 4+ columnas Notion parte las palabras y apila el sparkline


def _repartir_en_filas(columnas):
    """Trocea en filas de MAX_POR_FILA. Un column_list exige >= 2 columnas,
    así que si la última fila se queda con una sola, se reequilibra."""
    filas = [columnas[i:i + MAX_POR_FILA] for i in range(0, len(columnas), MAX_POR_FILA)]
    if len(filas) > 1 and len(filas[-1]) == 1:
        filas[-1].insert(0, filas[-2].pop())
    return filas


def construir_tarjetas(series):
    """Una tarjeta por fila Activo de Dashboard Layout [DB], en el orden y con
    el tipo (Tarjeta / Valor fijo) que Javi haya configurado en Notion."""
    columnas = []
    for fila in layout_rows():
        etiqueta, emoji, sufijo = fila["etiqueta"], fila["icono"], fila["sufijo"]
        serie = series.get(fila["kpi_id"], [])

        if not serie:
            texto = f"{etiqueta}\n—\nsin datos"
            color = "gray_background"
        else:
            fecha, valor = serie[0]

            if fila["menor_es_mejor"]:
                ok = len(serie) > 1 and valor < serie[1][1]
            elif fila["meta"] is not None:
                ok = valor >= fila["meta"]
            else:
                ok = None   # sin Meta ni "menor es mejor" → solo mostrar el dato, sin juicio
            color = "gray_background" if ok is None else (
                "green_background" if ok else "red_background")

            if fila["tipo"] == "Valor fijo":
                # Sin sparkline ni delta: para KPIs infrecuentes, la tendencia
                # semana a semana es ruido, no señal.
                texto = f"{etiqueta}\n{valor:g}{sufijo}\núltima lectura · {fecha:%d/%m}"
            else:
                cronologica = [v for _, v in reversed(serie[-8:])]
                chispa = sparkline(cronologica)
                if len(serie) > 1:
                    d = valor - serie[1][1]
                    flecha = "▲" if d > 0 else ("▼" if d < 0 else "=")
                    delta = f"{flecha} {abs(d):g}"
                else:
                    delta = "1ª lectura"
                texto = f"{etiqueta}\n{valor:g}{sufijo}\n{chispa}\n{delta} · {fecha:%d/%m}"

        columnas.append({"object": "block", "type": "column",
                         "column": {"children": [_tarjeta(etiqueta, emoji, texto, color)]}})

    bloques = [{"object": "block", "type": "column_list", "column_list": {"children": fila}}
               for fila in _repartir_en_filas(columnas)]
    bloques.append(_p(f"{FIRMA_TARJETAS} · {datetime.now():%Y-%m-%d %H:%M}"))
    return bloques


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
            # El panel puede ocupar varias filas: borra todos los column_list
            # consecutivos que hay justo antes de la firma, no solo el último.
            borradas, j = 0, i - 1
            while j >= 0 and hijos[j]["type"] == "column_list":
                requests.delete(f"https://api.notion.com/v1/blocks/{hijos[j]['id']}",
                                headers=NOTION_HEADERS).raise_for_status()
                borradas += 1
                j -= 1
            print(f"♻️  Panel anterior eliminado ({borradas} fila(s)).")
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
    es_lunes = date.today().weekday() == 0

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
        print("✅ Sistema semanal: ⚠️  no se encontró la página de la semana")
    else:
        dias = semana["dias"]
        per_ok  = sum(v["personal"][0] for v in dias.values())
        per_tot = sum(v["personal"][1] for v in dias.values())
        fac_ok  = sum(v["facephi"][0]  for v in dias.values())
        fac_tot = sum(v["facephi"][1]  for v in dias.values())
        print(f"✅ «{semana['titulo']}» — {len(dias)}/7 días con contenido")
        print(f"   personal: {per_ok}/{per_tot}  ·  facephi: {fac_ok}/{fac_tot}  ·  "
              f"claude: {semana['claude_dias']}/7")
        if not es_lunes:
            print("   ℹ️  hoy no es lunes: es una foto a medias, no se registrará como lectura final")

    if not write:
        print("\nℹ️  Modo lectura. Usa --write para publicar en el dashboard.")
        return

    print("\n🗂️  Sincronizando KPI Readings…")
    sync = sincronizar_readings(lunes, insta, grat, semana, es_lunes)
    for clave, valor in sync["creadas"]:
        print(f"   ✅ lectura creada — {clave}: {valor:g}")
    for clave, nombre in sync["saltadas"]:
        print(f"   ⏭️  ya existía — {nombre}")
    for clave, motivo in sync["omitidas"]:
        print(f"   ⚠️  omitida — {clave} ({motivo})")
    for clave in sync["sin_kpi"]:
        print(f"   ❌ sin fila en KPIs [DB] — {clave}")

    print("\n📊 Escribiendo en el dashboard…")
    series = series_por_kpi()               # una sola pasada, compartida por tarjetas y detalle
    write_tarjetas(construir_tarjetas(series))
    write_section(build_blocks(lunes, domingo, insta, grat, semana, sync, series))
    print(f"🔗 https://app.notion.com/p/{DASHBOARD_PAGE_ID}")

    # Reset: SOLO lunes, y SOLO si el KPI de checks ya quedó guardado en Notion
    # (recién creado o ya existente de una corrida anterior hoy). Nunca borramos
    # antes de confirmar que el dato está a salvo.
    checks_a_salvo = (any(c == CLAVE_CHECKS for c, _ in sync["creadas"]) or
                      any(c == CLAVE_CHECKS for c, _ in sync["saltadas"]))
    if es_lunes and semana and checks_a_salvo:
        print("\n🧹 Reseteando la semana (lunes, dato ya guardado)…")
        resetear_semana(semana)
    elif es_lunes and semana:
        print("\nℹ️  Es lunes pero el KPI de checks no se guardó — no se resetea la página "
              "para no perder datos sin registrar.")


if __name__ == "__main__":
    main()
