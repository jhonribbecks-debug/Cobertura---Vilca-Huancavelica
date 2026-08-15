# -*- coding: utf-8 -*-
"""Servidor MCP para importar modelos SAP2000 (.s2k) a Revit.

Arquitectura:
    Cliente MCP -> este servidor (FastMCP) -> HTTP localhost:48884 -> pyRevit Routes -> Revit API

Requiere:
  - Revit abierto con la extension pyRevit "s2k-to-revit-python" instalada
    y el servidor Routes activado (pyRevit > Settings > Routes).

Uso:
  uv run --with "mcp[cli]" python mcp_server.py                 # stdio
  python mcp_server.py --streamable-http                         # HTTP en :8000
  python mcp_server.py --combined                                # SSE + streamable-http
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import httpx  # noqa: E402
from mcp.server.fastmcp import FastMCP, Context  # noqa: E402

from sap2000gen.s2kreader import parse_s2k  # noqa: E402
import s2k_to_json  # noqa: E402  (mismo directorio)

mcp = FastMCP(
    "Revit S2K MCP",
    host="127.0.0.1",
    port=8000,
    stateless_http=True,
    json_response=True,
)

REVIT_HOST = "127.0.0.1"
REVIT_PORT = 48884
BASE_URL = "http://{}:{}/revit_mcp".format(REVIT_HOST, REVIT_PORT)


# --------------------------------------------------------------------------- #
# Helpers HTTP
# --------------------------------------------------------------------------- #
async def _revit_call(method, endpoint, data=None, timeout=120.0):
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            url = BASE_URL + endpoint
            if method == "GET":
                response = await client.get(url)
            else:
                response = await client.post(url, json=data)
            if response.status_code == 200:
                return response.json()
            return {"error": "Revit respondio {}: {}".format(
                response.status_code, response.text[:500])}
    except httpx.TimeoutException:
        return {"error": "Timeout al llamar a Revit ({}s)".format(timeout)}
    except Exception as e:
        return {"error": "No se pudo conectar con Revit (pyRevit Routes): {}".format(str(e))}


def _parse_family_map(raw):
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _family_map_to_json(family_map):
    return json.dumps(family_map, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# Herramientas MCP
# --------------------------------------------------------------------------- #
@mcp.tool()
async def revit_status() -> str:
    """Comprueba si el puente a Revit (pyRevit Routes) esta activo y responde."""
    data = await _revit_call("GET", "/status/")
    return json.dumps(data, ensure_ascii=False, indent=2)


@mcp.tool()
def s2k_preview(s2k_path: str) -> str:
    """Inspecciona un archivo .s2k de SAP2000 y devuelve estadisticas de geometria.

    No necesita Revit. Muestra nudos, barras, secciones y el mapeo de
    coordenadas (metros).
    """
    if not os.path.exists(s2k_path):
        return "Error: archivo no existe: {}".format(s2k_path)
    data = s2k_to_json.parse_s2k_geometry(s2k_path)
    summary = {
        "source_file": data["source_file"],
        "unit": data["unit"],
        "stats": data["stats"],
        "sections": data["sections"],
        "joints_min": min((j["z"] for j in data["joints"]), default=0.0),
        "joints_max": max((j["z"] for j in data["joints"]), default=0.0),
        "sample_frames": data["frames"][:5],
    }
    return json.dumps(summary, ensure_ascii=False, indent=2)


@mcp.tool()
async def list_structural_families() -> str:
    """Lista los tipos estructurales cargados en el proyecto de Revit (columnas y vigas/arriostramiento)."""
    data = await _revit_call("POST", "/list_structural_families/", data={})
    return json.dumps(data, ensure_ascii=False, indent=2)


@mcp.tool()
async def s2k_family_mapping(s2k_path: str, family_map: str = "") -> str:
    """Muestra que tipo de Revit se usaria para cada seccion SAP2000 del .s2k.

    Args:
        s2k_path: ruta al archivo .s2k
        family_map: JSON opcional '{"SECCION": {"family": "...", "type": "..."}}'
    """
    if not os.path.exists(s2k_path):
        return "Error: archivo no existe: {}".format(s2k_path)
    data = s2k_to_json.parse_s2k_geometry(s2k_path)
    payload = {
        "sections": data["sections"],
        "family_map": _parse_family_map(family_map),
    }
    result = await _revit_call("POST", "/preview_s2k_sections/", data=payload)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def find_base_families(content_base: str = "") -> str:
    """Detecta las familias base parametricas para crear las secciones del .s2k.

    Busca en dos lugares: (1) la libreria de contenido de Revit instalada y
    (2) las familias YA CARGADAS en el proyecto activo (p. ej. "HSS Rectangular",
    "Round Bar", familias de columna HSS). Con las del proyecto no hace falta
    instalar contenido.

    Args:
        content_base: ruta raiz opcional de la libreria de contenido
                      (defecto: C:\\ProgramData\\Autodesk\\RVT 2027\\Libraries)
    """
    data = await _revit_call("POST", "/find_base_families/",
                             data={"content_base": content_base})
    return json.dumps(data, ensure_ascii=False, indent=2)


@mcp.tool()
async def find_project_families() -> str:
    """Devuelve las familias estructurales detectadas en el proyecto de Revit
    (HSS de viga, barra redonda y columna HSS) que se usaran para crear las
    secciones del .s2k sin instalar contenido adicional.
    """
    data = await _revit_call("POST", "/find_project_families/", data={})
    return json.dumps(data, ensure_ascii=False, indent=2)


@mcp.tool()
async def create_sections(
    s2k_path: str,
    hss_family: str = "",
    bar_family: str = "",
    content_base: str = "",
) -> str:
    """Crea en Revit los tipos de seccion estructural definidos por el .s2k.

    Para cada geometria unica del modelo (p. ej. HSS500x200x4.5, O 5/8) crea
    el tipo con las dimensiones del .s2k sobre las familias parametricas ya
    cargadas en el proyecto (HSS rectangular, Round Bar) via EditFamily, y lo
    carga al documento. Devuelve el family_map listo para import_s2k.

    Args:
        s2k_path: ruta al archivo .s2k (absoluta)
        hss_family: ruta opcional al .rfa del tubo rectangular HSS
        bar_family: ruta opcional al .rfa de la barra redonda
        content_base: ruta raiz opcional de la libreria de contenido
    """
    if not os.path.exists(s2k_path):
        return "Error: archivo no existe: {}".format(s2k_path)
    data = s2k_to_json.parse_s2k_geometry(s2k_path)
    payload = {
        "sections": data["sections"],
        "use_project": True,
        "hss_family": hss_family,
        "bar_family": bar_family,
        "content_base": content_base,
    }
    result = await _revit_call("POST", "/ensure_sections/", data=payload)
    result["s2k_stats"] = data["stats"]
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def import_s2k(
    s2k_path: str,
    family_map: str = "",
    level_name: str = "",
    make_columns: bool = True,
    dry_run: bool = False,
) -> str:
    """Importa la geometria de un modelo .s2k de SAP2000 a Revit creando columnas y vigas.

    Args:
        s2k_path: ruta al archivo .s2k (ej. "MN\\HUANCALPI - MODELO FINAL v3.s2k")
        family_map: JSON opcional para mapear secciones S2K a familias de Revit:
                    '{"BRIDA SUPERIOR HSS100x50x4.5": {"family": "...", "type": "..."}}'
                    Si va vacio se autodetectan tipos HSS cargados en el proyecto.
        level_name: nivel de Revit donde apoyar los elementos (vacío = el más bajo)
        make_columns: si True, los miembros verticales se crean como columnas
        dry_run: si True, solo muestra el mapeo de secciones sin crear nada
    """
    if not os.path.exists(s2k_path):
        return "Error: archivo no existe: {}".format(s2k_path)

    data = s2k_to_json.parse_s2k_geometry(s2k_path)
    parsed_map = _parse_family_map(family_map)

    if dry_run:
        payload = {
            "sections": data["sections"],
            "family_map": parsed_map,
        }
        result = await _revit_call("POST", "/preview_s2k_sections/", data=payload)
        result["dry_run"] = True
        result["stats"] = data["stats"]
        return json.dumps(result, ensure_ascii=False, indent=2)

    payload = {
        "unit": data["unit"],
        "joints": data["joints"],
        "frames": data["frames"],
        "sections": data["sections"],
        "family_map": parsed_map,
        "level_name": level_name,
        "make_columns": make_columns,
    }
    result = await _revit_call("POST", "/import_s2k/", data=payload)
    result["stats"] = data["stats"]
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def finish_arc_pipeline(
    dry_run: bool = False,
    planes: str = "",
    skip_save: bool = False,
) -> str:
    """Ejecuta de una sola llamada el flujo completo de finalizacion de la malla
    del tijeral en Revit: simetrizar la malla en X=11.325, alinear los miembros
    extremos radiales y apoyar las correas sobre la brida superior.

    Orquesta las rutas de pyRevit secuencialmente (cada paso una llamada HTTP
    al bridge localhost:48884). Si un paso falla se detiene y reporta.

    Args:
        dry_run: si True, solo muestra el plan de cada paso sin modificar.
        planes: lista JSON opcional de planos Y a procesar, ej. "[0, 5.05]"
                (vacío = todos los planos detectados).
        skip_save: si True, no guarda el documento al final.
    """
    try:
        import json as _json
        parsed_planes = []
        if planes:
            try:
                parsed_planes = _json.loads(planes)
                if not isinstance(parsed_planes, list):
                    parsed_planes = []
            except Exception:
                parsed_planes = []
    except Exception:
        parsed_planes = []

    steps = [
        ("symmetrize_web", {"dry_run": dry_run, "planes": parsed_planes}),
        ("align_extreme_members", {"dry_run": dry_run}),
        ("fix_correas_on_chord", {"dry_run": dry_run}),
    ]
    results = []
    for name, payload in steps:
        result = await _revit_call("POST", "/{}/".format(name), data=payload,
                                   timeout=600.0)
        if result.get("error"):
            results.append({"step": name, "status": "error",
                            "error": result.get("error")})
            return json.dumps({
                "status": "failed",
                "failed_step": name,
                "results": results,
            }, ensure_ascii=False, indent=2)
        summary = {k: result.get(k) for k in (
            "moved", "created", "deleted", "total_purlins", "to_move",
            "skipped", "errors", "plan", "dry_run") if k in result}
        results.append({"step": name, "status": result.get("status"),
                        "summary": summary})
        if result.get("status") != "success":
            return json.dumps({
                "status": "failed",
                "failed_step": name,
                "results": results,
            }, ensure_ascii=False, indent=2)

    if not dry_run and not skip_save:
        save = await _revit_call("POST", "/save_doc/", data={}, timeout=300.0)
        results.append({"step": "save_doc", "status": save.get("status"),
                        "path": save.get("path")})

    return json.dumps({
        "status": "success",
        "dry_run": dry_run,
        "steps": len(results),
        "results": results,
    }, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    transport = "stdio"
    if "--combined" in sys.argv:
        print("Iniciando con SSE (/sse, /messages/) y streamable-http (/mcp) en :8000")
        import uvicorn
        import anyio

        http_app = mcp.streamable_http_app()
        sse_app = mcp.sse_app()
        for route in sse_app.routes:
            http_app.routes.append(route)
        config = uvicorn.Config(http_app, host="127.0.0.1", port=8000, log_level="info")
        anyio.run(uvicorn.Server(config).serve)
        sys.exit(0)
    elif "--streamable-http" in sys.argv or "--http" in sys.argv:
        transport = "streamable-http"
    mcp.run(transport=transport)
