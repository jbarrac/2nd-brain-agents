"""
Reparación puntual de KPIs [DB] — 2026-08-01.

Al cambiar las opciones del select `Fuente`, Notion vació el valor de toda fila
cuya opción dejó de existir (`Manual`, `Automático (kpis.py)`, `iOS (Manual)`):
25 de 37 filas se quedaron sin Fuente.

La información NO se pierde del todo: el valor borrado era casi siempre
"Manual", que es justo el concepto que sacamos de `Fuente` y movemos a la nueva
columna `Ingesta`. Así que reponer `Ingesta = Manual` recupera el contenido real.
`Fuente` (el DÓNDE) se rellena solo donde se conoce con certeza; el resto lo
revisa Javi, que ya está repasando los KPIs uno a uno.

Solo escribe en campos VACÍOS: nunca pisa lo que Javi haya puesto.
Dry-run por defecto; `--apply` para escribir.
"""

import os
import sys

import requests

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
KPIS_DB_ID   = "3ae9982c113c80719d03e543f608f4c2"

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

# Los que conozco con certeza: (Fuente, Ingesta, Clave)
# La Clave es el ancla estable de kpis.py — inmune a que se renombre el KPI.
CONOCIDOS = {
    "Diario de Gratitud (Días con entrada)":      ("Diario de Gratitud [DB]", "Manual", "gratitud_dias"),
    "Checks sistema semanal (Personal + Facephi)": ("Plantilla Semanal",      "Manual", "checks_semanal"),
    "Días trabajando en proyectos personales":     ("Plantilla Semanal",      "Manual", "proyectos_personales"),
    "Horas de Instagram":                          ("iOS Screen Time",        "Manual", "instagram_horas"),
    "Rentabilidad Mensual":                        ("Excel-Drive",            "Manual", None),
}


def query_db(db_id):
    filas, cursor = [], None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        r = requests.post(f"https://api.notion.com/v1/databases/{db_id}/query",
                          headers=NOTION_HEADERS, json=payload)
        r.raise_for_status()
        data = r.json()
        filas.extend(data.get("results", []))
        if not data.get("has_more"):
            return filas
        cursor = data.get("next_cursor")


def texto(props, campo):
    return "".join(i["plain_text"] for i in props.get(campo, {}).get("rich_text", [])).strip()


def seleccion(props, campo):
    s = props.get(campo, {}).get("select")
    return s["name"] if s else None


def main():
    aplicar = "--apply" in sys.argv
    print("=" * 62)
    print(f"🩹 Reparación de KPIs [DB] — {'APLICANDO' if aplicar else 'DRY-RUN'}")
    print("=" * 62)

    cambios = 0
    for fila in query_db(KPIS_DB_ID):
        props   = fila["properties"]
        nombre  = "".join(i["plain_text"] for i in props.get("Nombre", {}).get("title", [])).strip()
        fuente  = seleccion(props, "Fuente")
        ingesta = seleccion(props, "Ingesta")
        clave   = texto(props, "Clave")

        nuevo = {}
        conocido = CONOCIDOS.get(nombre)

        # 1) Fuente: solo si está vacía y la conocemos.
        if not fuente and conocido and conocido[0]:
            nuevo["Fuente"] = {"select": {"name": conocido[0]}}

        # 2) Ingesta: repone lo que el ALTER borró.
        if not ingesta:
            if conocido:
                valor = conocido[1]
            elif fuente == "Apple Health":
                valor = "Automática"          # lo recoge el iPhone solo
            elif fuente == "Por definir":
                valor = None                  # no inventamos
            else:
                valor = "Manual"              # era lo que decía Fuente antes
            if valor:
                nuevo["Ingesta"] = {"select": {"name": valor}}

        # 3) Clave: ancla del script.
        if not clave and conocido and conocido[2]:
            nuevo["Clave"] = {"rich_text": [{"text": {"content": conocido[2]}}]}

        if not nuevo:
            continue

        resumen = ", ".join(
            f"{k}={conocido[0] if k == 'Fuente' else (conocido[2] if k == 'Clave' else nuevo[k]['select']['name'])}"
            for k in nuevo)
        print(f"  • {nombre}\n      → {resumen}")
        cambios += 1

        if aplicar:
            r = requests.patch(f"https://api.notion.com/v1/pages/{fila['id']}",
                               headers=NOTION_HEADERS, json={"properties": nuevo})
            if not r.ok:
                print(f"      ❌ {r.status_code}: {r.text}")
            r.raise_for_status()

    print("=" * 62)
    print(f"{'✅ Aplicados' if aplicar else 'ℹ️  Se aplicarían'} {cambios} cambios.")
    if not aplicar:
        print("   Ejecuta con --apply para escribir.")
    print("   Solo se tocan campos vacíos; nada de lo que hayas puesto se pisa.")
    print("=" * 62)


if __name__ == "__main__":
    main()
