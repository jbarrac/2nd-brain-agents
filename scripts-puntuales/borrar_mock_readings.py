"""
Borrado puntual — las 11 lecturas [MOCK] de KPI Readings [DB] — 2026-09-07.

Se metieron el 2026-08-01 para una revisión de UX del dashboard, nunca fueron
datos reales (Peso, Checks sistema semanal). Quedaron pendientes de borrar
desde entonces. Se borran ahora porque el renombrado a formato semanal
("Nombre - WXX-AAAA") les haría perder el prefijo [MOCK], quedando
indistinguibles de una lectura real.

IDs fijos, verificados por consulta antes de escribir este script — no hay
lógica de búsqueda aquí a propósito, para no arriesgarse a barrer algo más.
"""

import os

import requests

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

IDS_MOCK = [
    "3af9982c113c810b81d1ecaa13c7a216",  # [MOCK] Peso · 2026-07-06
    "3af9982c113c8128ade8d6274d2f769c",  # [MOCK] Checks sistema semanal (personal) · 2026-06-22
    "3af9982c113c8134bec9c5b09f7fa452",  # [MOCK] Checks sistema semanal (personal) · 2026-06-29
    "3af9982c113c813ba9a0e054135a8729",  # [MOCK] Peso · 2026-07-20
    "3af9982c113c8172a9daf85f50d5358d",  # [MOCK] Peso · 2026-07-13
    "3af9982c113c817faec3cf4f363e8358",  # [MOCK] Peso · 2026-06-22
    "3af9982c113c8195b5a1d52ae0c7534e",  # [MOCK] Checks sistema semanal (personal) · 2026-07-13
    "3af9982c113c81a4a3ecf633a3d10555",  # [MOCK] Checks sistema semanal (personal) · 2026-07-06
    "3af9982c113c81b4bd78f266224e7c70",  # [MOCK] Peso · 2026-07-27
    "3af9982c113c81d7ab59fb3c495aef77",  # [MOCK] Peso · 2026-06-29
    "3af9982c113c81eda715dbcdb997853e",  # [MOCK] Checks sistema semanal (personal) · 2026-07-20
]


def main():
    print(f"🗑️  Borrando {len(IDS_MOCK)} lecturas [MOCK]…")
    for page_id in IDS_MOCK:
        r = requests.patch(f"https://api.notion.com/v1/pages/{page_id}",
                           headers=NOTION_HEADERS, json={"archived": True})
        if not r.ok:
            print(f"  ❌ {page_id}: {r.status_code} {r.text}")
        r.raise_for_status()
        print(f"  ✅ {page_id}")
    print("✅ Listo.")


if __name__ == "__main__":
    main()
