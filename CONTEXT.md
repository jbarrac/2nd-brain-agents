# 2nd Brain — Contexto del sistema

El 2nd Brain es el sistema personal de organización de Javi en Notion
("2nd AI Brain (Life Optimization)"). Estructura:

- **Tasks [DB]**: tareas con campos Task, Status (Not Started / In Progress /
  Done / Blocked), Type (🤖 Agent / ⚙️ Semi / 👤 Manual), Priority
  (🔴 Alta / 🟡 Media / 🟢 Baja), Context, Output (Expected), Agent Result,
  Life Area (Link), Attempts, Last Attempt.
- **Life Areas [DB]**: las 7 áreas de vida (Internal, Professional, Health,
  Mental, Finance, Social, Free Time). Cada tarea pertenece a un área.
- **Goals [DB]** y **Projects [DB]**: objetivos y proyectos vinculados a áreas.

Convenciones:
- Idioma de los outputs: español. Nombres de entidades/campos: inglés.
- El resultado de cada tarea se escribe en el campo "Agent Result" de Notion
  (límite ~2000 caracteres): sé conciso y accionable.
- Las tareas Type=🤖 Agent las ejecuta el agente de principio a fin; las
  Type=⚙️ Semi solo se PREPARAN (draft/plan/research) para que Javi las cierre.
- El agente corre sin supervisión vía GitHub Actions: si una tarea es ambigua
  o requiere acción humana, es mejor devolver NEEDS_INPUT/BLOCKED que inventar.
