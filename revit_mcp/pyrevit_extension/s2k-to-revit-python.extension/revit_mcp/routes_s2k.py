# -*- coding: UTF-8 -*-
"""Rutas de importacion de modelos SAP2000 (.s2k) a Revit."""

from pyrevit import routes, revit, DB
import json
import logging
import os
import tempfile

from revit_mcp.utils import (
    normalize_string,
    element_id_value,
    resolve_symbol,
    find_level,
    lowest_level,
    section_dims,
    get_element_name,
    log_route_error,
    _norm,
)

logger = logging.getLogger(__name__)

FT_PER_M = 1.0 / 0.3048
TOL = 0.05  # pies (~15 mm)

PROG_LOG = r"C:\Users\aintc\AppData\Local\Temp\opencode\import_progress.log"

# Nombres de familias que son montantes/mullion de muro cortina y que NO deben
# usarse como respaldo para columnas estructurales (causa el dialogo
# "No es posible colocar la familia de montantes de sistema en este muro cortina").
SKIP_FALLBACK_HINTS = ("montante", "mullion", "rejilla", "grid")


class _AutoAcceptFailures(DB.IFailuresPreprocessor):
    """Preprocesador que borra avisos y continua con errores automaticamente.

    Evita que Revit muestre dialogos modales durante el import (p. ej.
    "La base del pilar debe estar por debajo de su parte superior") que
    bloquean/revierte las transacciones cuando el usuario pulsa Cancelar.
    """

    def PreprocessFailures(self, failuresAccessor):
        try:
            failuresAccessor.DeleteAllWarnings()
        except Exception:
            pass
        return DB.FailureProcessingResult.ProceedWithCommit


def _new_txn(doc, name):
    t = DB.Transaction(doc, name)
    try:
        opts = doc.GetFailureHandlingOptions()
        opts.SetFailuresPreprocessor(_AutoAcceptFailures())
        opts.SetClearAfterRollback(True)
        t.SetFailureHandlingOptions(opts)
    except Exception:
        pass
    return t


def _mark(msg):
    try:
        with open(PROG_LOG, "a") as fh:
            fh.write(u"[MARK] {}\n".format(msg))
    except Exception:
        pass


def _as_xyz(joint, unit_factor):
    return DB.XYZ(
        float(joint["x"]) * unit_factor,
        float(joint["y"]) * unit_factor,
        float(joint["z"]) * unit_factor,
    )


def _parse_body(request):
    data = request.data
    if isinstance(data, str):
        data = json.loads(data)
    return data if isinstance(data, dict) else {}


def _find_symbol_from_map(doc, family_map, section, category):
    entry = family_map.get(section)
    if not entry:
        return None
    if isinstance(entry, dict) and ("framing" in entry or "column" in entry):
        key = "column" \
            if int(category) == int(DB.BuiltInCategory.OST_StructuralColumns) \
            else "framing"
        sub = entry.get(key) or {}
        family_name = sub.get("family")
        type_name = sub.get("type")
    else:
        family_name = entry.get("family")
        type_name = entry.get("type")
    for sym in DB.FilteredElementCollector(doc)\
                  .OfClass(DB.FamilySymbol).ToElements():
        fam = _norm(get_element_name(sym.Family))
        if family_name and fam != _norm(family_name):
            continue
        if type_name and _norm(get_element_name(sym)) != _norm(type_name):
            continue
        return sym
    return None


