# Revit MCP — Import S2K (SAP2000 → Revit)

Servidor MCP que permite a opencode (u otro cliente MCP) inspeccionar y modelar
directamente en Revit mediante la API de Revit, importando modelos estructurales
de SAP2000 (archivos `.s2k`).

## Arquitectura

```
Cliente MCP (opencode)
        │  stdio (JSON-RPC)
        ▼
mcp_server.py  (Python externo, FastMCP 1.x, venv propio)
        │  HTTP  http://127.0.0.1:48884/revit_mcp
        ▼
pyRevit Routes  (extensión "s2k-to-revit-python" cargada en Revit 2027)
        │  Revit API (doc activo, familias estructurales, ModelCurve)
        ▼
Modelo Revit
```

- El `.s2k` se convierte a JSON con `s2k_to_json.py` (nudos, barras, secciones).
- `mcp_server.py` expone herramientas FastMCP y delega la parte de Revit a
  pyRevit Routes por HTTP.

## Componentes

| Archivo | Función |
|---|---|
| `s2k_to_json.py` | Parsea `.s2k` → `{joints, frames, sections}` (unidades: metros). |
| `mcp_server.py` | Servidor MCP (tools: `revit_status`, `s2k_preview`, `list_structural_families`, `find_base_families`, `create_sections`, `s2k_family_mapping`, `import_s2k`). |
| `pyrevit_extension/s2k-to-revit-python.extension/` | Extensión pyRevit con las rutas HTTP de Routes (`/status/`, `/import_s2k/`, `/ensure_sections/`, etc.). |
| `dynamo/s2k_import.py` | Nodo Python para Dynamo (alternativa manual sin MCP). |
| `requirements.txt` | Dependencias del venv (`mcp>=1.20.0,<2.0.0`, `httpx>=0.28.0`). |

## Instalación

### 1. Cliente MCP (venv)

```powershell
cd revit_mcp
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

### 2. pyRevit

Instalar el CLI (instalador Inno silencioso) y adjuntar un clone a Revit 2027:

```powershell
pyrevit installs   # ruta del binario pyrevit.exe
pyrevit clones add "C:\Users\aintc\AppData\Local\pyRevit\pyrevit23"
pyrevit attach pyrevit23 DEFAULT 2027
pyrevit attached   # verificar
```

Añadir la extensión y activar el servidor de Routes en
`%APPDATA%\pyRevit\pyRevit_config.ini`:

```ini
[core]
userextensions = ["C:\Users\aintc\OneDrive\Escritorio\Tenorious\revit_mcp\pyrevit_extension"]

[s2k-to-revit-python.extension]
disabled = false

[routes]
enabled = true
host = "127.0.0.1"
port = 48884
core_api = true
```

Reiniciar Revit. En la pestaña pyRevit debe aparecer la extensión
`s2k-to-revit-python`. El servidor Routes queda escuchando en el puerto 48884.

> Nota: la clave de la sección es `routes` y el flag de activación es `enabled`
> (claves confirmadas en `pyRevitLabs.PyRevit.dll`: `routes/enabled/host/port/core_api`).

### 3. Registrar el MCP en opencode

Ya existe `opencode.json` en la raíz del proyecto:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "revit": {
      "type": "local",
      "command": [
        "C:/Users/aintc/OneDrive/Escritorio/Tenorious/revit_mcp/.venv/Scripts/python.exe",
        "C:/Users/aintc/OneDrive/Escritorio/Tenorious/revit_mcp/mcp_server.py"
      ],
      "enabled": true
    }
  }
}
```

Reiniciar opencode para que cargue la configuración.

## Uso

0. **Preparar contenido estructural (una vez).** Las secciones del S2K
   (HSS100x50x4.5, etc.) no existen en Revit por defecto; se crean sobre una
   familia base paramétrica. Esa familia base viene en la librería estándar
   de Revit, que hay que instalar vía **Autodesk Access** (o el instalador
   de Revit → paquete de contenido "Structural Framing / Steel"). Sin esa
   librería, `find_base_families` no encontrará la familia HSS.
1. Abrir Revit 2027 con un proyecto que tenga cargadas las familias
   estructurales de acero (p. ej. columnas y vigas HSS).
2. Desde opencode:

   - `revit_status` → verificar que Revit responde (estado, doc, versiones).
   - `s2k_preview` → resumen del `.s2k` (**usar ruta absoluta**), p. ej.
     `C:\Users\aintc\OneDrive\Escritorio\Tenorious\MN\HUANCALPI - MODELO FINAL v3.s2k`.
   - `find_base_families` → confirma que encontró la familia HSS y la de
     barra redonda en la librería de contenido instalada.
   - `create_sections` → crea los tipos de sección en Revit (uno por
     geometría única: HSS100x50x4.5, HSS500x200x4.5, HSS240x80x2,
     HSS100x100x2.5 y O 5/8). Devuelve un `family_map` listo.
   - `import_s2k` → con ese `family_map`, crea columnas y vigas/arriostramientos
     como `ModelCurve` en el documento activo.

### Modelo de referencia

`MN\HUANCALPI - MODELO FINAL v3.s2k` — 352 nudos, 719 barras, 9 secciones
(malla de cobertura metálica, niveles Z de 0.00 a 11.66 m). Secciones únicas
a crear:

| Tipo | Uso en el modelo |
|---|---|
| HSS100x50x4.5 | Bridas y reticulados (4 secciones S2K) |
| HSS100x100x2.5 | Diagonales y reticulado (2 secciones S2K) |
| HSS500x200x4.5 | Columna (A572) |
| HSS240x80x2 | Correa |
| O 5/8 (Ø15.88 mm) | Tensor (barra redonda) |

## Troubleshooting

- **`All connection attempts failed`** → Revit no está abierto, la extensión no
  se cargó, o `[routes] enabled` está en `false`. Verificar con
  `pyrevit extensions` y `pyrevit attached`.
- **Ruta relativa no resuelta en `s2k_preview`** → el cwd del servidor puede no
  coincidir; pasar siempre la ruta absoluta del `.s2k`.
- **`module 'mcp' has no attribute ...`** → usar `mcp>=1.20.0,<2.0.0`
  (`mcp` 2.0.0 elimina la API de `FastMCP` usada aquí).
- **Cambios en `opencode.json` sin efecto** → opencode no recarga la config en
  caliente; reiniciar opencode.
