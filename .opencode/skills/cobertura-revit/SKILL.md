---
name: cobertura-revit
description: Use when finalizando/automatizando un modelo de cobertura metálica en Revit importado desde SAP2000 (.s2k): simetrizar la malla del tijeral, alinear miembros extremos radiales, apoyar correas sobre la brida superior, reiniciar Revit para recargar rutas, y guardar el documento. Sirve para el flujo de arco de tijera con montantes HSS50, bridas HSS100x50x3/4.5 y correas HSS150x50x3.
---

# Cobertura metálica: flujo de finalización en Revit (MCP + pyRevit)

Documenta el procedimiento validado para terminar la malla del tijeral
(cobertura en arco, tipo "COBERTURA HUANCALPI") tras importar el modelo
`.s2k` de SAP2000. Todos los pasos se ejecutan contra el puente pyRevit
Routes en `http://127.0.0.1:48884/revit_mcp/`.

## Constantes geométricas del proyecto (validadas)

- Centro de simetría del arco: `X = 11.325` (= 22.65/2). Los espejos se
  calculan como `X' = 2*11.325 - X`.
- Pórticos (planos Y): `0, 5.05, 10.1, 15.15, 20.2, 25.25, 30.3` (7 tijerales).
- Arco superior (brida): centro `(11.325, -2.3)`, `R = 14.16 m`
  (familia HSS100x50x3, DB.Arc real).
- Correas: HSS150x50x3, longitud 30.3 m (corren en Y). Su centro de línea
  debe quedar a **R + 0.125 m** (0.075 semiprofundidad correa + 0.05
  semiprofundidad brida) para apoyar la cara inferior sobre el canto
  superior de la brida.
- Montantes/diagonales del alma: HSS50x50x2.5. Miembros web detectados con
  `_is_member_web` (nombre contiene `hss50x50x2`).

## Orden recomendado del flujo

1. **Estado**: `POST /revit_status/` o `/status/` → confirma doc y health.
2. **Inspección**: `probe_web_mesh/` (malla por plano Y), `probe_purlins_meta/`
   (correas largas), `inspect_element/` (extremos de una barra por id).
3. **Simetrizar la malla** (voltea la mitad izquierda para que sea espejo
   exacto de la derecha en X=11.325):
   `POST /symmetrize_web/` body `{"dry_run": true}` primero, luego
   `{"dry_run": false}`. Crea espejos de miembros derechos y borra los
   izquierdos que no tengan espejo válido.
4. **Alinear miembros extremos radiales** (montante + diagonal del extremo,
   para que queden sobre el radio del arco):
   `POST /align_extreme_members/` (admite `dry_run`). Esperado: ~22 elementos
   por pórtico, con IfcGUID conservado.
5. **Correas sobre la brida superior**:
   `POST /fix_correas_on_chord/` body `{"dry_run": true}` luego `{"dry_run": false}`.
   Sube cada correa +0.125 m radial (offset `offset_m`, default 0.125).
6. **Guardar**: `POST /save_doc/`.

## Recarga de rutas (IMPORTANTE)

Las rutas de `routes_arc.py` se registran en `startup.py` **solo al cargar la
sesión pyRevit** (arranque de Revit). Si se edita una ruta, hay que reiniciar
Revit para que el cambio tenga efecto. Usar el controlador del toolbox:

```powershell
cd C:\Users\aintc\OneDrive\Escritorio\RIBBECK ENG\OPENCODE\Tenorious-Toolbox\revit_mcp
python revitctl.py stop
python revitctl.py start --timeout 240
```

El `startup.py` auto-abre el `.rvt` definido en `TENORIOUS_PROJECT`
(default: `COBERTURA HUANCALPI.rvt` en Tenorious). Verificar con `/status/`
que `document_title` coincide antes de operar.

## Pipeline de un disparo (herramienta MCP)

El flujo completo (simetrizar + alinear extremos + correas + guardar) se
orquesta desde el **servidor MCP externo** (`mcp_server.py`), no desde Revit:
la herramienta `finish_arc_pipeline(dry_run, planes, skip_save)` llama
secuencialmente a las rutas por HTTP. Usarla así en opencode:

- `finish_arc_pipeline(dry_run=True)` → plan de los 3 pasos sin modificar.
- `finish_arc_pipeline()` → ejecuta todo y guarda el documento.

No usar auto-llamadas HTTP dentro de una ruta de Revit (el servidor de rutas
es single-threaded y se bloquea).

## Rutas útiles en routes_arc.py

| Ruta | Función |
|---|---|
| `/symmetrize_web/` | Simetrizar malla web en X=11.325 (50 creados / 61 borrados típico) |
| `/align_extreme_members/` | Alinear montante+diagonal de extremo al radio del arco |
| `/fix_correas_on_chord/` | Correas HSS150x50x3 a R+0.125 sobre la brida (asigna LocationCurve directo) |
| `/fix_correas_align/` | Alinear correas a nodos de montante (X,Z) |
| `/probe_web_mesh/` | Malla por plano Y (read-only) |
| `/probe_purlins_meta/` | Correas largas: X, Z, longitud (read-only) |
| `/inspect_element/` | Extremos y parámetros de un elemento (read-only) |
| `/save_doc/` | Guardar documento |
| `/rotate_correas_long/` | Giro de sección (STRUCTURAL_BEND_DIR_ANGLE) por curvatura |

## Verificación post-cambios

- **Simetría**: para cada plano Y, cada miembro derecho (punto medio X >
  11.325) debe tener espejo exacto en la izquierda. Esperado: 0 asimetrías.
- **Correas**: cada correa a distancia ~0.125 m de su nodo de montante y
  `hypot(x-11.325, z+2.3) ≈ 14.285`; ambos extremos a la misma Z (sin tilt).
- **Extremos**: la montante y diagonal extremas apoyan exactamente sobre el
  arco (radial), conservando IfcGUID.

## Notas de archivos

- `revit_mcp/pyrevit_extension/s2k-to-revit-python.extension/startup.py`:
  registro de rutas + auto-open.
- `.../revit_mcp/routes_arc.py`: todas las rutas del arco (módulo grande,
  ~6400 líneas).
- `revit_mcp/revitctl.py`: stop/start de Revit.
- `sap2000gen/` + `cli.py`: generación de `.s2k` desde planos y memoria.
- El toolbox es **genérico**: solo se configuran `TENORIOUS_PROJECT` y
  `TENORIOUS_REVIT_EXE` por entorno para usarlo en otro proyecto.