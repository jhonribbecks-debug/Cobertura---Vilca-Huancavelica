# Tenorious-Toolbox

Toolbox independiente y reutilizable de automatización estructural para
cubiertas metálicas: **SAP2000 (.s2k) → Revit** + finalización de la malla
del tijeral + generación de memoria de cálculo.

Este repositorio contiene **solo código y documentación** (no los archivos de
proyecto). Los modelos `.rvt`, planos `.dwg`, `.s2k` y memorias viven en la
carpeta del proyecto (`C:\Users\aintc\OneDrive\Escritorio\Tenorious`).

## Contenido

| Carpeta | Función |
|---|---|
| `revit_mcp/` | Servidor MCP + puente pyRevit Routes (importar `.s2k` a Revit, rutas de arco/malla/correas). |
| `sap2000gen/` | Generador de archivos `.s2k` desde planos (DWG/DXF) y memoria de cálculo `.docx`. |
| `scripts/` | Utilidades: memoria, XML/IOM (Idea StatiCa), docx→pdf, verificación. |
| `.opencode/skills/cobertura-revit/` | Skill de opencode con el flujo completo de finalización en Revit. |

## Requisitos

- Revit 2027 + pyRevit (extensión `s2k-to-revit-python`).
- Python 3.x. Entorno: `revit_mcp/.venv` (no subido a git, recrear con
  `pip install -r revit_mcp/requirements.txt`).

## Configuración (proyecto-genérico)

El toolbox es **genérico**. Solo se configura por variable de entorno:

- `TENORIOUS_PROJECT`: ruta al modelo `.rvt` a abrir/operar
  (default: `COBERTURA HUANCALPI.rvt`).
- `TENORIOUS_REVIT_EXE`: ruta del ejecutable de Revit
  (default: `C:\Program Files\Autodesk\Revit 2027\Revit.exe`).

pyRevit lee la extensión desde `%APPDATA%\pyRevit\pyRevit_config.ini`
(`[core] userextensions`) apuntando a `...\Tenorious-Toolbox\revit_mcp\pyrevit_extension`.
opencode usa el MCP declarado en `opencode.json` del proyecto.

## Uso rápido

```powershell
# Control de Revit (stop / start / status)
cd revit_mcp
python revitctl.py status
python revitctl.py start --timeout 240
python revitctl.py stop
```

El flujo de finalización del tijeral (simetrizar malla, alinear extremos,
correas sobre brida, guardar) está documentado en el skill
`.opencode/skills/cobertura-revit/SKILL.md` y se puede ejecutar de una sola
llamada con la ruta `/finish_arc_pipeline/`.

## Nota sobre los scripts del proyecto

Los scripts en `scripts/` pueden contener rutas absolutas de un proyecto
concreto (Huancalpi). Antes de reusarlos en otro proyecto, revisar los paths
hardcodeados o extraerlos a variables de entorno.

## Repo

GitHub: https://github.com/jhonribbecks-debug/Cobertura---Vilca-Huancavelica