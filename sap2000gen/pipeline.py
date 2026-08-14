"""Pipeline end-to-end: plano -> geometria -> .s2k.

Flujos:
    1) dwg_to_s2k(dwg, template, out, layer_sections)
         - extrae geometria exacta del DWG/DXF (ezdxf)
    2) plan_to_s2k(image_or_pdf, template, out)
         - IA de vision interpreta el plano (imagen o paginas PDF)
    3) geometry_to_s2k(geom_dict, template, out)
         - alimenta el generador .s2k con cualquier dict de geometria
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

from .model import S2kModel, Joint, Frame, JointLoad
from .s2kreader import parse_s2k
from .s2kwriter import write_s2k
from .dwg import extract_geometry
from .pdf import pdf_to_images

if os.environ.get("SAP2000GEN_SKIP_AI") != "1":
    from .ai.vision import interpret_plan
else:  # pragma: no cover
    interpret_plan = None


def geometry_to_s2k(geom: dict, template_path: str, output_path: str) -> dict:
    """Convierte un dict de geometria en un .s2k listo para importar."""
    model = parse_s2k(template_path)

    for j in geom.get("joints", []):
        restr = None
        # buscar restraints en "supports"
        for s in geom.get("supports", []):
            if int(s["joint"]) == int(j["id"]):
                restr = s.get("restraints")
                break
        model.add_joint(Joint(id=int(j["id"]), x=float(j.get("x", 0)),
                              y=float(j.get("y", 0)), z=float(j.get("z", 0)),
                              restraints=restr))

    for n, f in enumerate(geom.get("frames", []), start=1):
        rel = f.get("releases")
        if rel is not None:
            rel = [bool(x) for x in rel]
        model.add_frame(Frame(id=n, joint_i=int(f["i"]), joint_j=int(f["j"]),
                              section=f.get("section", "ARCO"),
                              releases=rel,
                              comp_only=bool(f.get("comp_only", False))))

    for ld in geom.get("joint_loads", []):
        model.joint_loads.append(
            JointLoad(joint=int(ld["joint"]), pattern=ld.get("pattern", "CM"),
                      f1=float(ld.get("f1", 0)), f2=float(ld.get("f2", 0)),
                      f3=float(ld.get("f3", 0)), m1=float(ld.get("m1", 0)),
                      m2=float(ld.get("m2", 0)), m3=float(ld.get("m3", 0))))

    write_s2k(model, output_path)
    return {"output": output_path, "joints": len(model.joints),
            "frames": len(model.frames), "source": geom.get("source", "")}


def dwg_to_s2k(dwg_path: str, template_path: str, output_path: str,
               layer_sections: Optional[Dict[str, str]] = None,
               include_layers: Optional[List[str]] = None,
               skip_layers: Optional[List[str]] = None,
               default_section: str = "COST") -> dict:
    """Extrae geometria del DWG/DXF y genera el .s2k."""
    geom = extract_geometry(dwg_path, layer_sections=layer_sections,
                            include_layers=include_layers, skip_layers=skip_layers,
                            default_section=default_section)
    return geometry_to_s2k(geom, template_path, output_path)


def plan_to_s2k(plan_path: str, template_path: str, output_path: str,
                ai_context: Optional[str] = None) -> dict:
    """Usa IA de vision sobre una imagen/PDF y genera el .s2k."""
    if interpret_plan is None:
        raise RuntimeError("Modulo de IA desactivado o sin dependencias.")

    images: List[str] = []
    if plan_path.lower().endswith(".pdf"):
        images = pdf_to_images(plan_path)
    else:
        images = [plan_path]

    for img in images:
        try:
            geom = interpret_plan(img, extra_context=ai_context)
            geom["source"] = os.path.basename(plan_path)
            return geometry_to_s2k(geom, template_path, output_path)
        except Exception as exc:
            last = exc
    raise RuntimeError(f"No se pudo interpretar el plano: {last}")
