# -*- coding: utf-8 -*-
"""Nodo Python de Dynamo para importar un modelo .s2k a Revit.

VINCULACION CON DYNAMO
======================
1. Genera el JSON desde un .s2k (fuera de Revit):
       python revit_mcp/s2k_to_json.py "MN\\HUANCALPI - MODELO FINAL v3.s2k" -o modelo_revit.json

2. En Revit abre Dynamo, crea un nodo "Python Script" y pega este codigo.

3. Entradas del nodo (definir "Inputs" al fondo del archivo):
   IN[0] -> str : ruta absoluta al JSON (ej. r"C:\...\modelo_revit.json")
   IN[1] -> str : nombre de nivel de Revit (opcional, "" = el mas bajo)
   IN[2] -> str : JSON con family_map opcional
                  '{"BRIDA SUPERIOR HSS100x50x4.5": {"family": "...", "type": "..."}}'
                  ("" = autodeteccion HSS)

4. Ejecuta el grafo. Crea Columnas (elementos verticales) y
   Vigas/Arriostramientos (el resto) dentro de una unica transaccion.

Notas:
- Este script funciona en CPython 3.x (Dynamo 2027 por defecto) y en IronPython 2.7.
- Las coordenadas del .s2k estan en metros; se convierten a pies (unidades Revit).
- Necesita familias estructurales cargadas en el proyecto (columnas y vigas).
"""

import json
import re
import sys

try:
    import clr  # IronPython
    clr.AddReference("RevitAPI")
    from Autodesk.Revit import DB
    from Autodesk.Revit.DB import Structure
except ImportError:
    import Autodesk.Revit.DB as DB
    from Autodesk.Revit.DB import Structure

from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

# --- Entradas ---------------------------------------------------------------
json_path = IN[0]  # noqa: F821  (variable de Dynamo)
level_name = IN[1] if len(IN) > 1 and IN[1] else ""  # noqa: F821
family_map_raw = IN[2] if len(IN) > 2 and IN[2] else ""  # noqa: F821

doc = DocumentManager.Instance.CurrentDBDocument
FT_PER_M = 1.0 / 0.3048
TOL = 0.05

family_map = {}
if family_map_raw:
    family_map = json.loads(family_map_raw) if isinstance(family_map_raw, str) else family_map_raw


def norm(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def section_dims(name):
    m = re.search(r"hss\s*(\d+)\s*x\s*(\d+)\s*(?:x\s*([\d.]+))?", (name or "").lower())
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), float(m.group(3)) if m.group(3) else None)


def collect_symbols(cat):
    coll = DB.FilteredElementCollector(doc).OfCategory(cat).WhereElementIsElementType().ToElements()
    return [s for s in coll if s.Category and s.Category.Id.IntegerValue == int(cat)]


def resolve_symbol(section_name, cat):
    for sym in collect_symbols(cat):
        fam = norm(getattr(sym.Family, "Name", ""))
        typ = norm(getattr(sym, "Name", ""))
        if fam + typ == norm(section_name):
            return sym
    dims = section_dims(section_name)
    if dims:
        best, best_score = None, -1
        for sym in collect_symbols(cat):
            hay = norm(getattr(sym.Family, "Name", "") + " " + getattr(sym, "Name", ""))
            if "hss" not in hay and "rectang" not in hay:
                continue
            score = sum(1 for d in dims if d is not None and str(d).replace(".0", "") in hay)
            if score > best_score:
                best, best_score = sym, score
        if best and best_score > 0:
            return best
    syms = collect_symbols(cat)
    return syms[0] if syms else None


def main():
    with open(json_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    joints = {j["id"]: DB.XYZ(j["x"] * FT_PER_M, j["y"] * FT_PER_M, j["z"] * FT_PER_M)
              for j in data.get("joints", [])}
    frames = data.get("frames", [])

    if level_name:
        level = next((lvl for lvl in
                      DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Levels)
                        .WhereElementIsNotElementType().ToElements()
                      if getattr(lvl, "Name", "") == level_name), None)
        if not level:
            raise ValueError("Level not found: " + level_name)
    else:
        levels = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Levels) \
                  .WhereElementIsNotElementType().ToElements()
        level = min(levels, key=lambda lvl: lvl.Elevation)

    col_cat = DB.BuiltInCategory.OST_StructuralColumns
    bm_cat = DB.BuiltInCategory.OST_StructuralFraming

    created = 0
    skipped = 0
    errors = []

    TransactionManager.Instance.EnsureInTransaction(doc)
    try:
        for fr in frames:
            p1 = joints.get(fr.get("i"))
            p2 = joints.get(fr.get("j"))
            if p1 is None or p2 is None:
                skipped += 1
                continue

            is_column = abs(p1.X - p2.X) < TOL and abs(p1.Y - p2.Y) < TOL \
                and abs(p1.Z - p2.Z) > TOL
            section = fr.get("section") or ""

            sym = None
            entry = family_map.get(section) if isinstance(family_map, dict) else None
            if entry:
                for s in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol).ToElements():
                    if norm(getattr(s.Family, "Name", "")) == norm(entry.get("family")) and \
                       (not entry.get("type") or norm(getattr(s, "Name", "")) == norm(entry.get("type"))):
                        sym = s
                        break
            if sym is None:
                sym = resolve_symbol(section, col_cat if is_column else bm_cat)

            if sym is None:
                skipped += 1
                continue

            try:
                if not sym.IsActive:
                    sym.Activate()
                if is_column:
                    inst = doc.Create.NewFamilyInstance(p1, sym, level,
                                                        Structure.StructuralType.Column)
                else:
                    line = DB.Line.CreateBound(p1, p2)
                    s_type = Structure.StructuralType.Beam \
                        if abs(p1.Z - p2.Z) < TOL else Structure.StructuralType.Brace
                    inst = doc.Create.NewFamilyInstance(line, sym, level, s_type)
                created += 1
            except Exception as e:
                errors.append(u"frame {}: {}".format(fr.get("id"), str(e)))
    finally:
        TransactionManager.Instance.TransactionTaskDone()

    OUT = {  # noqa: F821
        "created": created,
        "skipped": skipped,
        "errors": errors[:50],
    }


main()
