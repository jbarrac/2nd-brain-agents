"""
2nd Brain — KPIs Personales (sin IA)

Computa los KPIs de VIDA (no de salud del sistema: eso es linter.py) y los
escribe como sección gestionada "📈 KPIs Personales" en el dashboard de Notion.

Fuentes:
  - Gratitud    → Diario de Gratitud [DB] (días con entrada en la semana)
  - Claude      → checkbox diario en la página de Planificación Semanal
  - Checks      → to_do de la Planificación Semanal, bloque personal vs Facephi
  - Tareas      → Tasks [DB] (snapshot diario, no semanal: abiertas + alta prioridad)

Instagram (Clave `instagram_horas`) YA NO se auto-detecta: el campo del que
salía ("Instagram (h)" en Weekly Self-Assessment) desapareció al renombrar esa
DB a Coaching Assessment [DB] (2026-08-09). Javi decidió que a partir de ahora
sea 100% manual, como Peso o Rentabilidad — una lectura suelta en
KPI Readings [DB] cuando toque. El renderizado (tarjeta + detalle) ya es
genérico vía Dashboard Layout [DB], así que no hace falta código para eso.

Solo lee (salvo KPI Readings y su propio bloque del dashboard). Coste: 0 tokens de IA.
"""

import os
import sys
from datetime import date, datetime, timedelta

import requests

# ── Configuración ──────────────────────────────────────────────────────────────

NOTION_TOKEN      = os.environ["NOTION_TOKEN"]
GRATITUD_DB_ID    = "c726a373ea4e49bf8b85197ae0cddebd"   # Diario de Gratitud [DB]
PLANNING_PAGE_ID  = "3b19982c113c809ea424c4aa600eeb37"   # Planificación Semanal (Current Week)
SISTEMA_PAGE_ID   = "2ed9982c113c809a9186eca7c1f79385"   # Sistema: Planificación Semanal — cuelga # Histórico
TEMPLATE_PAGE_ID  = "3809982c113c80bd8e57c188737cafd9"   # _ DDMMM2026 Template Planificación Semanal
TASKS_DB_ID       = "067cbf54b7e741b09e059291a44a31c1"   # Tasks [DB] (Roadmap & Tasks)
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
CLAVE_TAREAS   = "tareas_pendientes"

# Objetivos (espejo de config/areas.yaml — si cambian allí, cambian aquí)
META_GRATITUD = 3   # días/semana con entrada
META_CLAUDE   = 4   # días/semana con trabajo en proyectos personales
META_CHECKS   = 5   # días/semana con el bloque personal completo

DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MESES_ABBR = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL",
              "AGO", "SEP", "OCT", "NOV", "DIC"]

# Umbral de "dato viejo" para tarjetas manuales (Instagram, Sueño...). No
# distingue por Frecuencia del KPI todavía — hoy todos los manuales del panel
# son semanales, así que un umbral único vale; revisar si se añade uno diario
# o mensual.
UMBRAL_OBSOLETO_DIAS = 10
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

# ── KPI: Tareas pendientes (snapshot diario, no semanal) ────────────────────────

