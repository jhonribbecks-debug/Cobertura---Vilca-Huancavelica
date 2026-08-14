"""Extraccion de geometria desde planos DWG/DXF usando ezdxf.

Filosofia:
    - Se leen entidades en el espacio modelo (LINE, LWPOLYLINE, POLYLINE,
      CIRCLE, ARC, TEXT, MTEXT, DIMENSION, INSERT).
    - Los extremos de lineas se agrupan en "nudos" mediante tolerancia.
    - Cada segmento recto se convierte en una barra candidata.
    - La capa (layer) sirve para clasificar el tipo de miembro y, mediante
      un mapa capa -> seccion, asignar la seccion de la plantilla .s2k.

Requisito DWG: se necesita "ODA File Converter" o exportar DXF desde AutoCAD
(File > Save As > DXF). ezdxf solo lee DXF nativamente.
"""

from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional, Tuple

try:
    import ezdxf
    from ezdxf.math import Vec3
    EZDXF_OK = True
except Exception:  # pragma: no cover
    EZDXF_OK = False


def _dxf_path(src: str, converter: str | None = None) -> str:
    """Convierte .dwg a .dxf via AutoCAD COM o ODA File Converter."""
    ext = os.path.splitext(src)[1].lower()
    if ext == ".dxf":
        return src
    if ext != ".dwg":
        raise ValueError(f"Formato no soportado: {ext}")
    if not EZDXF_OK:
        raise RuntimeError("ezdxf no instalado")
    # 1) intentar ODA File Converter
    from ezdxf.addons import odafc
    try:
        tmp_dxf = os.path.join(os.path.dirname(src), os.path.basename(src) + ".dxf")
        odafc.convert(src, tmp_dxf, version="R2018")
        return tmp_dxf
    except Exception:
        pass
    # 2) fallback: AutoCAD COM (SaveAs formato DXF 2024 = 65)
    try:
        import subprocess
        import tempfile
        ps = r'''
$acad = New-Object -ComObject "AutoCAD.Application"
$acad.Visible = $false
try { $acad.GetType().InvokeMember("FileDia", "SetProperty", $null, $acad, 0) } catch {}
$doc = $acad.Documents.Open($env:DWG, $true)
$doc.SaveAs($env:DXF, 65)
try { $doc.Close($false) } catch {}
try { $acad.Quit() } catch {}
'''
        tmp_dxf = os.path.join(tempfile.gettempdir(), "sap2kgen_tmp.dxf")
        env = dict(os.environ, DWG=src, DXF=tmp_dxf)
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       env=env, timeout=120, check=True, capture_output=True)
        if os.path.exists(tmp_dxf):
            return tmp_dxf
    except Exception as exc:
        raise RuntimeError(
            "No se pudo convertir el DWG. Instala 'ODA File Converter' "
            "(https://www.opendesign.com/guestfiles/oda_file_converter) o "
            "guarda el plano como DXF desde AutoCAD (SAVEAS -> DXF). "
            f"Detalle: {exc}"
        )
    raise RuntimeError("No se pudo convertir el DWG a DXF.")


def _shift_to_origin(joints: List[dict], frames: List[dict]) -> None:
    """Desplaza la geometria para que el punto minimo quede en (0,0,0)."""
    if not joints:
        return
    ox = min(j["x"] for j in joints)
    oy = min(j["y"] for j in joints)
    oz = min(j["z"] for j in joints)
    if abs(ox) < 1e-6 and abs(oy) < 1e-6 and abs(oz) < 1e-6:
        return
    for j in joints:
        j["x"] -= ox
        j["y"] -= oy
        j["z"] -= oz


def _segments_from_polyline(pline) -> List[Tuple[Vec3, Vec3, bool]]:
    """Devuelve pares (inicio, fin, es_curvo) para una polilinea/lwpolyline."""
    segs: List[Tuple[Vec3, Vec3, bool]] = []
    pts = list(pline.vertices())
    if len(pts) < 2:
        return segs
    for i in range(len(pts) - 1):
        segs.append((pts[i], pts[i + 1], False))
    if pline.is_closed and len(pts) > 2:
        segs.append((pts[-1], pts[0], False))
    return segs


def _arc_segments(center: Vec3, radius: float, start_a: float, end_a: float,
                  n: int = 8) -> List[Tuple[Vec3, Vec3, bool]]:
    """Aproxima un arco en n segmentos rectos (para arcos estructurales)."""
    import math
    segs = []
    if end_a < start_a:
        end_a += 2 * math.pi
    span = end_a - start_a
    steps = max(2, int(math.ceil(abs(span) / (2 * math.pi) * n)))
    for i in range(steps):
        a1 = start_a + span * i / steps
        a2 = start_a + span * (i + 1) / steps
        p1 = center + Vec3(radius * math.cos(a1), radius * math.sin(a1), 0)
        p2 = center + Vec3(radius * math.cos(a2), radius * math.sin(a2), 0)
        segs.append((p1, p2, False))
    return segs


