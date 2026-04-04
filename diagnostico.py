"""
2nd Brain - Diagnóstico de Conectividad
Verifica conexión con Notion y cuenta tareas pendientes.
No ejecuta ni modifica nada.
"""

import os
import requests

NOTION_TOKEN  = os.environ["NOTION_TOKEN"]
TASKS_DB_ID   = "067cbf54b7e741b09e059291a44a31c1"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

def test_conexion():
    print("🔌 Test 1: Conectividad con Notion...")
    r = requests.get("https://api.notion.com/v1/users/me", headers=HEADERS)
    if r.status_code == 200:
        nombre = r.json().get("name", "desconocido")
        print(f"   ✅ Conexión OK — Usuario: {nombre}")
        return True
    else:
        print(f"   ❌ Error de conexión — Status: {r.status_code}")
        print(f"   Detalle: {r.text}")
        return False

def test_tareas():
    print("\n📋 Test 2: Acceso a Tasks DB...")
    r = requests.post(
        f"https://api.notion.com/v1/databases/{TASKS_DB_ID}/query",
        headers=HEADERS,
        json={"page_size": 100}
    )
    if r.status_code == 200:
        resultados = r.json().get("results", [])
        print(f"   ✅ Acceso OK — Total de tareas en DB: {len(resultados)}")

        # Contar por estado
        estados = {}
        sin_estado = 0
        for t in resultados:
            s = t["properties"].get("Status", {}).get("select")
            nombre = s["name"] if s else "Sin estado"
            estados[nombre] = estados.get(nombre, 0) + 1

        print("\n   📊 Desglose por estado:")
        for estado, count in sorted(estados.items()):
            print(f"      {estado}: {count}")

        # Tareas pendientes (Not Started)
        pendientes = estados.get("Not Started", 0)
        print(f"\n   🎯 Tareas pendientes (Not Started): {pendientes}")
    else:
        print(f"   ❌ Error accediendo a la DB — Status: {r.status_code}")
        print(f"   Detalle: {r.text}")

if __name__ == "__main__":
    print("=" * 45)
    print("🤖 2nd Brain — Diagnóstico de Conectividad")
    print("=" * 45)
    ok = test_conexion()
    if ok:
        test_tareas()
    print("\n" + "=" * 45)
    print("✅ Diagnóstico completado")
    print("=" * 45)
