# -*- coding: utf-8 -*-
"""Convierte un modelo .s2k de SAP2000 a un JSON de geometria estructural.

Solo extrae lo que Revit necesita: nudos, barras y secciones (HSS/tubos).
Las coordenadas se mantienen en metros (unidades de los .s2k de SAP2000);
la conversion a pies la hace la extension de pyRevit dentro de Revit.

Uso:
    python s2k_to_json.py "MN\\HUANCALPI - MODELO FINAL v3.s2k" -o modelo.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sap2000gen.model import S2kModel  # noqa: E402

_TABLE_RE = re.compile(r'^\s*TABLE:\s*"?([^"]+)"?\s*$')
_FIELD_RE = re.compile(r'([A-Za-z0-9_.]+)\s*=\s*("([^"]*)"|([^\s]+))')

GEOM_TABLES = {
    "JOINT COORDINATES",
    "CONNECTIVITY - FRAME",
    "FRAME SECTION ASSIGNMENTS",
    "FRAME SECTION PROPERTIES 01 - GENERAL",
}


def parse_fields(line: str) -> dict:
    """Extrae pares clave=valor de una fila, soportando valores entre comillas."""
    fields = {}
    for m in _FIELD_RE.finditer(line):
        key = m.group(1)
        value = m.group(3) if m.group(3) is not None else m.group(4)
        fields[key] = value
    return fields


def parse_s2k_geometry(path: str) -> dict:
    """Lee un .s2k y devuelve {joints, frames, sections, source_file, unit}."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()

    joints: list[dict] = []
    frames: list[dict] = []
    sections: dict[str, dict] = {}
    section_assign: dict[int, str] = {}

    current: str | None = None
    for ln in lines:
        stripped = ln.strip()
        if not stripped:
            continue
        m = _TABLE_RE.match(stripped)
        if m:
            current = m.group(1).strip()
            continue
        if current is None or current not in GEOM_TABLES:
            continue

        f = parse_fields(ln)
        if current == "JOINT COORDINATES":
            if "Joint" not in f:
                continue
            joints.append({
                "id": int(f["Joint"]),
                "x": float(f.get("XorR", 0.0)),
                "y": float(f.get("Y", 0.0)),
                "z": float(f.get("Z", 0.0)),
            })
        elif current == "CONNECTIVITY - FRAME":
            if "Frame" not in f:
                continue
            frames.append({
                "id": int(f["Frame"]),
                "i": int(f.get("JointI", 0)),
                "j": int(f.get("JointJ", 0)),
            })
        elif current == "FRAME SECTION ASSIGNMENTS":
            if "Frame" not in f:
                continue
            section_assign[int(f["Frame"])] = f.get("AnalSect", "")
        elif current == "FRAME SECTION PROPERTIES 01 - GENERAL":
            name = f.get("SectionName", "")
            if not name:
                continue
            sec = {
                "material": f.get("Material", "A36"),
                "shape": f.get("Shape", "General"),
            }
            for k in ("t3", "t2", "tf", "tw", "r"):
                if k in f:
                    try:
                        sec[k] = float(f[k])
                    except ValueError:
                        pass
            sections[name] = sec

    for fr in frames:
        fr["section"] = section_assign.get(fr["id"], "")

    joints.sort(key=lambda j: j["id"])
    frames.sort(key=lambda frm: frm["id"])

    return {
        "source_file": os.path.basename(path),
        "unit": "m",
        "joints": joints,
        "frames": frames,
        "sections": sections,
        "stats": {
            "joints": len(joints),
            "frames": len(frames),
            "sections": len(sections),
        },
    }


def to_s2k_model(path: str) -> S2kModel:
    """Reusa el modelo de sap2000gen (para tablas de definicion) + geometria."""
    from sap2000gen.s2kreader import parse_s2k

    model = parse_s2k(path)
    return model


def main() -> None:
    p = argparse.ArgumentParser(prog="s2k_to_json",
                                description="Convierte .s2k de SAP2000 a JSON de geometria")
    p.add_argument("input", help="Ruta del .s2k")
    p.add_argument("-o", "--output", default="modelo_revit.json")
    args = p.parse_args()

    data = parse_s2k_geometry(args.input)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    print("OK: {joints} nudos, {frames} barras, {sections} secciones".format(**data["stats"]))
    print("Archivo generado: {}".format(args.output))


if __name__ == "__main__":
    main()