# Capas tipicas de anotacion que NO son miembros estructurales
ANNOTATION_LAYER_HINTS = (
    "cota", "texto", "membrete", "titulo", "dim", "detalle", "achurado",
    "nota", "acot", "hatch", "pista", "plancha", "vidrio", "fierro",
    "estribo", "corrugada", "corte", "arreglo",
)


def _is_annotation(layer: str) -> bool:
    ll = layer.lower()
    return any(h in ll for h in ANNOTATION_LAYER_HINTS)


def extract_geometry(dwg_or_dxf: str, layer_sections: Optional[Dict[str, str]] = None,
                     tol: float = 0.01,
                     include_layers: Optional[List[str]] = None,
                     skip_layers: Optional[List[str]] = None,
                     shift_to_origin: bool = True,
                     default_section: str = "") -> dict:
    """Extrae nudos/barras de un DWG/DXF.

    layer_sections: mapa de nombre de capa -> seccion (nombre en la plantilla),
        p.ej. {"CORDON": "ARCO", "DIAGONAL": "DIAG100", ...}.
    include_layers: si se indica, SOLO se usan esas capas (whitelist).
    skip_layers: capas a ignorar explicitamente (ademas de las de anotacion).
    shift_to_origin: desplaza el minimo de las coordenadas al origen (0,0,0).
    default_section: seccion a usar para capas sin mapeo (vacia = dejar sin seccion).
    Devuelve un dict JSON-serializable:
        {joints: [{id,x,y,z}], frames: [{i,j,section,layer}], sections_used: [...], source}
    """
    if not EZDXF_OK:
        raise RuntimeError("Falta ezdxf: pip install ezdxf")
    path = _dxf_path(dwg_or_dxf)
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    layer_sections = layer_sections or {}
    skip_layers = set(skip_layers or [])
    include_layers = set(include_layers or [])

    raw_segs: List[Tuple[Vec3, Vec3, str]] = []  # (p1, p2, layer)

    def use_layer(layer: str) -> bool:
        if include_layers and layer not in include_layers:
            return False
        if layer in skip_layers:
            return False
        if _is_annotation(layer):
            return False
        return True

    for e in msp:
        etype = e.dxftype()
        layer = e.dxf.layer
        if not use_layer(layer):
            continue
        try:
            if etype == "LINE":
                raw_segs.append((e.dxf.start, e.dxf.end, layer))
            elif etype == "LWPOLYLINE":
                for s in _segments_from_polyline(e):
                    raw_segs.append((s[0], s[1], layer))
            elif etype == "POLYLINE":
                for s in _segments_from_polyline(e):
                    raw_segs.append((s[0], s[1], layer))
            elif etype == "ARC":
                for s in _arc_segments(e.dxf.center, e.dxf.radius,
                                       e.dxf.start_angle, e.dxf.end_angle):
                    raw_segs.append((s[0], s[1], layer))
            elif etype == "CIRCLE":
                for s in _arc_segments(e.dxf.center, e.dxf.radius, 0.0, 360.0):
                    raw_segs.append((s[0], s[1], layer))
        except Exception:
            continue  # entidades no geometricas / fallos de lectura

    # 1) Agrupar extremos en nudos.
    nodes: List[Vec3] = []

    def find_node(p: Vec3) -> int:
        for i, n in enumerate(nodes):
            if (n - p).magnitude <= tol:
                return i
        nodes.append(p)
        return len(nodes) - 1

    frames: List[dict] = []
    for p1, p2, layer in raw_segs:
        if (p2 - p1).magnitude <= tol:
            continue
        i = find_node(p1)
        j = find_node(p2)
        section = layer_sections.get(layer, "")
        if not section:
            section = default_section
        frames.append({"i": i + 1, "j": j + 1, "layer": layer, "section": section})

    joints = [
        {"id": idx + 1, "x": float(p.x), "y": float(p.y), "z": float(p.z)}
        for idx, p in enumerate(nodes)
    ]
    if shift_to_origin:
        _shift_to_origin(joints, frames)

    used = sorted({f["section"] for f in frames if f["section"]})
    return {"joints": joints, "frames": frames, "sections_used": used,
            "source": os.path.basename(dwg_or_dxf)}