def contar_tareas_pendientes():
    """(total, abiertas, alta_prioridad_abiertas) de Tasks [DB].

    Réplica ligera de lo que linter.py ya calcula para su propio informe —
    aceptamos el escaneo duplicado de Tasks [DB] a cambio de que kpis.py no
    dependa de linter.py ni comparta estado entre scripts.
    """
    total = abiertas = alta = 0
    for row in query_db(TASKS_DB_ID):
        props = row["properties"]
        status = (props.get("Status", {}).get("select") or {}).get("name")
        priority = (props.get("Priority", {}).get("select") or {}).get("name")
        total += 1
        if status in ("Not Started", "In Progress"):
            abiertas += 1
            if priority == "🔴 Alta":
                alta += 1
    return total, abiertas, alta

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
    7 días está presente desde el lunes. El reset (ver
    resetear_semana_desde_plantilla()) ya NO es automático — solo archivar()
    corre solo cada lunes; el reset es una acción explícita, para darle
    margen a Javi de corregir el cierre antes de que se borre nada.

    Cada día es un heading_2 con toggle=true ("## Lunes... {toggle=true}"),
    y sus to_do viven ANIDADOS dentro (hijos del heading, no hermanos) — hay
    que bajar un nivel más que en el diseño anterior. El divider `---` sigue
    separando bloque personal / bloque Facephi dentro de cada día.
    """
    bloques = list_block_children(PLANNING_PAGE_ID)
    titulo = next((plain(b, "heading_3") for b in bloques if b["type"] == "heading_3"),
                  "Semana actual")

    dias, claude_dias = {}, 0

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
                if checked:
                    dias[dia][seccion][0] += 1
                    if any(m in texto_item for m in CLAUDE_MARKERS):
                        claude_dias += 1

    if not dias:
        return None
    return {"titulo": titulo, "dias": dias, "claude_dias": claude_dias}


def _titulo_semana(lunes):
    """'17AGO' a partir del lunes de referencia — mismo formato que ya usa Javi
    en los títulos de página ('Current Week 17AGO', 'Week 10AGO')."""
    return f"{lunes.day}{MESES_ABBR[lunes.month - 1]}"


def _sin_nulos(valor):
    """Notion devuelve `null` en campos opcionales al LEER (icon, href, link...)
    pero rechaza ese mismo `null` explícito al CREAR — quiere la clave ausente,
    no en None. Limpieza recursiva porque el null puede estar anidado (p. ej.
    dentro de cada item de un rich_text, no solo a nivel de bloque)."""
    if isinstance(valor, dict):
        return {k: _sin_nulos(v) for k, v in valor.items() if v is not None}
    if isinstance(valor, list):
        return [_sin_nulos(v) for v in valor]
    return valor


def clonar_bloque(block):
    """Reconstruye un bloque LEÍDO en la forma que espera la API para crear
    uno nuevo — Notion usa (casi) la misma forma para leer y escribir estas
    propiedades (rich_text, checked, color, is_toggleable...), así que una
    copia superficial de block[tipo] basta (tras quitar los null). Recursivo:
    clona también los hijos, así que un toggle con to_do anidados (los días)
    se copia entero de una vez.
    """
    tipo = block["type"]
    contenido = _sin_nulos(dict(block.get(tipo) or {}))
    nuevo = {"object": "block", "type": tipo, tipo: contenido}
    if block.get("has_children"):
        contenido["children"] = [clonar_bloque(h) for h in list_block_children(block["id"])]
    return nuevo


def existe_archivo(titulo_semana):
    """Evita duplicar el archivo si el cron corre dos veces el mismo lunes."""
    nombre = f"Planificación Semanal (Week {titulo_semana})"
    for b in list_block_children(SISTEMA_PAGE_ID):
        if b["type"] == "child_page" and b["child_page"].get("title") == nombre:
            return True
    return False


def archivar_semana(lunes):
    """Duplica el contenido ACTUAL de la Página Fija a una página nueva bajo
    # Histórico en la página Sistema — mismo naming que Javi ya usa a mano
    ('Week 10AGO', 'Week 3AGO'). No destructivo: solo crea, nunca borra ni
    toca la Página Fija. Se llama todos los lunes, incondicionalmente —
    es la red de seguridad antes de cualquier corrección o reseteo posterior.
    """
    titulo_semana = _titulo_semana(lunes)
    if existe_archivo(titulo_semana):
        print(f"⏭️  Archivo de la semana {titulo_semana} ya existe — no se duplica.")
        return

    bloques = [clonar_bloque(b) for b in list_block_children(PLANNING_PAGE_ID)]
    payload = {
        "parent": {"page_id": SISTEMA_PAGE_ID},
        "properties": {"title": {"title": [
            {"text": {"content": f"Planificación Semanal (Week {titulo_semana})"}}]}},
        "children": bloques,
    }
    r = requests.post("https://api.notion.com/v1/pages", headers=NOTION_HEADERS, json=payload)
    if not r.ok:
        print(f"❌ Error archivando la semana {titulo_semana}: {r.status_code} {r.text}")
    r.raise_for_status()
    print(f"🗄️  Semana {titulo_semana} archivada bajo # Histórico "
          f"({len(bloques)} bloques de nivel superior).")


# Secciones que el reset sustituye por su versión de la Plantilla. "Global
# Semanal" se editó igual que un día (objetivos G1/G2/G3 narrowed durante la
# semana) — va primero porque así aparece en la página, antes de Lunes.
# "Focus Semanal" NO está aquí a propósito: es la rotación de foco entre
# semanas que Javi cura él mismo, la Plantilla no la sabe reproducir.
SECCIONES_RESET = ["Global Semanal"] + DIAS


def resetear_semana_desde_plantilla():
    """Sustituye Global Semanal + cada día (Lunes–Domingo) de la Página Fija
    por el de la Plantilla — checks Y texto (teletrabajo/deporte/objetivos
    G1-G2-G3/etc.) vuelven a los genéricos. Focus Semanal queda intacto.

    NO se llama automáticamente desde el cron — es una acción explícita
    (--reset-semana) para no borrar nada antes de que Javi haya podido
    revisar/corregir el cierre de la semana. Asume que la semana ya se
    archivó (archivar_semana()) antes de llamar a esto.
    """
    secciones_plantilla = {}
    for b in list_block_children(TEMPLATE_PAGE_ID):
        if b["type"] == "heading_2":
            texto = plain(b, "heading_2")
            sec = next((s for s in SECCIONES_RESET if texto.lower().startswith(s.lower())), None)
            if sec:
                secciones_plantilla[sec] = b

    faltan = [s for s in SECCIONES_RESET if s not in secciones_plantilla]
    if faltan:
        print(f"❌ La Plantilla no tiene bloque para: {', '.join(faltan)} — abortando, no se toca nada.")
        return

    borrados = 0
    for b in list_block_children(PLANNING_PAGE_ID):
        if b["type"] != "heading_2":
            continue
        texto = plain(b, "heading_2")
        if next((s for s in SECCIONES_RESET if texto.lower().startswith(s.lower())), None):
            r = requests.delete(f"https://api.notion.com/v1/blocks/{b['id']}", headers=NOTION_HEADERS)
            if not r.ok:
                print(f"❌ Error borrando '{texto}': {r.status_code} {r.text}")
            r.raise_for_status()
            borrados += 1

    nuevos = [clonar_bloque(secciones_plantilla[s]) for s in SECCIONES_RESET]
    r = requests.patch(f"https://api.notion.com/v1/blocks/{PLANNING_PAGE_ID}/children",
                       headers=NOTION_HEADERS, json={"children": nuevos})
    if not r.ok:
        print(f"❌ Error escribiendo las secciones desde la Plantilla: {r.status_code} {r.text}")
    r.raise_for_status()
    print(f"🧹 Semana reseteada desde la Plantilla — {borrados} secciones sustituidas por "
          f"{len(nuevos)} nuevas (Global Semanal + 7 días). Focus Semanal intacto.")

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
        # Sin .strip(): un espacio inicial en "Sufijo" (" h", " abiertas") es
        # intencional — sufijos tipo "/7" o "%" no lo llevan. Strip se comía
        # el espacio y dejaba "4abiertas", "6.8h" pegados al valor.
        sufijo = "".join(i["plain_text"] for i in
                         props.get("Sufijo", {}).get("rich_text", []))
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


def valores_de_la_semana(grat, semana, es_lunes):
    """Qué se puede medir esta semana y qué no.

    Los 2 KPIs que salen de la plantilla semanal (checks, proyectos personales)
    solo se registran el LUNES: es el único día en que la página fija refleja
    una semana ya cerrada. Cualquier otro día, la página está a medias (los
    días futuros existen pero vacíos) — escribirlo sería un dato falso, no
    incompleto. Preferimos un hueco en la serie.

    Instagram no aparece aquí: pasó a ser 100% manual (ver docstring del
    módulo), no hay nada que este script pueda calcular.
    """
    escribir, omitir = [], []

    # Gratitud: fuente independiente (su propia DB), pero el VALOR es acumulado
    # a lo largo de la semana — igual que checks/proyectos, solo se cierra el
    # lunes. Escribirlo cualquier día "congelaba" para siempre el conteo del
    # primer día que corriera el script (bug real, detectado 2026-08-09: una
    # corrida de prueba en martes dejó Gratitud en 1/7 toda la semana, cuando
    # el cierre real fue 7/7).
    if es_lunes:
        escribir.append((CLAVE_GRATITUD, float(grat["dias"]), None))
    else:
        omitir.append((CLAVE_GRATITUD, "solo se registra el lunes, al cerrar la semana"))

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


def sincronizar_readings(lunes, grat, semana, es_lunes):
    """Escribe las lecturas de la semana. Idempotente: no duplica si ya existen."""
    idx = kpi_index()
    ya  = readings_de_fecha(lunes)
    escribir, omitir = valores_de_la_semana(grat, semana, es_lunes)

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


def sincronizar_tareas_pendientes():
    """Snapshot DIARIO del backlog — a diferencia de los KPIs semanales, se
    registra cada vez que corre el script (no solo el lunes): es un estado
    puntual (como Peso), no un acumulado de la semana. Por eso el dedup usa
    la fecha de HOY, no el lunes de referencia."""
    idx = kpi_index()
    kpi = idx.get(CLAVE_TAREAS)
    if not kpi:
        return {"estado": "sin_kpi"}

    hoy = date.today()
    ya_hoy = set()
    for row in query_db(READINGS_DB_ID):
        props = row["properties"]
        f = (props.get("Fecha", {}).get("date") or {}).get("start")
        if f and f[:10] == hoy.isoformat():
            for rel in props.get("KPI", {}).get("relation", []):
                ya_hoy.add(rel["id"].replace("-", ""))

    if kpi["id"].replace("-", "") in ya_hoy:
        return {"estado": "saltada"}

    total, abiertas, alta = contar_tareas_pendientes()
    nota = f"{abiertas} abiertas de {total} totales"
    crear_reading(kpi["id"], kpi["nombre"], hoy, float(alta), nota)
    return {"estado": "creada", "total": total, "abiertas": abiertas, "alta": alta}


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
        if (date.today() - serie[0][0]).days > UMBRAL_OBSOLETO_DIAS:
            dias = (date.today() - serie[0][0]).days
            b.append(_bullet(f"{nombre}: sin dato esta semana  ·  última lectura "
                             f"{serie[0][1]:g} el {serie[0][0]:%d/%m} (hace {dias}d)"))
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


def build_blocks(lunes, domingo, grat, semana, sync, series):
    now = datetime.now()
    b = [_p(f"Actualizado automáticamente por kpis.py · {now:%Y-%m-%d %H:%M}  ·  "
            f"semana {lunes:%d/%m} – {domingo:%d/%m}")]

    # Instagram: sin sección dedicada — es 100% manual desde 2026-08-09 y ya
    # aparece, como cualquier otro KPI con Clave, en la tarjeta del panel y en
    # "Serie temporal" más abajo (bloques_serie), sin código específico.

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
        elif (date.today() - serie[0][0]).days > UMBRAL_OBSOLETO_DIAS:
            # Dato real pero viejo (KPI manual sin actualizar) — no lo pintamos
            # como si fuera de esta semana. Mejor "sin dato" honesto que un
            # número desactualizado con pinta de actual.
            dias = (date.today() - serie[0][0]).days
            texto = f"{etiqueta}\nsin dato esta semana\núltima: {serie[0][1]:g}{sufijo} hace {dias}d"
            color = "gray_background"
        else:
            fecha, valor = serie[0]

            if fila["menor_es_mejor"]:
                # "Menor es mejor" compara contra la lectura anterior, no un
                # umbral absoluto — sin una previa no hay base de juicio.
                ok = (valor < serie[1][1]) if len(serie) > 1 else None
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
    if "--reset-semana" in sys.argv:
        print("🧹 Reset explícito de la Página Fija desde la Plantilla…")
        resetear_semana_desde_plantilla()
        return

    write = "--write" in sys.argv
    lunes, domingo = semana_referencia()
    es_lunes = date.today().weekday() == 0

    print("=" * 55)
    print(f"📈 2nd Brain — KPIs Personales — semana {lunes:%d/%m/%Y} – {domingo:%d/%m/%Y}")
    print("=" * 55)

    grat   = kpi_gratitud(lunes, domingo)
    semana = parse_semana_actual()

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
    sync = sincronizar_readings(lunes, grat, semana, es_lunes)
    for clave, valor in sync["creadas"]:
        print(f"   ✅ lectura creada — {clave}: {valor:g}")
    for clave, nombre in sync["saltadas"]:
        print(f"   ⏭️  ya existía — {nombre}")
    for clave, motivo in sync["omitidas"]:
        print(f"   ⚠️  omitida — {clave} ({motivo})")
    for clave in sync["sin_kpi"]:
        print(f"   ❌ sin fila en KPIs [DB] — {clave}")

    tareas = sincronizar_tareas_pendientes()
    if tareas["estado"] == "creada":
        print(f"   ✅ lectura creada — tareas_pendientes: {tareas['alta']:g} alta prioridad "
              f"({tareas['abiertas']} abiertas de {tareas['total']} totales)")
    elif tareas["estado"] == "saltada":
        print("   ⏭️  ya existía — tareas_pendientes (ya se registró hoy)")
    elif tareas["estado"] == "sin_kpi":
        print("   ❌ sin fila en KPIs [DB] — tareas_pendientes")

    print("\n📊 Escribiendo en el dashboard…")
    series = series_por_kpi()               # una sola pasada, compartida por tarjetas y detalle
    write_tarjetas(construir_tarjetas(series))
    write_section(build_blocks(lunes, domingo, grat, semana, sync, series))
    print(f"🔗 https://app.notion.com/p/{DASHBOARD_PAGE_ID}")

    # Archivo: incondicional cada lunes, nunca destructivo (solo crea). Es la
    # red de seguridad antes de cualquier corrección o del reset posterior —
    # que YA NO es automático (ver --reset-semana): así Javi tiene margen para
    # revisar/corregir el cierre antes de que se borre nada de la Página Fija.
    if es_lunes:
        print("\n🗄️  Archivando la semana bajo # Histórico…")
        archivar_semana(lunes)


if __name__ == "__main__":
    main()
