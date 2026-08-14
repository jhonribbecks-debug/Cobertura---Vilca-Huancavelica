"""Escritor de .s2k: regenera la geometria sobre la plantilla base.

Formato de linea en tablas .s2k:
    <spaces>Campo1=Valor1   Campo2=Valor2   ...
Los nombres de tabla van como:  TABLE:  "NOMBRE"
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

from .model import S2kModel
from .s2kreader import GEOM_TABLES

F6 = "{:.5f}"


def _row(**fields) -> str:
    parts = []
    for k, v in fields.items():
        if v is None:
            continue
        parts.append(f"{k}={v}")
    return "   " + "   ".join(parts)


def _joints_rows(model: S2kModel) -> List[str]:
    return [
        _row(Joint=j.id, CoordSys="GLOBAL", CoordType="Cartesian",
             XorR=F6.format(j.x), Y=F6.format(j.y), Z=F6.format(j.z))
        for j in sorted(model.joints, key=lambda j: j.id)
    ]


def _connectivity_rows(model: S2kModel) -> List[str]:
    return [
        _row(Frame=f.id, JointI=f.joint_i, JointJ=f.joint_j, IsCurved="No")
        for f in sorted(model.frames, key=lambda f: f.id)
    ]


def _restraint_rows(model: S2kModel) -> List[str]:
    rows = []
    for j in sorted(model.joints, key=lambda j: j.id):
        if not j.restraints:
            continue
        r = j.restraints
        rows.append(
            _row(Joint=j.id, U1="Yes" if r[0] else "No", U2="Yes" if r[1] else "No",
                 U3="Yes" if r[2] else "No", R1="Yes" if r[3] else "No",
                 R2="Yes" if r[4] else "No", R3="Yes" if r[5] else "No")
        )
    return rows


def _frame_section_rows(model: S2kModel) -> List[str]:
    return [
        _row(Frame=f.id, SectionType="General", AutoSelect="N.A.",
             AnalSect=f.section, MatProp="Default")
        for f in sorted(model.frames, key=lambda f: f.id)
    ]


def _release_rows(model: S2kModel) -> List[str]:
    rows = []
    for f in sorted(model.frames, key=lambda f: f.id):
        if not f.releases:
            continue
        r = f.releases
        rows.append(
            _row(Frame=f.id,
                 PI="Yes" if r[0] else "No", V2I="Yes" if r[1] else "No",
                 V3I="Yes" if r[2] else "No", TI="Yes" if r[3] else "No",
                 M2I="Yes" if r[4] else "No", M3I="Yes" if r[5] else "No",
                 PJ="Yes" if r[6] else "No", V2J="Yes" if r[7] else "No",
                 V3J="Yes" if r[8] else "No", TJ="Yes" if r[9] else "No",
                 M2J="Yes" if r[10] else "No", M3J="Yes" if r[11] else "No")
        )
    return rows


def _comp_limit_rows(model: S2kModel) -> List[str]:
    rows = []
    for f in sorted(model.frames, key=lambda f: f.id):
        if not f.comp_only:
            continue
        rows.append(_row(Frame=f.id, TensLimit="No", CompLimit="Yes", CompLimitVal=0))
    return rows


def _joint_load_rows(model: S2kModel) -> List[str]:
    rows = []
    for ld in model.joint_loads:
        rows.append(
            _row(Joint=ld.joint, LoadPat=ld.pattern, CoordSys="GLOBAL",
                 F1=F6.format(ld.f1), F2=F6.format(ld.f2), F3=F6.format(ld.f3),
                 M1=F6.format(ld.m1), M2=F6.format(ld.m2), M3=F6.format(ld.m3))
        )
    return rows


def _frame_load_rows(model: S2kModel) -> List[str]:
    rows = []
    for ld in model.frame_loads:
        rows.append(
            _row(Frame=ld.frame, LoadPat=ld.pattern,
                 Type="Force", Dir=ld.direction, CoordSys=ld.coord_sys,
                 Dist1=F6.format(ld.dist1), Dist2=F6.format(ld.dist2),
                 Val1=F6.format(ld.val1), Val2=F6.format(ld.val2))
        )
    return rows


# nombre de tabla -> (generador de lineas, "regenerar" bool)
_GEOM_GENERATORS = {
    "JOINT COORDINATES": _joints_rows,
    "CONNECTIVITY - FRAME": _connectivity_rows,
    "JOINT RESTRAINT ASSIGNMENTS": _restraint_rows,
    "FRAME SECTION ASSIGNMENTS": _frame_section_rows,
    "FRAME RELEASE ASSIGNMENTS 1 - GENERAL": _release_rows,
    "FRAME TENSION AND COMPRESSION LIMITS": _comp_limit_rows,
    "JOINT LOADS - FORCE": _joint_load_rows,
    "FRAME LOADS - DISTRIBUTED": _frame_load_rows,
}


def write_s2k(model: S2kModel, output_path: str) -> None:
    """Escribe el .s2k nuevo. La geometria se regenera; el resto se conserva."""
    out: List[str] = []
    emitted_geom: set = set()

    for table_name, rows in model.passthrough:
        if table_name in GEOM_TABLES and model.frames:
            gen = _GEOM_GENERATORS[table_name]
            new_rows = gen(model)
            if new_rows:
                out.append(f'TABLE:  "{table_name}"')
                out.extend(new_rows)
            emitted_geom.add(table_name)
        elif table_name in GEOM_TABLES:
            # sin geometria nueva: conservar la original de la plantilla
            out.append(f'TABLE:  "{table_name}"')
            out.extend(rows)
        elif table_name == "FRAME SECTION PROPERTIES 01 - GENERAL" and model.section_rows:
            out.append(f'TABLE:  "{table_name}"')
            for name in model.section_rows:
                out.append(model.section_rows[name])
        elif table_name.startswith("MATERIAL PROPERTIES") and table_name in model.extra_material_rows:
            out.append(f'TABLE:  "{table_name}"')
            out.extend(rows)
            out.extend(model.extra_material_rows[table_name])
        else:
            out.append(f'TABLE:  "{table_name}"')
            out.extend(rows)

    # Tablas de geometria que no existian en la plantilla (solo si hay geometria nueva)
    if model.frames:
        for table_name, gen in _GEOM_GENERATORS.items():
            if table_name in emitted_geom:
                continue
            new_rows = gen(model)
            if new_rows:
                out.append(f'TABLE:  "{table_name}"')
                out.extend(new_rows)

    text = "\n".join(out)
    # Separar tablas con una linea de un espacio (formato exacto del .s2k)
    text = text.replace('TABLE:  "', ' \nTABLE:  "')
    if text.startswith(" \n"):
        text = text[2:]
    # Marcador de fin de archivo
    text += "\n \nEND TABLE DATA\n"

    with open(output_path, "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write(text)
