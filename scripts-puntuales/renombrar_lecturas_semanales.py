"""
Migración puntual — renombrar lecturas semanales a "Nombre - WXX-AAAA" — 2026-08-31.

Javi quiere poder escanear la serie de un KPI semanal por número de semana ISO
en vez de por fecha exacta ("Diario de Gratitud (Días) - W36-2026" en vez de
"Diario de Gratitud (Días) · 2026-08-24"). Afecta a TODAS las lecturas de
KPIs con Frecuencia=Semanal en KPIs [DB] — no solo a las que escribe kpis.py,
incluye entradas manuales como Instagram.

Los KPIs de otra Frecuencia (Diaria, Mensual...) NO se tocan a propósito: un
snapshot Diario (p. ej. tareas_pendientes) titulado solo con la semana sería
ambiguo — varias lecturas de la misma semana, mismo título. La fecha sigue
viva en la propiedad `Fecha` en cualquier caso; esto solo cambia el título
visible (`Registro`).

A partir de ahora, kpis.py ya escribe las lecturas semanales que él mismo
genera con este formato (ver crear_reading() en kpis.py) — este script es
solo para poner al día lo que ya existía antes del cambio.

Dry-run por defecto; --apply para escribir.
"""

import os
import sys
from datetime import date

import requests

NOTION_TOKEN   = os.environ["NOTION_TOKEN"]
KPIS_DB_ID     = "3ae9982c113c80719d03e543f608f4c2"
READINGS_DB_ID = "c72ead033113467fad46bc8dc0de71d3"

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
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


def semana_iso(fecha):
    anio, semana, _ = fecha.isocalendar()
    return f"W{semana}-{anio}"


def main():
    aplicar = "--apply" in sys.argv
    print("=" * 62)
    print(f"🩹 Renombrado de lecturas semanales — {'APLICANDO' if aplicar else 'DRY-RUN'}")
    print("=" * 62)

    kpis_semanales = []
    for fila in query_db(KPIS_DB_ID):
        props = fila["properties"]
        frecuencia = (props.get("Frecuencia", {}).get("select") or {}).get("name")
        if frecuencia != "Semanal":
            continue
        nombre = "".join(i["plain_text"] for i in
                         props.get("Nombre", {}).get("title", [])).strip()
        kpis_semanales.append((fila["id"], nombre))

    print(f"KPIs con Frecuencia=Semanal ({len(kpis_semanales)}):")
    for _, nombre in kpis_semanales:
        print(f"  • {nombre}")
    print()

    nombres = dict(kpis_semanales)
    cambios = 0
    for row in query_db(READINGS_DB_ID):
        props = row["properties"]
        kpi_rel = props.get("KPI", {}).get("relation", [])
        if not kpi_rel or kpi_rel[0]["id"] not in nombres:
            continue
        fecha_str = (props.get("Fecha", {}).get("date") or {}).get("start")
        if not fecha_str:
            continue
        fecha = date.fromisoformat(fecha_str[:10])
        nombre = nombres[kpi_rel[0]["id"]]
        nuevo_titulo = f"{nombre} - {semana_iso(fecha)}"

        actual = "".join(i["plain_text"] for i in
                         props.get("Registro", {}).get("title", [])).strip()
        if actual == nuevo_titulo:
            continue

        print(f"  • «{actual}»\n      → «{nuevo_titulo}»")
        cambios += 1

        if aplicar:
            r = requests.patch(
                f"https://api.notion.com/v1/pages/{row['id']}",
                headers=NOTION_HEADERS,
                json={"properties": {"Registro": {"title": [
                    {"text": {"content": nuevo_titulo[:2000]}}]}}})
            if not r.ok:
                print(f"      ❌ {r.status_code}: {r.text}")
            r.raise_for_status()

    print("=" * 62)
    print(f"{'✅ Renombradas' if aplicar else 'ℹ️  Se renombrarían'} {cambios} lecturas.")
    if not aplicar:
        print("   Ejecuta con --apply para escribir.")
    print("=" * 62)


if __name__ == "__main__":
    main()