def register_s2k_routes(api):
    @api.route("/import_s2k/", methods=["POST"])
    def import_s2k(doc, request):
        """Crea elementos estructurales en Revit a partir de geometria .s2k.

        Body esperado (coordenadas en metros si unit='m'):
        {
          "unit": "m",
          "joints": [{"id":1,"x":0,"y":0,"z":6.0}, ...],
          "frames": [{"id":1,"i":1,"j":2,"section":"BRIDA SUPERIOR HSS100x50x4.5"}, ...],
          "sections": {"<name>": {"material":"A36","shape":"Box/Tube","t3":0.1,"t2":0.05,...}},
          "family_map": {"<section>": {"family":"...","type":"..."}},   # opcional
          "level_name": "Level 1",                                       # opcional
          "make_columns": true                                           # opcional
        }
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)

            data = _parse_body(request)
            joints = data.get("joints") or []
            frames = data.get("frames") or []
            family_map = data.get("family_map") or {}
            make_columns = bool(data.get("make_columns", True))
            unit = data.get("unit", "m")
            unit_factor = FT_PER_M if unit == "m" else 1.0

            if not joints:
                return routes.make_response(
                    data={"error": "No joints in payload"}, status=400)
            if not frames:
                return routes.make_response(
                    data={"error": "No frames in payload"}, status=400)

            joint_xyz = {j["id"]: _as_xyz(j, unit_factor) for j in joints}

            level = None
            if data.get("level_name"):
                level = find_level(doc, data["level_name"])
                if not level:
                    return routes.make_response(
                        data={"error": "Level not found: " + str(data["level_name"])},
                        status=404)
            if level is None:
                level = lowest_level(doc)
            if level is None:
                return routes.make_response(
                    data={"error": "No levels found in the document"}, status=404)

            column_cat = DB.BuiltInCategory.OST_StructuralColumns
            framing_cat = DB.BuiltInCategory.OST_StructuralFraming

            column_syms = DB.FilteredElementCollector(doc)\
                           .OfCategory(column_cat)\
                           .WhereElementIsElementType()\
                           .ToElements()
            framing_syms = DB.FilteredElementCollector(doc)\
                            .OfCategory(framing_cat)\
                            .WhereElementIsElementType()\
                            .ToElements()

            if not column_syms and not framing_syms:
                return routes.make_response(
                    data={
                        "error": "No structural families loaded (columns/framing). "
                                 "Carga familias estructurales en el proyecto o usa family_map.",
                    },
                    status=404,
                )

            def _good_fallback(syms):
                for s in syms:
                    fam = _norm(get_element_name(s.Family))
                    if any(hint in fam for hint in SKIP_FALLBACK_HINTS):
                        continue
                    return s
                return syms[0] if syms else None

            column_fallback = _good_fallback(column_syms)
            framing_fallback = _good_fallback(framing_syms)

            symbol_cache = {}
            resolved_debug = {}
            map_debug = {}

            def symbol_for(section, category, fallback):
                key = (section, int(category))
                if key in symbol_cache:
                    return symbol_cache[key]
                try:
                    if section not in map_debug:
                        map_debug[section] = {
                            "in_map": section in family_map,
                            "map_keys": list(family_map.keys())[:20],
                            "map_entry": family_map.get(section),
                        }
                except Exception:
                    pass
                sym = _find_symbol_from_map(doc, family_map, section, category)
                if sym is None:
                    sym = resolve_symbol(doc, section, category, None)
                if sym is None:
                    other_cat = framing_cat \
                        if int(category) == int(column_cat) else column_cat
                    sym = _find_symbol_from_map(doc, family_map, section, other_cat) \
                        or resolve_symbol(doc, section, other_cat, None)
                if sym is None:
                    sym = fallback
                symbol_cache[key] = sym
                try:
                    if sym is not None:
                        resolved_debug[key] = u"{} / {}".format(
                            normalize_string(get_element_name(sym.Family)),
                            normalize_string(get_element_name(sym)))
                except Exception:
                    pass
                return sym

            chunk_size = int(data.get("chunk_size") or 100)

            created = 0
            skipped = 0
            errors = []
            per_category = {}

            try:
                if data.get("clear_existing"):
                    _mark(u"start clear_existing")
                    t = _new_txn(doc, "Clear S2K")
                    t.Start()
                    ids = []
                    for cat in (column_cat, framing_cat):
                        ids.extend([
                            e.Id for e in DB.FilteredElementCollector(doc)
                                    .OfCategory(cat)
                                    .WhereElementIsNotElementType()
                                    .ToElements()
                        ])
                    for eid in ids:
                        doc.Delete(eid)
                    t.Commit()
                    _mark(u"end clear_existing n={}".format(len(ids)))

                t = _new_txn(doc, "Import S2K chunk")
                t.Start()
                created_in_txn = 0
                for i, fr in enumerate(frames):
                    try:
                        prog = open(PROG_LOG, "a")
                        prog.write(u"{} {} -> {}\n".format(
                            i, fr.get("id"), fr.get("section")))
                        prog.close()
                    except Exception:
                        pass
                    p1 = joint_xyz.get(fr.get("i"))
                    p2 = joint_xyz.get(fr.get("j"))
                    if p1 is None or p2 is None:
                        skipped += 1
                        continue

                    dx = abs(p1.X - p2.X)
                    dy = abs(p1.Y - p2.Y)
                    dz = abs(p1.Z - p2.Z)
                    is_column = make_columns and dx < TOL and dy < TOL and dz > TOL

                    if is_column and p1.Z > p2.Z:
                        p1, p2 = p2, p1

                    section = fr.get("section") or ""
                    if is_column:
                        sym = symbol_for(section, column_cat, column_fallback)
                        structural_type = DB.Structure.StructuralType.Column
                    else:
                        sym = symbol_for(section, framing_cat, framing_fallback)
                        structural_type = DB.Structure.StructuralType.Beam \
                            if dz < TOL else DB.Structure.StructuralType.Brace

                    if sym is None:
                        skipped += 1
                        continue

                    try:
                        if not sym.IsActive:
                            sym.Activate()
                        line = DB.Line.CreateBound(p1, p2)
                        instance = doc.Create.NewFamilyInstance(
                            line, sym, level, structural_type)
                    except Exception as e:
                        errors.append(u"frame {}: {}".format(fr.get("id"), str(e)))
                        continue

                    try:
                        mark = instance.LookupParameter("Mark")
                        if mark and not mark.IsReadOnly:
                            mark.Set(str(fr.get("id")))
                        if section:
                            comments = instance.LookupParameter("Comments")
                            if comments and not comments.IsReadOnly:
                                comments.Set(u"S2K {}".format(section))
                    except Exception:
                        pass

                    created += 1
                    created_in_txn += 1
                    cat_label = "columns" if is_column else "framing"
                    per_category[cat_label] = per_category.get(cat_label, 0) + 1

                    if created_in_txn >= chunk_size:
                        t.Commit()
                        _mark(u"chunk committed n={}".format(created))
                        t = _new_txn(doc, "Import S2K chunk")
                        t.Start()
                        created_in_txn = 0

                if t.HasStarted() and not t.HasEnded():
                    t.Commit()
                _mark(u"import committed total={}".format(created))
            except Exception:
                try:
                    if t is not None and t.HasStarted() and not t.HasEnded():
                        t.RollBack()
                except Exception:
                    pass
                raise

            response_data = {
                "status": "success",
                "created": created,
                "skipped": skipped,
                "per_category": per_category,
                "errors": errors[:50],
                "error_count": len(errors),
                "debug_symbols": dict(list(resolved_debug.items())[:30]),
                "debug_map": dict(list(map_debug.items())[:10]),
                "level": normalize_string(level.Name),
                "import_id": created,
            }
            return routes.make_response(data=response_data)

        except Exception as e:
            log_route_error("import_s2k", e)
            logger.error("import_s2k failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/preview_s2k_sections/", methods=["POST"])
    def preview_s2k_sections(doc, request):
        """Resuelve que tipo de Revit se usaria para cada seccion SAP2000."""
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            data = _parse_body(request)
            sections = data.get("sections") or {}
            family_map = data.get("family_map") or {}

            column_cat = DB.BuiltInCategory.OST_StructuralColumns
            framing_cat = DB.BuiltInCategory.OST_StructuralFraming
            column_syms = DB.FilteredElementCollector(doc)\
                           .OfCategory(column_cat)\
                           .WhereElementIsElementType()\
                           .ToElements()
            framing_syms = DB.FilteredElementCollector(doc)\
                            .OfCategory(framing_cat)\
                            .WhereElementIsElementType()\
                            .ToElements()

            mapping = {}
            failures = []
            for i, name in enumerate(sections):
                try:
                    col = _find_symbol_from_map(doc, family_map, name, column_cat) \
                          or resolve_symbol(doc, name, column_cat, None)
                    bm = _find_symbol_from_map(doc, family_map, name, framing_cat) \
                         or resolve_symbol(doc, name, framing_cat, None)
                    mapping[name] = {
                        "column": {
                            "family": normalize_string(get_element_name(col.Family)),
                            "type": normalize_string(get_element_name(col)),
                        } if col else None,
                        "framing": {
                            "family": normalize_string(get_element_name(bm.Family)),
                            "type": normalize_string(get_element_name(bm)),
                        } if bm else None,
                        "dims": section_dims(name),
                    }
                except Exception as e:
                    failures.append(u"section[{}] {}: {}".format(i, name, str(e)))

            return routes.make_response(data={
                "status": "success",
                "mapping": mapping,
                "echo_family_map": family_map,
                "section_failures": failures,
                "available_columns": len(column_syms),
                "available_framing": len(framing_syms),
            })
        except Exception as e:
            log_route_error("preview_s2k_sections", e)
            logger.error("preview_s2k_sections failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/open_document/", methods=["POST"])
    def open_document(uiapp, request):
        """Abre un modelo de Revit y lo activa.

        Body: {"path": "C:\\...\\modelo.rvt"}
        """
        try:
            data = request.data
            if isinstance(data, str):
                data = json.loads(data)
            data = data if isinstance(data, dict) else {}
            path = data.get("path")
            if not path:
                return routes.make_response(
                    data={"error": "path required"}, status=400)
            if not os.path.exists(path):
                return routes.make_response(
                    data={"error": "file not found: {}".format(path)}, status=404)
            # Usar el UIApplication real del contexto pyRevit (siempre disponible)
            if not uiapp:
                return routes.make_response(
                    data={"error": "no Application available"}, status=500)
            try:
                out = uiapp.OpenAndActivateDocument(path)
            except Exception as e1:
                return routes.make_response(data={"error": str(e1)}, status=500)
            title = None
            try:
                title = normalize_string(out.Title)
            except Exception:
                pass
            return routes.make_response(data={
                "status": "success",
                "document": title,
                "path": path,
            })
        except Exception as e:
            log_route_error("open_document", e)
            return routes.make_response(data={"error": str(e)}, status=500)

    logger.info("S2K routes registered successfully")
