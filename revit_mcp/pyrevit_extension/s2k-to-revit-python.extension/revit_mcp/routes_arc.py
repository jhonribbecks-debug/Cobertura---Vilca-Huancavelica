# -*- coding: UTF-8 -*-
"""Rutas para convertir las bridas del arco (segmentos lineales) en curvas reales.

Crea vigas estructurales curvas (DB.Arc) sobre la familia HSS parametrica y
borra los elementos frame lineales que aproximaban la curva en SAP2000.
"""

from pyrevit import routes, DB, revit
import json
import logging
import math

from revit_mcp.utils import (
    get_element_name,
    find_level,
    lowest_level,
    log_route_error,
    element_id_value,
    _norm,
)

from revit_mcp.routes_s2k import _new_txn, _AutoAcceptFailures, _mark
from Autodesk.Revit.DB.Structure import StructuralFramingUtils as _SFU

logger = logging.getLogger(__name__)

FT_PER_M = 1.0 / 0.3048

F_HSS = u"HSS-Secci\u00f3n estructural hueca"


def _xyz(xyz_m):
    return DB.XYZ(
        float(xyz_m[0]) * FT_PER_M,
        float(xyz_m[1]) * FT_PER_M,
        float(xyz_m[2]) * FT_PER_M,
    )


def _resolve_symbol(doc, family_name, type_name):
    fam = _norm(family_name)
    typ = _norm(type_name)
    for sym in DB.FilteredElementCollector(doc)\
                  .OfClass(DB.FamilySymbol).ToElements():
        if fam and _norm(get_element_name(sym.Family)) != fam:
            continue
        if typ and _norm(get_element_name(sym)) != typ:
            continue
        return sym
    return None


def _make_arc(rec):
    """Crea DB.Arc a partir de start/mid/end en metros."""
    start = _xyz(rec["start"])
    end = _xyz(rec["end"])
    mid = _xyz(rec["mid"])
    return DB.Arc.Create(start, end, mid)


def _is_diag(el):
    try:
        tn = _norm(get_element_name(el.Symbol))
        return "hss50x50x25" in tn
    except Exception:
        return False


def _is_member_web(el):
    try:
        tn = _norm(get_element_name(el.Symbol))
        return "hss50x50x2" in tn
    except Exception:
        return False


def _pts_close(a, b, tol=0.15):
    return math.hypot(a.X - b.X, a.Y - b.Y, a.Z - b.Z) <= tol * FT_PER_M


def _is_arch(el):
    try:
        tn = _norm(get_element_name(el.Symbol))
        return tn in ("hss100x50x3", "hss100x50x45")
    except Exception:
        return False


def _collect_arch_curves(doc, diag_cat):
    arches = [e for e in DB.FilteredElementCollector(doc)
                .OfCategory(diag_cat)
                .WhereElementIsNotElementType().ToElements()
              if _is_arch(e)]
    curves = []
    for el in arches:
        try:
            loc = el.Location
            if hasattr(loc, "Curve") and loc.Curve:
                curves.append((el, loc.Curve))
        except Exception:
            pass
    return arches, curves


def _register(api):
    @api.route("/test_curve/", methods=["POST"])
    def test_curve(doc, request):
        """Crea UNA viga curva de prueba y devuelve su estado + bbox del solido.

        Body opcional: {"family": "...", "type": "..."}
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            data = request.data
            if isinstance(data, str):
                data = json.loads(data)
            data = data if isinstance(data, dict) else {}
            fam = data.get("family", F_HSS)
            typ = data.get("type", "HSS100x50x3")
            rec = {
                "start": [0.0, 0.0, 6.0],
                "end": [22.65, 0.0, 6.0],
                "mid": [11.325, 0.0, 11.66],
            }
            arc = _make_arc(rec)
            sym = _resolve_symbol(doc, fam, typ)
            if sym is None:
                return routes.make_response(data={"error": "symbol not found"}, status=404)
            level = lowest_level(doc)
            t = _new_txn(doc, "Test curved beam")
            t.Start()
            try:
                inst = doc.Create.NewFamilyInstance(
                    arc, sym, level, DB.Structure.StructuralType.Beam)
                idv = inst.Id
                t.Commit()
            except Exception:
                t.RollBack()
                raise
            # inspeccionar el elemento creado
            elem = doc.GetElement(idv)
            info = {"id": int(str(idv).replace("ElementId(", "").replace(")", ""))}
            try:
                lc = elem.Location
                if hasattr(lc, "Curve"):
                    info["curve"] = type(lc.Curve).__name__
                    info["length_m"] = lc.Curve.Length / FT_PER_M
            except Exception as e:
                info["curve_err"] = str(e)
            try:
                bb = elem.get_BoundingBox(None)
                if bb:
                    info["bb_min_m"] = [round(bb.Min.X / FT_PER_M, 3),
                                        round(bb.Min.Y / FT_PER_M, 3),
                                        round(bb.Min.Z / FT_PER_M, 3)]
                    info["bb_max_m"] = [round(bb.Max.X / FT_PER_M, 3),
                                        round(bb.Max.Y / FT_PER_M, 3),
                                        round(bb.Max.Z / FT_PER_M, 3)]
            except Exception as e:
                info["bb_err"] = str(e)
            return routes.make_response(data={
                "status": "success",
                "element": info,
                "family": get_element_name(sym.Family),
                "type": get_element_name(sym),
            })
        except Exception as e:
            log_route_error("test_curve", e)
            logger.error("test_curve failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/arcify/", methods=["POST"])
    def arcify(doc, request):
        """Convierte las bridas del arco en curvas reales.

        Body (coordenadas en metros):
        {
          "unit": "m",
          "arcs": [
            {
              "section": "BRIDA SUPERIOR HSS100x50x3 mm",
              "family": "HSS-Sección estructural hueca",
              "type": "HSS100x50x3",
              "start": [0,0,6], "mid": [11.325,0,11.66], "end": [22.65,0,6],
              "frame_ids": [1,2,...]
            }, ...
          ],
          "structural_type": "Beam",     # opcional
          "dry_run": false
        }
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            data = request.data
            if isinstance(data, str):
                data = json.loads(data)
            data = data if isinstance(data, dict) else {}

            arcs = data.get("arcs", [])
            dry_run = bool(data.get("dry_run", False))
            stype_name = data.get("structural_type", "Beam")
            stype = DB.Structure.StructuralType.Beam \
                if stype_name.lower() == "beam" else DB.Structure.StructuralType.Brace

            level = lowest_level(doc)

            # resolver simbolos por familia+tipo
            symbols = {}
            for a in arcs:
                key = (a.get("family", F_HSS), a.get("type", ""))
                if key not in symbols:
                    symbols[key] = _resolve_symbol(doc, key[0], key[1])
                a["_sym"] = symbols[key]

            # indices de elemento a borrar (Mark = frame id .s2k) -> NO se usa:
            # el parametro Mark no existe en estos elementos; se borra por
            # geometria + tipo (segmento lineal sobre el arco).
            chord_types = set()
            for a in arcs:
                chord_types.add((_norm(a.get("family", F_HSS)),
                                 _norm(a.get("type", ""))))

            created = 0
            deleted = 0
            skipped = []
            if not dry_run:
                t = _new_txn(doc, "Arcify arch chords")
                t.Start()
                try:
                    for i, a in enumerate(arcs):
                        sym = a.get("_sym")
                        if sym is None:
                            skipped.append(i)
                            continue
                        if not sym.IsActive:
                            sym.Activate()
                        arc = _make_arc(a)
                        inst = doc.Create.NewFamilyInstance(
                            arc, sym, level, stype)
                        mark = inst.LookupParameter("Mark")
                        if mark and not mark.IsReadOnly:
                            mark.Set(u"ARC {}".format(i + 1))
                        created += 1

                    # borrar segmentos lineales del arco:
                    #  - tipo HSS100x50x3: todos son brida superior (lineal)
                    #  - tipo HSS100x50x4.5: solo los que van en direccion X
                    #    (los correas van en direccion Y y se conservan)
                    collector = DB.FilteredElementCollector(doc)\
                        .OfCategory(DB.BuiltInCategory.OST_StructuralFraming)\
                        .WhereElementIsNotElementType()
                    for el in collector.ToElements():
                        try:
                            sym = el.Symbol
                            key = (_norm(get_element_name(sym.Family)),
                                   _norm(get_element_name(sym)))
                            if key not in chord_types:
                                continue
                            lc = el.Location
                            if not hasattr(lc, "Curve"):
                                continue
                            curve = lc.Curve
                            if not isinstance(curve, DB.Line):
                                continue  # conservar las curvas creadas
                            try:
                                d = curve.Direction
                            except Exception:
                                continue
                            is_x = abs(d.X) > abs(d.Y)
                            tname = _norm(get_element_name(sym))
                            if tname == "hss100x50x3":
                                should_del = True
                            elif tname == "hss100x50x45":
                                should_del = is_x
                            else:
                                should_del = False
                            if should_del:
                                doc.Delete(el.Id)
                                deleted += 1
                        except Exception:
                            continue
                    t.Commit()
                except Exception:
                    t.RollBack()
                    raise

            return routes.make_response(data={
                "status": "success",
                "created": created,
                "deleted": deleted,
                "dry_run": dry_run,
                "skipped": skipped,
                "total_arcs": len(arcs),
            })
        except Exception as e:
            log_route_error("arcify", e)
            logger.error("arcify failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)


    @api.route("/delete_elements/", methods=["POST"])
    def delete_elements(doc, request):
        """Borra elementos de Revit por id (para limpiar pruebas)."""
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            data = request.data
            if isinstance(data, str):
                data = json.loads(data)
            data = data if isinstance(data, dict) else {}
            ids = data.get("ids", [])
            lookup = {}
            for cat in (DB.BuiltInCategory.OST_StructuralFraming,
                        DB.BuiltInCategory.OST_StructuralColumns):
                for el in DB.FilteredElementCollector(doc)\
                        .OfCategory(cat)\
                        .WhereElementIsNotElementType()\
                        .ToElements():
                    lookup[str(el.Id)] = el
            t = _new_txn(doc, "Delete elements")
            t.Start()
            deleted = 0
            try:
                for raw in ids:
                    try:
                        el = lookup.get(str(raw))
                        if el is not None:
                            doc.Delete(el.Id)
                            deleted += 1
                    except Exception:
                        continue
                t.Commit()
            except Exception:
                t.RollBack()
                raise
            return routes.make_response(data={
                "status": "success", "deleted": deleted,
            })
        except Exception as e:
            log_route_error("delete_elements", e)
            logger.error("delete_elements failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)


    @api.route("/list_marks/", methods=["POST"])
    def list_marks(doc, request):
        """Lista elementos structural framing con su Mark, id y tipo."""
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            data = request.data
            if isinstance(data, str):
                data = json.loads(data)
            data = data if isinstance(data, dict) else {}
            typ_filter = data.get("type")
            collector = DB.FilteredElementCollector(doc)\
                .OfCategory(DB.BuiltInCategory.OST_StructuralFraming)\
                .WhereElementIsNotElementType()
            out = []
            for el in collector.ToElements():
                try:
                    typ = get_element_name(el.GetType())
                    if typ_filter and _norm(typ) != _norm(typ_filter):
                        continue
                    mp = el.LookupParameter("Mark")
                    mark = mp.AsString() if mp else None
                    out.append({
                        "id": int(str(el.Id).replace("ElementId(", "").replace(")", "")),
                        "type": typ,
                        "mark": mark,
                        "has_mark_param": mp is not None,
                    })
                except Exception:
                    continue
            return routes.make_response(data={
                "status": "success", "count": len(out), "elements": out[:60],
            })
        except Exception as e:
            log_route_error("list_marks", e)
            logger.error("list_marks failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)


    @api.route("/inspect_arcs/", methods=["POST"])
    def inspect_arcs(doc, request):
        """Inspecciona los elementos framing con LocationCurve tipo Arc."""
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            collector = DB.FilteredElementCollector(doc)\
                .OfCategory(DB.BuiltInCategory.OST_StructuralFraming)\
                .WhereElementIsNotElementType()
            out = []
            for el in collector.ToElements():
                try:
                    lc = el.Location
                    curve = lc.Curve if hasattr(lc, "Curve") else None
                    if not isinstance(curve, DB.Arc):
                        continue
                    rec = {
                        "id": int(str(el.Id).replace("ElementId(", "").replace(")", "")),
                        "type": get_element_name(el.Symbol),
                        "length_m": curve.Length / FT_PER_M,
                    }
                    try:
                        ctr = curve.Center
                        rec["center_m"] = [round(ctr.X / FT_PER_M, 3),
                                           round(ctr.Y / FT_PER_M, 3),
                                           round(ctr.Z / FT_PER_M, 3)]
                        rec["radius_m"] = round(curve.Radius / FT_PER_M, 4)
                    except Exception:
                        pass
                    for k, idx in (("p0", 0), ("p1", 1)):
                        try:
                            p = curve.GetEndPoint(idx)
                            rec[k + "_m"] = [round(p.X / FT_PER_M, 3),
                                             round(p.Y / FT_PER_M, 3),
                                             round(p.Z / FT_PER_M, 3)]
                        except Exception:
                            pass
                    try:
                        bb = el.get_BoundingBox(None)
                        if bb:
                            rec["bb_min_m"] = [round(bb.Min.X / FT_PER_M, 3),
                                               round(bb.Min.Y / FT_PER_M, 3),
                                               round(bb.Min.Z / FT_PER_M, 3)]
                            rec["bb_max_m"] = [round(bb.Max.X / FT_PER_M, 3),
                                               round(bb.Max.Y / FT_PER_M, 3),
                                               round(bb.Max.Z / FT_PER_M, 3)]
                    except Exception:
                        pass
                    out.append(rec)
                except Exception:
                    continue
            return routes.make_response(data={
                "status": "success", "count": len(out), "arcs": out,
            })
        except Exception as e:
            log_route_error("inspect_arcs", e)
            logger.error("inspect_arcs failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)


    @api.route("/solid_info/", methods=["POST"])
    def solid_info(doc, request):
        """Datos del solido real de un elemento: volumen y bbox de geometria."""
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            data = request.data
            if isinstance(data, str):
                data = json.loads(data)
            data = data if isinstance(data, dict) else {}
            ids = data.get("ids", [])
            lookup = {}
            for cat in (DB.BuiltInCategory.OST_StructuralFraming,
                        DB.BuiltInCategory.OST_StructuralColumns):
                for el in DB.FilteredElementCollector(doc)\
                        .OfCategory(cat)\
                        .WhereElementIsNotElementType()\
                        .ToElements():
                    lookup[str(el.Id)] = el
            out = []
            for raw in ids:
                try:
                    el = lookup.get(str(raw))
                    if el is None:
                        out.append({"id": raw, "error": "not found"})
                        continue
                    rec = {"id": raw, "type": get_element_name(el.Symbol)}
                    opt = DB.Options()
                    opt.DetailLevel = DB.ViewDetailLevel.Fine
                    opt.ComputeReferences = False
                    st = {"vol": 0.0, "solids": 0, "bmin": None, "bmax": None,
                          "n": 0, "z_gt_7": 0, "z_gt_9": 0, "z_gt_10": 0,
                          "zmax": -1e30, "pts": []}

                    def walk(ge):
                        for obj in ge:
                            if isinstance(obj, DB.Solid):
                                try:
                                    st["vol"] += obj.Volume
                                    st["solids"] += 1
                                except Exception:
                                    pass
                                try:
                                    for edg in obj.Edges:
                                        for p in edg.Tessellate():
                                            st["n"] += 1
                                            if p.Z > st["zmax"]:
                                                st["zmax"] = p.Z
                                            if p.Z > 7.0:
                                                st["z_gt_7"] += 1
                                            if p.Z > 9.0:
                                                st["z_gt_9"] += 1
                                            if p.Z > 10.0:
                                                st["z_gt_10"] += 1
                                            if len(st["pts"]) < 12:
                                                st["pts"].append(
                                                    [round(p.X / FT_PER_M, 3),
                                                     round(p.Y / FT_PER_M, 3),
                                                     round(p.Z / FT_PER_M, 3)])
                                except Exception:
                                    pass
                            elif isinstance(obj, DB.GeometryInstance):
                                try:
                                    walk(obj.GetInstanceGeometry())
                                except Exception:
                                    pass

                    walk(el.get_Geometry(opt))
                    rec["solids"] = st["solids"]
                    rec["volume_m3"] = round(st["vol"] / (FT_PER_M ** 3), 6)
                    rec["n_pts"] = st["n"]
                    rec["z_max_m"] = round(st["zmax"] / FT_PER_M, 3)
                    rec["z_gt_7"] = st["z_gt_7"]
                    rec["z_gt_9"] = st["z_gt_9"]
                    rec["z_gt_10"] = st["z_gt_10"]
                    rec["sample_pts"] = st["pts"]
                    out.append(rec)
                except Exception as e:
                    out.append({"id": raw, "error": str(e)})
            return routes.make_response(data={"status": "success", "items": out})
        except Exception as e:
            log_route_error("solid_info", e)
            logger.error("solid_info failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)


def register_arc_routes(api):
    _register(api)
    logger.info("Arc routes registered successfully")

    @api.route("/diag_join_api/", methods=["POST"])
    def diag_join_api(doc, request):
        """Diagnostic: checks JoinGeometryUtils API and cut length vs system length."""
        try:
            result = {}
            result["db_has_jgu"] = hasattr(DB, 'JoinGeometryUtils')
            try:
                jgu = DB.JoinGeometryUtils
                result["jgu_methods"] = sorted([m for m in dir(jgu) if not m.startswith('_')])
            except Exception as e:
                result["jgu_error"] = str(e)

            # Check cut length vs system length for diagonals
            cut_vs_sys = []
            param_names = []
            FT_PER_M = 3.280839895
            for el in DB.FilteredElementCollector(doc)\
                .OfCategory(DB.BuiltInCategory.OST_StructuralFraming)\
                .WhereElementIsNotElementType()\
                .ToElements():
                try:
                    tn = get_element_name(el.Symbol)
                    if "hss50x50x25" not in _norm(tn):
                        continue

                    # List all parameters for first few elements
                    if len(param_names) < 3:
                        pnames = []
                        for p in el.Parameters:
                            pnames.append(p.Definition.Name)
                        param_names.append({"id": int(str(el.Id).replace("ElementId(", "").replace(")", "")), "params": sorted(pnames)})

                    # Try built-in parameters (check both English and Spanish names)
                    sys_len = None
                    cut_len = None
                    for p in el.Parameters:
                        name = p.Definition.Name.lower()
                        if "sistema" in name or "system length" in name:
                            sys_len = p.AsDouble()
                        if "corte" in name or "cut length" in name:
                            cut_len = p.AsDouble()

                    curve_len = None
                    if hasattr(el.Location, 'Curve') and el.Location.Curve:
                        curve_len = el.Location.Curve.Length

                    cut_vs_sys.append({
                        "id": int(str(el.Id).replace("ElementId(", "").replace(")", "")),
                        "type": tn,
                        "sys_len_m": round(sys_len / FT_PER_M, 4) if sys_len else None,
                        "cut_len_m": round(cut_len / FT_PER_M, 4) if cut_len else None,
                        "curve_len_m": round(curve_len / FT_PER_M, 4) if curve_len else None,
                    })
                except Exception as e:
                    pass
                if len(cut_vs_sys) >= 10:
                    break

            result["all_params_sample"] = param_names
            result["cut_len_vs_sys_len"] = cut_vs_sys

            # Check StructuralFramingUtils
            try:
                from Autodesk.Revit.DB.Structure import StructuralFramingUtils as SFU
                result["sfu_methods"] = sorted([m for m in dir(SFU) if not m.startswith('_')])
                result["has_disallow"] = hasattr(SFU, 'DisallowJoinAtEnd')
                result["has_allow"] = hasattr(SFU, 'AllowJoinAtEnd')
            except Exception as e:
                result["sfu_error"] = str(e)
            try:
                sfu2 = DB.StructuralFramingUtils
                result["db_sfu_methods"] = sorted([m for m in dir(sfu2) if not m.startswith('_')])
            except Exception as e:
                result["db_sfu_error"] = str(e)

            return routes.make_response(data=result)
        except Exception as e:
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/disallow_join_diags/", methods=["POST"])
    def disallow_join_diags(doc, request):
        """Aplica DisallowJoinAtEnd a ambos extremos de TODOS los elementos rectos
        estructurales (diagonales, correas, montantes, tensores, columnas).

        Esto previene el corte automatico de Revit en los extremos, haciendo que
        la Longitud de Corte = Longitud del Sistema.
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)

            FT_PER_M = 3.280839895

            # Tipos que son "elementos rectos" (no arcos curvos)
            straight_types = set()
            arc_type_names = {"hss100x50x3", "hss100x50x45"}

            from Autodesk.Revit.DB.Structure import StructuralFramingUtils

            modified = 0
            errors = []
            check = []

            cat_map = {
                "framing": DB.BuiltInCategory.OST_StructuralFraming,
                "columns": DB.BuiltInCategory.OST_StructuralColumns,
            }

            t = _new_txn(doc, "Disallow join at end for straight elements")
            t.Start()
            try:
                for cat_label, cat in cat_map.items():
                    for el in DB.FilteredElementCollector(doc)\
                        .OfCategory(cat)\
                        .WhereElementIsNotElementType()\
                        .ToElements():
                        try:
                            tn = _norm(get_element_name(el.Symbol))
                            # Skip curved elements (arcs)
                            loc = el.Location
                            curve = None
                            if hasattr(loc, "Curve"):
                                curve = loc.Curve
                            if isinstance(curve, DB.Arc):
                                continue  # curved arch, skip

                            # Check if it has a LocationCurve (straight element)
                            if not (hasattr(loc, "Curve") and isinstance(curve, DB.Line)):
                                continue

                            # Columns don't support StructuralFramingUtils
                            if cat_label == "columns":
                                continue

                            # Check if join is already disallowed at both ends
                            try:
                                end0_allowed = StructuralFramingUtils.IsJoinAllowedAtEnd(el, 0)
                            except Exception:
                                end0_allowed = True
                            try:
                                end1_allowed = StructuralFramingUtils.IsJoinAllowedAtEnd(el, 1)
                            except Exception:
                                end1_allowed = True

                            if not end0_allowed and not end1_allowed:
                                # Already disallowed at both ends, just check
                                pass
                            else:
                                if end0_allowed:
                                    StructuralFramingUtils.DisallowJoinAtEnd(el, 0)
                                if end1_allowed:
                                    StructuralFramingUtils.DisallowJoinAtEnd(el, 1)
                            modified += 1
                        except Exception as e:
                            if len(errors) < 5:
                                errors.append(str(e)[:200])
                t.Commit()
            except Exception:
                try:
                    if t.HasStarted() and not t.HasEnded():
                        t.RollBack()
                except Exception:
                    pass
                raise

            # Check values AFTER transaction commit
            for el in DB.FilteredElementCollector(doc)\
                .OfCategory(DB.BuiltInCategory.OST_StructuralFraming)\
                .WhereElementIsNotElementType()\
                .ToElements():
                try:
                    tn = _norm(get_element_name(el.Symbol))
                    loc = el.Location
                    curve = loc.Curve if hasattr(loc, "Curve") else None
                    if isinstance(curve, DB.Arc):
                        continue
                    if not isinstance(curve, DB.Line):
                        continue
                    if len(check) < 20:
                        tl = el.LookupParameter(u"Longitud del sistema")
                        cl = el.LookupParameter(u"Longitud de corte")
                        sys_val = tl.AsDouble() if tl else None
                        cut_val = cl.AsDouble() if cl else None
                        check.append({
                            "id": int(str(el.Id).replace("ElementId(", "").replace(")", "")),
                            "type": get_element_name(el.Symbol),
                            "sys_m": round(sys_val / FT_PER_M, 4) if sys_val else None,
                            "cut_m": round(cut_val / FT_PER_M, 4) if cut_val else None,
                            "equal": abs(sys_val / FT_PER_M - cut_val / FT_PER_M) < 0.001 if (sys_val and cut_val) else False,
                        })
                except Exception:
                    pass

            return routes.make_response(data={
                "status": "success",
                "modified": modified,
                "errors": errors,
                "check": check,
            })
        except Exception as e:
            log_route_error("disallow_join_diags", e)
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/fix_inferior_arcs/", methods=["POST"])
    def fix_inferior_arcs(doc, request):
        """Recrea los arcos inferiores CONCENTRICOS con el arco superior.

        El desfase entre bridas es una distancia perpendicular (normal) constante,
        no vertical. Ambos arcos comparten el MISMO centro de curvatura y el arco
        inferior tiene R_inferior = R_superior - 0.50 m.

        Body opcional: {"offset_m": 0.50}
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)

            FT_PER_M = 3.280839895
            level = lowest_level(doc)
            try:
                offset_m = float(request.data.get("offset_m", 0.50))                     if isinstance(request.data, dict) else 0.50
            except Exception:
                offset_m = 0.50

            sym = _resolve_symbol(doc, F_HSS, "HSS100x50x4.5")
            if sym is None:
                return routes.make_response(
                    data={"error": "HSS100x50x4.5 symbol not found"}, status=404)

            cat = DB.BuiltInCategory.OST_StructuralFraming
            frames = DB.FilteredElementCollector(doc) \
                .OfCategory(cat).WhereElementIsNotElementType().ToElements()

            sup_arcs = []
            for el in frames:
                try:
                    if _norm(get_element_name(el.Symbol)) != "hss100x50x3":
                        continue
                    loc = el.Location
                    cur = loc.Curve if hasattr(loc, "Curve") else None
                    if isinstance(cur, DB.Arc):
                        sup_arcs.append((el, cur))
                except Exception:
                    continue

            deleted = 0
            created = 0
            errors = []
            t = _new_txn(doc, "Recreate concentric inferior arcs")
            t.Start()
            try:
                for el in frames:
                    try:
                        tn = _norm(get_element_name(el.Symbol))
                        if tn != "hss100x50x45":
                            continue
                        loc = el.Location
                        cur = loc.Curve if hasattr(loc, "Curve") else None
                        if isinstance(cur, DB.Arc):
                            doc.Delete(el.Id)
                            deleted += 1
                    except Exception:
                        continue

                for sel, sac in sup_arcs:
                    try:
                        center = sac.Center
                        Rsup = sac.Radius
                        Rinf = Rsup - offset_m * FT_PER_M
                        if Rinf <= 0:
                            continue
                        p0s = sac.GetEndPoint(0)
                        p1s = sac.GetEndPoint(1)
                        mid_s = sac.Evaluate(0.5, False)
                        p0 = center + (p0s - center) * (Rinf / Rsup)
                        p1 = center + (p1s - center) * (Rinf / Rsup)
                        mid = center + (mid_s - center) * (Rinf / Rsup)
                        arc = DB.Arc.Create(p0, p1, mid)
                        if not sym.IsActive:
                            try:
                                sym.Activate()
                            except Exception:
                                pass
                        inst = doc.Create.NewFamilyInstance(
                            arc, sym, level, DB.Structure.StructuralType.Beam)
                        mark = inst.LookupParameter("Mark")
                        if mark and not mark.IsReadOnly:
                            mark.Set(u"ARC-INF")
                        created += 1
                    except Exception as e:
                        if len(errors) < 5:
                            errors.append(str(e)[:120])

                t.Commit()
            except Exception:
                try:
                    if t.HasStarted() and not t.HasEnded():
                        t.RollBack()
                except Exception:
                    pass
                raise

            return routes.make_response(data={
                "status": "success",
                "deleted": deleted,
                "created": created,
                "offset_m": offset_m,
                "errors": errors[:6],
            })
        except Exception as e:
            log_route_error("fix_inferior_arcs", e)
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/miter_cut/", methods=["POST"])
    def miter_cut(doc, request):
        """Aplica Corte de Sierra - Ala (miter) entre diagonales y arcos.

        Une cada elemento diagonal (HSS50x50x2.5) con los elementos de arco
        (HSS100x50x3 / HSS100x50x4.5) cuyos extremos coincidan, usando
        JoinGeometryUtils para que Revit aplique el corte de sierra automático.
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)

            data = request.data
            if isinstance(data, str):
                data = json.loads(data)
            data = data if isinstance(data, dict) else {}
            try:
                tol_m = float(data.get("tol_m", 0.05))
            except Exception:
                tol_m = 0.05

            FT_PER_M = 3.280839895
            TOL = tol_m * FT_PER_M  # pies

            diag_cat = DB.BuiltInCategory.OST_StructuralFraming
            col_cat = DB.BuiltInCategory.OST_StructuralColumns

            def is_diag(el):
                try:
                    tn = _norm(get_element_name(el.Symbol))
                    return "hss50x50x25" in tn
                except Exception:
                    return False

            def is_arch(el):
                try:
                    tn = _norm(get_element_name(el.Symbol))
                    return tn in ("hss100x50x3", "hss100x50x45")
                except Exception:
                    return False

            diags = [e for e in DB.FilteredElementCollector(doc)\
                           .OfCategory(diag_cat)\
                           .WhereElementIsNotElementType()\
                           .ToElements() if is_diag(e)]
            arches = [e for e in DB.FilteredElementCollector(doc)\
                            .OfCategory(diag_cat)\
                            .WhereElementIsNotElementType()\
                            .ToElements() if is_arch(e)]

            # construir lista de curvas de arco
            arch_curves = []
            for el in arches:
                try:
                    loc = el.Location
                    if hasattr(loc, "Curve") and loc.Curve:
                        arch_curves.append((el, loc.Curve))
                except Exception:
                    pass

            joined = 0
            already_joined = 0
            failed = 0
            skipped = 0
            errors = []
            t = _new_txn(doc, "Miter cut diagonals to arches")
            t.Start()
            try:
                for d in diags:
                    try:
                        dloc = d.Location
                        if not hasattr(dloc, "Curve"):
                            skipped += 1
                            continue
                        dcurve = dloc.Curve
                        dp0 = dcurve.GetEndPoint(0)
                        dp1 = dcurve.GetEndPoint(1)
                        for arel, acurve in arch_curves:
                            near_eps = TOL
                            near = False
                            for dp in (dp0, dp1):
                                p = acurve.Project(dp)
                                if p and p.Distance < near_eps:
                                    near = True
                                    break
                            if not near:
                                continue
                            try:
                                if DB.JoinGeometryUtils.AreElementsJoined(doc, d, arel):
                                    already_joined += 1
                                else:
                                    DB.JoinGeometryUtils.JoinGeometry(doc, d, arel)
                                    joined += 1
                            except Exception as je:
                                failed += 1
                                if len(errors) < 5:
                                    errors.append(str(je)[:200])
                    except Exception:
                        skipped += 1
                        continue
                t.Commit()
            except Exception:
                try:
                    if t.HasStarted() and not t.HasEnded():
                        t.RollBack()
                except Exception:
                    pass
                raise

            return routes.make_response(data={
                "status": "success",
                "joined": joined,
                "already_joined": already_joined,
                "failed": failed,
                "skipped": skipped,
                "total_diags": len(diags),
                "total_arches": len(arches),
                "tol_m": tol_m,
                "errors": errors,
            })
        except Exception as e:
            log_route_error("miter_cut", e)
            logger.error("miter_cut failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/snap_diags_to_arcs/", methods=["POST"])
    def snap_diags_to_arcs(doc, request):
        """Lleva cada extremo de diagonal (HSS50x50x2.5) hasta la curva del arco
        (HSS100x50x3 / 4.5) mas cercana proyectando el punto sobre el arco.

        Body opcional: {"tol_m": 0.30}. Para cada diagonal cuyos extremos queden
        dentro de la tolerancia de un arco, recrea el elemento con el extremo
        exactamente sobre la curva del arco (proyeccion), dejandolo listo para
        el corte de sierra (miter)."""
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)

            data = request.data
            if isinstance(data, str):
                data = json.loads(data)
            data = data if isinstance(data, dict) else {}
            try:
                tol_m = float(data.get("tol_m", 0.30))
            except Exception:
                tol_m = 0.30

            FT_PER_M = 3.280839895
            TOL = tol_m * FT_PER_M

            diag_cat = DB.BuiltInCategory.OST_StructuralFraming
            diags = [e for e in DB.FilteredElementCollector(doc)
                       .OfCategory(diag_cat)
                       .WhereElementIsNotElementType().ToElements()
                     if _is_diag(e)]
            arches, arch_curves = _collect_arch_curves(doc, diag_cat)
            level = lowest_level(doc)

            moved = 0
            skipped = 0
            errors = []
            t = _new_txn(doc, "Snap diagonals to arch curves")
            t.Start()
            try:
                for d in diags:
                    try:
                        dloc = d.Location
                        if not hasattr(dloc, "Curve"):
                            skipped += 1
                            continue
                        dcurve = dloc.Curve
                        if not isinstance(dcurve, DB.Line):
                            skipped += 1
                            continue
                        sym = d.Symbol
                        if not sym.IsActive:
                            sym.Activate()
                        p0 = dcurve.GetEndPoint(0)
                        p1 = dcurve.GetEndPoint(1)

                        new_pts = []
                        changed = False
                        for dp in (p0, p1):
                            best = None
                            for arel, ac in arch_curves:
                                try:
                                    pr = ac.Project(dp)
                                    if pr and (best is None or pr.Distance < best[0]):
                                        best = (pr.Distance, pr.XYZPoint)
                                except Exception:
                                    pass
                            if best is not None and best[0] <= TOL:
                                new_pts.append(best[1])
                                if best[0] > 0.005 / FT_PER_M:
                                    changed = True
                            else:
                                new_pts.append(dp)

                        if not changed:
                            skipped += 1
                            continue

                        mark = d.LookupParameter("Mark")
                        mark_val = mark.AsString() if mark and not mark.IsReadOnly else None

                        new_line = DB.Line.CreateBound(new_pts[0], new_pts[1])
                        doc.Delete(d.Id)
                        inst = doc.Create.NewFamilyInstance(
                            new_line, sym, level, DB.Structure.StructuralType.Beam)
                        if mark_val is not None:
                            nm = inst.LookupParameter("Mark")
                            if nm and not nm.IsReadOnly:
                                try:
                                    nm.Set(mark_val)
                                except Exception:
                                    pass
                        moved += 1
                    except Exception as e1:
                        skipped += 1
                        if len(errors) < 5:
                            errors.append(str(e1)[:200])
                t.Commit()
            except Exception:
                try:
                    if t.HasStarted() and not t.HasEnded():
                        t.RollBack()
                except Exception:
                    pass
                raise

            return routes.make_response(data={
                "status": "success",
                "tol_m": tol_m,
                "total_diags": len(diags),
                "total_arches": len(arches),
                "moved": moved,
                "skipped": skipped,
                "errors": errors,
            })
        except Exception as e:
            log_route_error("snap_diags_to_arcs", e)
            logger.error("snap_diags_to_arcs failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/diag_diag_gaps/", methods=["POST"])
    def diag_diag_gaps(doc, request):
        """Diagnostica la distancia de cada extremo de diagonal (HSS50x50x2.5)
        al arco (HSS100x50x3/4.5) mas cercano. Reporta histograma de gaps."""
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            diag_cat = DB.BuiltInCategory.OST_StructuralFraming
            diags = [e for e in DB.FilteredElementCollector(doc)
                       .OfCategory(diag_cat)
                       .WhereElementIsNotElementType().ToElements()
                     if _is_diag(e)]
            arches, arch_curves = _collect_arch_curves(doc, diag_cat)
            FT = 3.280839895

            gaps = []
            samples = []
            for d in diags:
                try:
                    loc = d.Location
                    if not hasattr(loc, "Curve"):
                        continue
                    dc = loc.Curve
                    for k in (0, 1):
                        dp = dc.GetEndPoint(k)
                        best = None
                        for arel, ac in arch_curves:
                            try:
                                p = ac.Project(dp)
                                if p:
                                    dist = p.Distance
                                    if best is None or dist < best[0]:
                                        best = (dist, arel)
                            except Exception:
                                pass
                        if best is None:
                            continue
                        gaps.append(best[0] / FT)
                except Exception:
                    continue

            buckets = {}
            for g in gaps:
                key = round(g * 100, 0) / 100.0
                buckets[key] = buckets.get(key, 0) + 1

            counts = {
                "lt_0_05m": sum(1 for g in gaps if g < 0.05),
                "0_05_to_0_10": sum(1 for g in gaps if 0.05 <= g < 0.10),
                "0_10_to_0_20": sum(1 for g in gaps if 0.10 <= g < 0.20),
                "0_20_to_0_50": sum(1 for g in gaps if 0.20 <= g < 0.50),
                "ge_0_50m": sum(1 for g in gaps if g >= 0.50),
            }
            return routes.make_response(data={
                "status": "success",
                "total_diags": len(diags),
                "total_arches": len(arches),
                "gap_endpoints_sampled": len(gaps),
                "counts": counts,
                "histogram_m": buckets,
            })
        except Exception as e:
            log_route_error("diag_diag_gaps", e)
            logger.error("diag_diag_gaps failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/miter_diags_to_arcs/", methods=["POST"])
    def miter_diags_to_arcs(doc, request):
        """Habilita AllowJoinAtEnd en los extremos de diagonal (HSS50x50x2.5)
        que tocan un arco (HSS100x50x3/4.5) y aplica JoinGeometryUtils para el
        corte de sierra. Body: {"tol_m": 0.10}"""
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)

            data = request.data
            if isinstance(data, str):
                data = json.loads(data)
            data = data if isinstance(data, dict) else {}
            try:
                tol_m = float(data.get("tol_m", 0.10))
            except Exception:
                tol_m = 0.10

            FT_PER_M = 3.280839895
            TOL = tol_m * FT_PER_M
            diag_cat = DB.BuiltInCategory.OST_StructuralFraming
            diags = [e for e in DB.FilteredElementCollector(doc)
                       .OfCategory(diag_cat)
                       .WhereElementIsNotElementType().ToElements()
                     if _is_diag(e)]
            arches, arch_curves = _collect_arch_curves(doc, diag_cat)

            from Autodesk.Revit.DB.Structure import StructuralFramingUtils as SFU

            try:
                max_seg_m = float(data.get("max_seg_m", 0.50))
            except Exception:
                max_seg_m = 0.50
            MAX_SEG = max_seg_m * FT_PER_M

            # 1) para cada diagonal recolectar en que extremos toca arcos
            diag_arc_ends = []
            for d in diags:
                try:
                    dloc = d.Location
                    if not hasattr(dloc, "Curve"):
                        continue
                    dc = dloc.Curve
                    for idx in (0, 1):
                        p = dc.GetEndPoint(idx)
                        for arel, ac in arch_curves:
                            try:
                                pr = ac.Project(p)
                                if pr and pr.Distance <= TOL:
                                    diag_arc_ends.append((d, idx, pr.Parameter, arel))
                                    break
                            except Exception:
                                pass
                except Exception:
                    pass

            # 2) descomponer cada arco en tramos rectos (chords) en los puntos
            #    donde tocan las diagonales. Agrupar param por arco.
            from collections import defaultdict
            arc_points = defaultdict(set)
            for d, idx, par, arel in diag_arc_ends:
                arc_points[arel.Id.IntegerValue].add(par)

            errors = []
            t = _new_txn(doc, "Split arches into straight segments + join diagonals")
            t.Start()
            try:
                # 2b) crear los tramos rectos: puntos en [0,1] + conexiones
                new_segments = []  # (instancia, curva)
                seg_by_arch = defaultdict(list)
                seg_created = 0
                for arel, ac in arch_curves:
                    try:
                        params = sorted(set([0.0, 1.0]) | arc_points.get(
                            arel.Id.IntegerValue, set()))
                        pts = [ac.Evaluate(pp, False) for pp in params]
                        sym = arel.Symbol
                        level = arel.get_Parameter(
                            DB.BuiltInParameter.SCHEDULE_LEVEL_PARAM)
                        lvl = doc.GetElement(level.AsElementId()) if level and \
                            level.HasValue else doc.ActiveView.GenLevel
                        for i in range(len(pts) - 1):
                            pA, pB = pts[i], pts[i + 1]
                            if pA.DistanceTo(pB) < 1e-6:
                                continue
                            line = DB.Line.CreateBound(pA, pB)
                            inst = doc.Create.NewFamilyInstance(
                                line, sym, lvl, DB.Structure.StructuralType.Beam)
                            new_segments.append((inst, line))
                            seg_by_arch[arel.Id.IntegerValue].append(inst)
                            seg_created += 1
                    except Exception as e:
                        if len(errors) < 5:
                            errors.append("arch split: " + str(e)[:150])

                # 3) borrar los arcos curvos originales
                for arel in arches:
                    try:
                        doc.Delete(arel.Id)
                    except Exception:
                        pass

                # 4) unir cada diagonal a los tramos rectos con los que comparte extremo
                joined = 0
                already = 0
                failed = 0
                for d, idx, par, arel in diag_arc_ends:
                    try:
                        dc = d.Location.Curve
                        p = dc.GetEndPoint(idx)
                        for seg, seg_line in new_segments:
                            try:
                                s0, s1 = seg_line.GetEndPoint(0), seg_line.GetEndPoint(1)
                                near = p.DistanceTo(s0) <= TOL or p.DistanceTo(s1) <= TOL
                                if not near:
                                    continue
                                try:
                                    SFU.AllowJoinAtEnd(d, idx)
                                except Exception:
                                    pass
                                if DB.JoinGeometryUtils.AreElementsJoined(doc, d, seg):
                                    already += 1
                                else:
                                    DB.JoinGeometryUtils.JoinGeometry(doc, d, seg)
                                    joined += 1
                            except Exception as je:
                                failed += 1
                                if len(errors) < 5:
                                    errors.append("join: " + str(je)[:150])
                    except Exception:
                        continue

                t.Commit()
            except Exception:
                try:
                    if t.HasStarted() and not t.HasEnded():
                        t.RollBack()
                except Exception:
                    pass
                raise

            return routes.make_response(data={
                "status": "success",
                "tol_m": tol_m,
                "max_seg_m": max_seg_m,
                "total_diags": len(diags),
                "total_arches": len(arches),
                "diag_arc_touches": len(diag_arc_ends),
                "seg_created": seg_created,
                "joined": joined,
                "already": already,
                "failed": failed,
                "errors": errors[:6],
            })
        except Exception as e:
            log_route_error("miter_diag_to_arcs", e)
            logger.error("miter_diag_to_arcs failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/probe_framing_rot/", methods=["POST"])
    def probe_framing_rot(doc, request):
        """SOLO LECTURA. Muestra los parametros de rotacion de seccion
        disponibles en una viga estructural (para las correas)."""
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            cat = DB.BuiltInCategory.OST_StructuralFraming
            els = DB.FilteredElementCollector(doc)\
                .OfCategory(cat).WhereElementIsNotElementType().ToElements()
            target = None
            for el in els:
                try:
                    tn = _norm(get_element_name(el.Symbol))
                    if tn == "hss100x50x45":
                        target = el
                        break
                except Exception:
                    continue
            if target is None:
                return routes.make_response(
                    data={"error": "No HSS100x50x4.5 framing found"}, status=404)
            params = {}
            for p in target.Parameters:
                try:
                    bn = ""
                    try:
                        bn = str(p.Definition.BuiltInParameter)
                    except Exception:
                        pass
                    val = None
                    try:
                        if p.StorageType == DB.StorageType.Double:
                            val = p.AsDouble()
                            if p.HasValue:
                                val = round(p.AsDouble() / FT_PER_M, 5)
                        elif p.StorageType == DB.StorageType.Integer:
                            val = p.AsInteger()
                        elif p.StorageType == DB.StorageType.String:
                            val = p.AsString()
                    except Exception:
                        pass
                    if bn and ("ROT" in bn or "ANGLE" in bn or "ANG" in bn):
                        params[str(p.Definition.Name)] = {
                            "builtin": bn, "value": val,
                        }
                except Exception:
                    continue
            return routes.make_response(data={
                "status": "success",
                "element_id": int(str(target.Id).replace("ElementId(", "").replace(")", "")),
                "rotation_params": params,
                "all_param_names": [str(p.Definition.Name) for p in target.Parameters][:60],
            })
        except Exception as e:
            log_route_error("probe_framing_rot", e)
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/align_arcs/", methods=["POST"])
    def align_arcs(doc, request):
        """Alinea los arcos (HSS100x50x3 / HSS100x50x4.5) y sus columnas de
        apoyo (HSS200x200x6 en x=0 y x=22.65) a la cota del .s2k.

        El .s2k define el arco con centro (11.325, y, -2.5): el arco superior
        pasa por (0, 6.0) y (22.65, 6.0), y el inferior por (0.4, 5.70) y
        (22.25, 5.70). En el modelo actual el centro esta en z=-2.3, por lo
        que todos los extremos caen +0.2 m arriba. Esta ruta los baja 0.2 m
        hacia abajo (MoveElement por dz) sin alterar radios ni longitudes.

        Body opcional: {"dz_m": 0.20}
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)

            data = request.data
            if isinstance(data, str):
                data = json.loads(data)
            data = data if isinstance(data, dict) else {}
            try:
                dz_m = float(data.get("dz_m", 0.20))
            except Exception:
                dz_m = 0.20

            arc_names = {"hss100x50x3", "hss100x50x45"}
            col_names = {"hss200x200x6"}
            move_vec = DB.XYZ(0.0, 0.0, -dz_m * FT_PER_M)

            arcs = []
            cols = []
            framing = DB.FilteredElementCollector(doc)\
                .OfCategory(DB.BuiltInCategory.OST_StructuralFraming)\
                .WhereElementIsNotElementType().ToElements()
            for el in framing:
                try:
                    tn = _norm(get_element_name(el.Symbol))
                    if tn not in arc_names:
                        continue
                    loc = el.Location
                    cur = loc.Curve if hasattr(loc, "Curve") else None
                    if isinstance(cur, DB.Arc):
                        arcs.append(el)
                except Exception:
                    continue

            cols_collector = DB.FilteredElementCollector(doc)\
                .OfCategory(DB.BuiltInCategory.OST_StructuralColumns)\
                .WhereElementIsNotElementType().ToElements()
            for el in cols_collector:
                try:
                    tn = _norm(get_element_name(el.Symbol))
                    if tn in col_names:
                        cols.append(el)
                except Exception:
                    continue

            moved = 0
            errors = []
            t = _new_txn(doc, "Align arches to s2k elevation")
            t.Start()
            try:
                for el in arcs + cols:
                    try:
                        DB.ElementTransformUtils.MoveElement(doc, el.Id, move_vec)
                        moved += 1
                    except Exception as e:
                        if len(errors) < 5:
                            errors.append(str(e)[:160])
                t.Commit()
            except Exception:
                try:
                    if t.HasStarted() and not t.HasEnded():
                        t.RollBack()
                except Exception:
                    pass
                raise

            return routes.make_response(data={
                "status": "success",
                "dz_m": dz_m,
                "arcs_moved": len(arcs),
                "columns_moved": len(cols),
                "total_moved": moved,
                "errors": errors,
            })
        except Exception as e:
            log_route_error("align_arcs", e)
            logger.error("align_arcs failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/inspect_columns/", methods=["POST"])
    def inspect_columns(doc, request):
        """Lista columnas estructurales con su segmentacion vertical y la
        columna unica resultante por posicion (x, y)."""
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            cat = DB.BuiltInCategory.OST_StructuralColumns
            cols = DB.FilteredElementCollector(doc)\
                .OfCategory(cat).WhereElementIsNotElementType().ToElements()
            out = []
            for el in cols:
                try:
                    loc = el.Location
                    if not hasattr(loc, "Curve") or loc.Curve is None:
                        continue
                    c = loc.Curve
                    rec = {
                        "id": int(str(el.Id).replace("ElementId(", "").replace(")", "")),
                        "type": get_element_name(el.Symbol),
                        "len_m": round(c.Length / FT_PER_M, 3),
                        "p0_m": [round(c.GetEndPoint(0).X / FT_PER_M, 3),
                                 round(c.GetEndPoint(0).Y / FT_PER_M, 3),
                                 round(c.GetEndPoint(0).Z / FT_PER_M, 3)],
                        "p1_m": [round(c.GetEndPoint(1).X / FT_PER_M, 3),
                                 round(c.GetEndPoint(1).Y / FT_PER_M, 3),
                                 round(c.GetEndPoint(1).Z / FT_PER_M, 3)],
                    }
                    out.append(rec)
                except Exception:
                    continue
            out.sort(key=lambda r: (round(r["p0_m"][1], 2), round(r["p0_m"][0], 2), r["p0_m"][2]))
            return routes.make_response(data={
                "status": "success", "count": len(out), "columns": out,
            })
        except Exception as e:
            log_route_error("inspect_columns", e)
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/fix_column_tops/", methods=["POST"])
    def fix_column_tops(doc, request):
        """Baja los pilares de apoyo (HSS200x200x6) de forma PARAMETRICA.

        Los pilares estructurales estan gobernados por niveles: MoveElement
        desplaza la geometria pero Revit la recalcula desde Base Level / Top
        Level, por lo que el movimiento no persiste. Esta ruta ajusta el
        desfase superior (STRUCTURAL_TOP_OFFSET) de cada pilar HSS200x200x6
        para que su extremo superior quede a la cota dada (defecto z=6.0, la
        base del arco en el .s2k), manteniendo la base fija.

        Body opcional:
          {"top_z_m": 6.0, "dry_run": true|false}
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) \
                        if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            dry_run = bool(body.get("dry_run", False))
            try:
                top_z_m = float(body.get("top_z_m", 6.0))
            except Exception:
                top_z_m = 6.0

            cols = []
            for el in DB.FilteredElementCollector(doc)\
                     .OfCategory(DB.BuiltInCategory.OST_StructuralColumns)\
                     .WhereElementIsNotElementType().ToElements():
                try:
                    tn = _norm(get_element_name(el.Symbol))
                    if tn != "hss200x200x6":
                        continue
                    loc = el.Location
                    cur = loc.Curve if hasattr(loc, "Curve") else None
                    if not isinstance(cur, DB.Line):
                        continue
                    cols.append(el)
                except Exception:
                    continue

            out = []
            errors = []
            if not dry_run:
                t = _new_txn(doc, u"Bajar tops de pilares a cota arco")
                t.Start()
                try:
                    for el in cols:
                        try:
                            cur = el.Location.Curve
                            top_pt = cur.GetEndPoint(1)
                            cur_top = top_pt.Z / FT_PER_M
                            p_top = el.get_Parameter(
                                DB.BuiltInParameter.STRUCTURAL_TOP_OFFSET)
                            base_pt = cur.GetEndPoint(0)
                            cur_base = base_pt.Z / FT_PER_M
                            delta = top_z_m - cur_top
                            if p_top is not None:
                                new_top = (p_top.AsDouble() / FT_PER_M) + delta
                                p_top.Set(new_top * FT_PER_M)
                            out.append({
                                "id": int(str(el.Id).replace("ElementId(", "").replace(")", "")),
                                "base_z_m": round(cur_base, 3),
                                "top_z_m": round(top_z_m, 3),
                            })
                        except Exception as e1:
                            if len(errors) < 5:
                                errors.append(str(e1)[:160])
                    t.Commit()
                except Exception:
                    try:
                        if t.HasStarted() and not t.HasEnded():
                            t.RollBack()
                    except Exception:
                        pass
                    raise
            else:
                for el in cols:
                    try:
                        cur = el.Location.Curve
                        top_pt = cur.GetEndPoint(1)
                        cur_top = top_pt.Z / FT_PER_M
                        base_pt = cur.GetEndPoint(0)
                        cur_base = base_pt.Z / FT_PER_M
                        out.append({
                            "id": int(str(el.Id).replace("ElementId(", "").replace(")", "")),
                            "base_z_m": round(cur_base, 3),
                            "top_z_m": round(cur_top, 3),
                            "target_top_m": top_z_m,
                        })
                    except Exception:
                        continue

            return routes.make_response(data={
                "status": "success",
                "dry_run": dry_run,
                "top_z_m": top_z_m,
                "count": len(cols),
                "results": out,
                "errors": errors,
            })
        except Exception as e:
            log_route_error("fix_column_tops", e)
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/diag_export_api/", methods=["POST"])
    def diag_export_api(doc, request):
        """Diagnostico: inspecciona la API de ImageExportOptions/ExportImage."""
        import inspect
        out = {}
        try:
            out["image_opts_members"] = sorted(
                [m for m in dir(DB.ImageExportOptions) if not m.startswith("_")])
        except Exception as e:
            out["image_opts_error"] = str(e)
        try:
            out["export_folder_members"] = sorted(
                [m for m in dir(DB.ExportFolderInfo) if not m.startswith("_")])
        except Exception as e:
            out["export_folder_error"] = str(e)
        try:
            out["doc_export_methods"] = sorted(
                [m for m in dir(DB.Document) if "xport" in m or "Export" in m])
        except Exception as e:
            out["doc_export_error"] = str(e)
        try:
            o = DB.ImageExportOptions()
            out["instance_attrs"] = sorted([a for a in dir(o) if not a.startswith("_")])
        except Exception as e:
            out["instance_error"] = str(e)
        return routes.make_response(data=out)

    @api.route("/export_view_png/", methods=["POST"])
    def export_view_png(doc, request):
        """Renderiza la vista 3D 'S2K 3D' (o la activa) a un PNG en disco.

        Usa View.ExportImage + ImageExportOptions. La imagen queda en
        {out_dir}/{name}.png (defecto: C:\\Users\\aintc\\AppData\\Local\\Temp\\opencode\\revit_view.png).
        Body opcional:
          {"out_dir": "C:/...", "name": "vista", "pixels": 1600, "activate": true}
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) \
                        if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            out_dir = body.get("out_dir") or \
                u"C:\\Users\\aintc\\AppData\\Local\\Temp\\opencode"
            name = body.get("name") or "revit_view"
            try:
                pixels = int(body.get("pixels", 1600))
            except Exception:
                pixels = 1600
            activate = bool(body.get("activate", False))

            import os
            if not os.path.isdir(out_dir):
                os.makedirs(out_dir)
            img_path = os.path.join(out_dir, name + u".png")

            view = None
            for v in DB.FilteredElementCollector(doc)\
                      .OfClass(DB.View3D).ToElements():
                if v.Name.strip().upper() == u"S2K 3D" and not v.IsTemplate:
                    view = v
                    break
            if view is None:
                for v in DB.FilteredElementCollector(doc)\
                          .OfClass(DB.View3D).ToElements():
                    if not v.IsTemplate:
                        view = v
                        break
            if view is None:
                return routes.make_response(
                    data={"error": u"No hay vista 3D en el documento"}, status=404)

            if activate:
                try:
                    uidoc = revit.uidoc
                    if uidoc is not None:
                        uidoc.RequestViewChange(view)
                except Exception:
                    pass

            if not os.path.isdir(out_dir):
                os.makedirs(out_dir)
            opts = DB.ImageExportOptions()
            opts.ZoomType = DB.ZoomFitType.FitToPage
            opts.PixelSize = pixels
            opts.ImageResolution = DB.ImageResolution.DPI_150
            opts.HLRandWFViewsFileType = DB.ImageFileType.PNG
            opts.FilePath = os.path.join(out_dir, name)
            opts.SetViewsAndSheets([view.Id])
            doc.ExportImage(opts)
            file_path = os.path.join(out_dir, name + u".png")

            return routes.make_response(data={
                "status": "success",
                "view": view.Name,
                "path": file_path,
                "exists": os.path.isfile(file_path),
            })
        except Exception as e:
            log_route_error("export_view_png", e)
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/shift_steel_up/", methods=["POST"])
    def shift_steel_up(doc, request):
        """Desplaza elementos estructurales hacia +Z el valor dado (default +0.20 m).

        Body opcional:
          {"dz_m": 0.20,
           "family_include": ["hss", "round", "bar"],  # subcadenas de familia (default acero)
           "family_exclude": ["hormigon", "concreto", "pedestal"]}
        Por defecto mueve SOLO acero estructural (HSS / Round Bar), excluyendo
        hormigon/pedestales. Pasar family_include=[] para mover todo.
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)

            data = request.data
            if isinstance(data, str):
                data = json.loads(data)
            data = data if isinstance(data, dict) else {}
            try:
                dz_m = float(data.get("dz_m", 0.20))
            except Exception:
                dz_m = 0.20

            fam_include = data.get("family_include", None)
            fam_exclude = data.get("family_exclude",
                                   ["hormign", "hormigon", "concrete", "pedestal"])

            cats = [
                DB.BuiltInCategory.OST_StructuralFraming,
                DB.BuiltInCategory.OST_StructuralColumns,
                DB.BuiltInCategory.OST_StructuralTruss,
            ]

            ids = []
            for cat in cats:
                for el in DB.FilteredElementCollector(doc)\
                         .OfCategory(cat)\
                         .WhereElementIsNotElementType().ToElements():
                    try:
                        fam_name = _norm(get_element_name(el.Symbol.Family))
                    except Exception:
                        continue
                    if fam_exclude and any(s in fam_name for s in fam_exclude):
                        continue
                    if fam_include is not None:
                        if not any(s in fam_name for s in fam_include):
                            continue
                    ids.append(el.Id)

            ids = list(dict.fromkeys(ids))

            debug_norm = data.get("debug", False)
            if debug_norm:
                from collections import defaultdict
                counts = defaultdict(int)
                for cat in cats:
                    for el in DB.FilteredElementCollector(doc)\
                             .OfCategory(cat).WhereElementIsNotElementType()\
                             .ToElements():
                        try:
                            counts[_norm(get_element_name(el.Symbol.Family))] += 1
                        except Exception:
                            counts["<unknown>"] += 1
                return routes.make_response(data={
                    "status": "debug", "family_norm_counts": dict(counts)})

            move_vec = DB.XYZ(0.0, 0.0, dz_m * FT_PER_M)

            moved = 0
            skipped = 0
            errors = []
            t = _new_txn(doc, "Shift steel +{}m".format(dz_m))
            t.Start()
            try:
                for eid in ids:
                    try:
                        DB.ElementTransformUtils.MoveElement(doc, eid, move_vec)
                        moved += 1
                    except Exception as e1:
                        skipped += 1
                        if len(errors) < 5:
                            errors.append(str(e1)[:200])
                t.Commit()
            except Exception:
                try:
                    if t.HasStarted() and not t.HasEnded():
                        t.RollBack()
                except Exception:
                    pass
                raise

            return routes.make_response(data={
                "status": "success",
                "dz_m": dz_m,
                "candidates": len(ids),
                "moved": moved,
                "skipped": skipped,
                "errors": errors,
            })
        except Exception as e:
            log_route_error("shift_steel_up", e)
            logger.error("shift_steel_up failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/rotate_correas/", methods=["POST"])
    def rotate_correas(doc, request):
        """Coloca las correas (HSS100x50x4.5, longitud ~5.05 m, eje Y) encima de
        la brida superior del arco y les aplica el giro de seccion segun la
        pendiente de la curvatura del arco en su posicion X.

        Arco superior: centro (xc, zc) = (11.325, -2.3), R = 14.16 m.

        Por cada correa:
          - offset radial de 0.10 m (50 mm semiprofundidad arco + 50 mm correa)
            para apoyarla sobre la brida.
          - rotacion de seccion (STRUCTURAL_BEND_DIR_ANGLE, rad) = angulo del
            radio del arco en esa X respecto a la vertical.

        Body: {"dry_run": true|false, "offset_m": 0.10}
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) \
                        if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            dry_run = bool(body.get("dry_run", False))
            offset_m = float(body.get("offset_m", 0.10))

            xc = 11.325
            zc = -2.3
            R = 14.16

            cat = DB.BuiltInCategory.OST_StructuralFraming
            correas = []
            for inst in DB.FilteredElementCollector(doc)\
                            .OfCategory(cat)\
                            .WhereElementIsNotElementType()\
                            .ToElements():
                try:
                    tn = _norm(get_element_name(inst.Symbol))
                    if tn != "hss100x50x45":
                        continue
                    loc = inst.Location
                    curve = loc.Curve if hasattr(loc, "Curve") else None
                    if curve is None:
                        continue
                    if not isinstance(curve, DB.Line):
                        continue
                    p = curve.GetEndPoint(0)
                    q = curve.GetEndPoint(1)
                    if abs(curve.Length / FT_PER_M - 5.05) > 0.05:
                        continue
                    x = p.X / FT_PER_M
                    z = p.Z / FT_PER_M
                    correas.append({
                        "id": element_id_value(inst.Id),
                        "eid": inst.Id,
                        "x_m": x, "z_m": z,
                        "p1": [round(p.X / FT_PER_M, 3),
                               round(p.Y / FT_PER_M, 3),
                               round(p.Z / FT_PER_M, 3)],
                        "p2": [round(q.X / FT_PER_M, 3),
                               round(q.Y / FT_PER_M, 3),
                               round(q.Z / FT_PER_M, 3)],
                    })
                except Exception:
                    continue

            results = []
            for c in correas:
                x = c["x_m"]
                rad = math.sqrt(R * R - (x - xc) * (x - xc))
                z_arch = zc + rad
                dxn = (x - xc) / R
                dzn = rad / R
                theta = math.atan2(dzn, dxn) - math.pi / 2.0
                dx_m = dxn * offset_m
                dz_m = dzn * offset_m
                c["z_arch_m"] = round(z_arch, 3)
                c["dx_m"] = round(dx_m, 4)
                c["dz_m"] = round(dz_m, 4)
                c["theta_deg"] = round(math.degrees(theta), 2)
                c["theta_rad"] = round(theta, 6)
                results.append(c)

            moved = 0
            rotated = 0
            skipped = 0
            errors = []
            if not dry_run:
                t = _new_txn(doc, u"Colocar y rotar correas")
                t.Start()
                try:
                    for c in correas:
                        try:
                            el = doc.GetElement(c["eid"])
                            loc = el.Location
                            curve = loc.Curve if hasattr(loc, "Curve") else None
                            if curve is None:
                                skipped += 1
                                continue
                            p = curve.GetEndPoint(0)
                            x = p.X / FT_PER_M
                            z = p.Z / FT_PER_M
                            rad = math.sqrt(
                                R * R - (x - xc) * (x - xc))
                            dxn = (x - xc) / R
                            dzn = rad / R
                            theta = math.atan2(dzn, dxn) - math.pi / 2.0
                            dx_m = dxn * offset_m
                            dz_m = dzn * offset_m
                            DB.ElementTransformUtils.MoveElement(
                                doc, el.Id,
                                DB.XYZ(dx_m * FT_PER_M, 0.0, dz_m * FT_PER_M))
                            moved += 1
                            rot = None
                            for prm in el.Parameters:
                                try:
                                    bn = str(prm.Definition.BuiltInParameter)
                                    if "STRUCTURAL_BEND_DIR_ANGLE" in bn:
                                        rot = prm
                                        break
                                except Exception:
                                    continue
                            if rot is not None:
                                rot.Set(theta)
                                rotated += 1
                        except Exception as e1:
                            skipped += 1
                            if len(errors) < 5:
                                errors.append(str(e1)[:200])
                    t.Commit()
                except Exception:
                    try:
                        if t.HasStarted() and not t.HasEnded():
                            t.RollBack()
                    except Exception:
                        pass
                    raise

            return routes.make_response(data={
                "status": "success",
                "dry_run": dry_run,
                "offset_m": offset_m,
                "correas": len(correas),
                "moved": moved,
                "rotated": rotated,
                "skipped": skipped,
                "errors": errors,
                "sample": results[:6],
            })
        except Exception as e:
            log_route_error("rotate_correas", e)
            logger.error("rotate_correas failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)


    @api.route("/rotate_correas_165/", methods=["POST"])
    def rotate_correas_165(doc, request):
        """Aplica el giro de seccion (STRUCTURAL_BEND_DIR_ANGLE) a las correas
        HSS150x50x3 de 5.05 m creadas por remall_arc_165, segun la curvatura
        del arco superior en su posicion X (centro (11.325,-2.3), R=14.16 m).

        No mueve elementos (remall ya las deja apoyadas con LIFT); solo aplica
        la rotacion de seccion. Body: {"dry_run": true|false}
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) \
                        if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            dry_run = bool(body.get("dry_run", False))
            # Giro de seccion (STRUCTURAL_BEND_DIR_ANGLE, rad) igual al de la
            # base limpia: angulo del radio del arco (centro (11.325,-2.3),
            # R=14.16, LAS correas viven en unidades internas rad y este valor
            # ser almacenado directamente via prm.Set). OJO: los .round(...,5)
            # de este servidor dividen por FT_PER_M al LEER (lo vi en
            # inspect_element), por eso las lecturas historicas parecian
            # ~0.28 rad cuando el valor real es ~0.93 rad (53 deg).
            xc = 11.325
            zc = -2.3
            R = 14.16
            cat = DB.BuiltInCategory.OST_StructuralFraming
            correas = []
            for inst in DB.FilteredElementCollector(doc)\
                            .OfCategory(cat)\
                            .WhereElementIsNotElementType()\
                            .ToElements():
                try:
                    tn = _norm(get_element_name(inst.Symbol))
                    if tn != "hss150x50x3":
                        continue
                    loc = inst.Location
                    curve = loc.Curve if hasattr(loc, "Curve") else None
                    if curve is None or not isinstance(curve, DB.Line):
                        continue
                    if abs(curve.Length / FT_PER_M - 5.05) > 0.05:
                        continue
                    p = curve.GetEndPoint(0)
                    x = p.X / FT_PER_M
                    z = p.Z / FT_PER_M
                    # la correa extrema cae fuera del arco (x=-0.1 / x=22.75):
                    # saturar al extremo del arco (x=0 / x=22.65) igual que la
                    # base limpia (el giro ahi es el del punto de arranque).
                    if x < 0.0:
                        x = 0.0
                    elif x > 22.65:
                        x = 22.65
                    rad = math.sqrt(R * R - (x - xc) * (x - xc))
                    dxn = (x - xc) / R
                    dzn = rad / R
                    theta = math.atan2(dzn, dxn) - math.pi / 2.0
                    rot = None
                    for prm in inst.Parameters:
                        try:
                            bn = str(prm.Definition.BuiltInParameter)
                            if "STRUCTURAL_BEND_DIR_ANGLE" in bn:
                                rot = prm
                                break
                        except Exception:
                            continue
                    correas.append({
                        "id": element_id_value(inst.Id),
                        "eid": inst.Id,
                        "x_m": round(x, 3),
                        "z_m": round(z, 3),
                        "z_arch_m": round(zc + rad, 3),
                        "theta_deg": round(math.degrees(theta), 2),
                        "theta_rad": round(theta, 6),
                        "ref_clean_deg": round(math.degrees(theta), 2),
                        "has_rot": rot is not None,
                    })
                except Exception:
                    continue

            rotated = 0
            skipped = 0
            errors = []
            if not dry_run:
                t = _new_txn(doc, u"Rotar correas HSS150x50x3 por curvatura")
                t.Start()
                try:
                    for c in correas:
                        el = doc.GetElement(c["eid"])
                        theta = c["theta_rad"]
                        done = False
                        for prm in el.Parameters:
                            try:
                                bn = str(prm.Definition.BuiltInParameter)
                                if "STRUCTURAL_BEND_DIR_ANGLE" in bn:
                                    prm.Set(theta)
                                    done = True
                                    break
                            except Exception:
                                continue
                        if done:
                            rotated += 1
                        else:
                            skipped += 1
                    t.Commit()
                except Exception:
                    try:
                        if t.HasStarted() and not t.HasEnded():
                            t.RollBack()
                    except Exception:
                        pass
                    raise

            return routes.make_response(data={
                "status": "success",
                "dry_run": dry_run,
                "correas": len(correas),
                "rotated": rotated,
                "skipped": skipped,
                "errors": errors,
                "sample": correas[:6],
            })
        except Exception as e:
            log_route_error("rotate_correas_165", e)
            logger.error("rotate_correas_165 failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)


    @api.route("/rotate_correas_long/", methods=["POST"])
    def rotate_correas_long(doc, request):
        """Aplica el giro de seccion (STRUCTURAL_BEND_DIR_ANGLE) a las correas
        HSS150x50x3 LARGAS (L~30.3 m, eje Y, las que recorren todo el galpon),
        segun la curvatura del arco superior en su posicion X.

        Es el mismo criterio que rotate_correas_165 (que solo toca las de 5.05 m
        de remall_arc_165): theta = atan2(dzn, dxn) - pi/2 con centro del arco
        (xc,zc)=(11.325,-2.3) y R=14.16, evaluado en la X media de la correa.

        No mueve elementos. Body: {"dry_run": true|false}
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) \
                        if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            dry_run = bool(body.get("dry_run", False))

            xc = 11.325
            zc = -2.3
            R = 14.16
            cat = DB.BuiltInCategory.OST_StructuralFraming
            correas = []
            for inst in DB.FilteredElementCollector(doc)\
                            .OfCategory(cat)\
                            .WhereElementIsNotElementType()\
                            .ToElements():
                try:
                    tn = _norm(get_element_name(inst.Symbol))
                    if tn != "hss150x50x3":
                        continue
                    loc = inst.Location
                    curve = loc.Curve if hasattr(loc, "Curve") else None
                    if curve is None or not isinstance(curve, DB.Line):
                        continue
                    if curve.Length / FT_PER_M < 20.0:
                        continue
                    p = curve.GetEndPoint(0)
                    q = curve.GetEndPoint(1)
                    x = (p.X + q.X) / 2.0 / FT_PER_M
                    if x < 0.0:
                        x = 0.0
                    elif x > 22.65:
                        x = 22.65
                    rad = math.sqrt(R * R - (x - xc) * (x - xc))
                    dxn = (x - xc) / R
                    dzn = rad / R
                    theta = math.atan2(dzn, dxn) - math.pi / 2.0
                    correas.append({
                        "id": element_id_value(inst.Id),
                        "eid": inst.Id,
                        "x_m": round(x, 3),
                        "z_m": round(p.Z / FT_PER_M, 3),
                        "z_arch_m": round(zc + rad, 3),
                        "theta_deg": round(math.degrees(theta), 2),
                        "theta_rad": round(theta, 6),
                    })
                except Exception:
                    continue

            rotated = 0
            skipped = 0
            errors = []
            if not dry_run:
                t = _new_txn(doc, u"Rotar correas largas HSS150x50x3 por curvatura")
                t.Start()
                try:
                    for c in correas:
                        el = doc.GetElement(c["eid"])
                        theta = c["theta_rad"]
                        done = False
                        for prm in el.Parameters:
                            try:
                                bn = str(prm.Definition.BuiltInParameter)
                                if "STRUCTURAL_BEND_DIR_ANGLE" in bn:
                                    prm.Set(theta)
                                    done = True
                                    break
                            except Exception:
                                continue
                        if done:
                            rotated += 1
                        else:
                            skipped += 1
                    t.Commit()
                except Exception:
                    try:
                        if t.HasStarted() and not t.HasEnded():
                            t.RollBack()
                    except Exception:
                        pass
                    raise

            return routes.make_response(data={
                "status": "success",
                "dry_run": dry_run,
                "correas": len(correas),
                "rotated": rotated,
                "skipped": skipped,
                "errors": errors,
                "sample": correas[:6],
            })
        except Exception as e:
            log_route_error("rotate_correas_long", e)
            logger.error("rotate_correas_long failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/diagnose_miters/", methods=["POST"])
    def diagnose_miters(doc, request):
        """SOLO LECTURA. Reporta el estado de cortes/ingletes de todos los
        elementos framing: longitud de sistema vs longitud de corte (si difieren,
        hay corte en angulo = inglete) y si estan unidos por JoinGeometryUtils."""
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            cat = DB.BuiltInCategory.OST_StructuralFraming
            els = DB.FilteredElementCollector(doc)\
                .OfCategory(cat).WhereElementIsNotElementType().ToElements()
            out = []
            mitered = []
            joined = 0
            for el in els:
                try:
                    tn = get_element_name(el.Symbol)
                    sys_len = None
                    cut_len = None
                    for p in el.Parameters:
                        try:
                            name = p.Definition.Name.lower()
                            if "sistema" in name or "system length" in name:
                                if p.HasValue:
                                    sys_len = p.AsDouble()
                            if "corte" in name or "cut length" in name:
                                if p.HasValue:
                                    cut_len = p.AsDouble()
                        except Exception:
                            continue
                    curve = None
                    try:
                        lc = el.Location
                        curve = lc.Curve if hasattr(lc, "Curve") else None
                    except Exception:
                        pass
                    curve_len = curve.Length if curve else None
                    sl = sys_len / FT_PER_M if sys_len else None
                    cl = cut_len / FT_PER_M if cut_len else None
                    cul = curve_len / FT_PER_M if curve_len else None
                    is_miter = (sl is not None and cl is not None and
                                abs(cl - sl) > 0.02)
                    rec = {
                        "id": int(str(el.Id).replace("ElementId(", "").replace(")", "")),
                        "type": tn,
                        "sys_m": round(sl, 4) if sl else None,
                        "cut_m": round(cl, 4) if cl else None,
                        "curve_m": round(cul, 4) if cul else None,
                        "miter": is_miter,
                        "jcount": 0,
                    }
                    try:
                        for p in el.Parameters:
                            try:
                                bn = str(p.Definition.BuiltInParameter)
                                if "JOIN" in bn.upper() and "STATUS" in bn.upper():
                                    rec["join_param"] = bn
                                    try:
                                        rec["join_val"] = p.AsElementId().IntegerValue
                                    except Exception:
                                        pass
                            except Exception:
                                continue
                    except Exception:
                        pass
                    if is_miter:
                        mitered.append(rec["id"])
                    out.append(rec)
                except Exception:
                    continue
            # conteo real de joins por pares en framing
            n = len(els)
            checked_pairs = 0
            for i in range(n):
                for j in range(i + 1, n):
                    try:
                        if DB.JoinGeometryUtils.AreElementsJoined(doc, els[i], els[j]):
                            joined += 1
                    except Exception:
                        pass
                    checked_pairs += 1
                    if checked_pairs > 60000:
                        break
                if checked_pairs > 60000:
                    break
            total = len(out)
            return routes.make_response(data={
                "status": "success",
                "total_framing": total,
                "mitered_count": len(mitered),
                "mitered_ids": mitered[:200],
                "joined_pairs": joined,
                "elements": out,
            })
        except Exception as e:
            log_route_error("diagnose_miters", e)
            logger.error("diagnose_miters failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/inspect_element/", methods=["POST"])
    def inspect_element(doc, request):
        """SOLO LECTURA. Inspecciona un elemento framing por id: tipo, curva,
        parametros de longitud/extension y bbox."""
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) \
                        if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            eid = int(body.get("id", 0))
            el = None
            for inst in DB.FilteredElementCollector(doc)\
                          .WhereElementIsNotElementType()\
                          .ToElements():
                if element_id_value(inst.Id) == eid:
                    el = inst
                    break
            if el is None:
                return routes.make_response(
                    data={"error": "element not found: {}".format(eid)}, status=404)
            out = {
                "id": eid,
                "family": get_element_name(el.Symbol.Family)
                if hasattr(el, "Symbol") and el.Symbol else None,
                "type": get_element_name(el.Symbol)
                if hasattr(el, "Symbol") and el.Symbol else None,
                "params": {},
            }
            for p in el.Parameters:
                try:
                    val = None
                    if p.StorageType == DB.StorageType.Double:
                        if p.HasValue:
                            val = round(p.AsDouble() / FT_PER_M, 5)
                    elif p.StorageType == DB.StorageType.Integer:
                        if p.HasValue:
                            val = p.AsInteger()
                    elif p.StorageType == DB.StorageType.String:
                        if p.HasValue:
                            val = p.AsString()
                    out["params"][str(p.Definition.Name)] = val
                except Exception:
                    continue
            try:
                lc = el.Location
                curve = lc.Curve if hasattr(lc, "Curve") else None
                if curve is not None:
                    out["curve_type"] = type(curve).__name__
                    out["curve_len_m"] = round(curve.Length / FT_PER_M, 5)
                    if isinstance(curve, DB.Line):
                        p = curve.GetEndPoint(0)
                        q = curve.GetEndPoint(1)
                        out["p1_m"] = [round(p.X / FT_PER_M, 4),
                                       round(p.Y / FT_PER_M, 4),
                                       round(p.Z / FT_PER_M, 4)]
                        out["p2_m"] = [round(q.X / FT_PER_M, 4),
                                       round(q.Y / FT_PER_M, 4),
                                       round(q.Z / FT_PER_M, 4)]
                    elif isinstance(curve, DB.Arc):
                        out["radius_m"] = round(curve.Radius / FT_PER_M, 5)
                        ctr = curve.Center
                        out["center_m"] = [round(ctr.X / FT_PER_M, 4),
                                           round(ctr.Y / FT_PER_M, 4),
                                           round(ctr.Z / FT_PER_M, 4)]
                        p = curve.GetEndPoint(0)
                        q = curve.GetEndPoint(1)
                        out["p1_m"] = [round(p.X / FT_PER_M, 4),
                                       round(p.Y / FT_PER_M, 4),
                                       round(p.Z / FT_PER_M, 4)]
                        out["p2_m"] = [round(q.X / FT_PER_M, 4),
                                       round(q.Y / FT_PER_M, 4),
                                       round(q.Z / FT_PER_M, 4)]
            except Exception:
                pass
            try:
                bb = el.get_BoundingBox(None)
                if bb:
                    out["bb_min_m"] = [round(bb.Min.X / FT_PER_M, 4),
                                       round(bb.Min.Y / FT_PER_M, 4),
                                       round(bb.Min.Z / FT_PER_M, 4)]
                    out["bb_max_m"] = [round(bb.Max.X / FT_PER_M, 4),
                                       round(bb.Max.Y / FT_PER_M, 4),
                                       round(bb.Max.Z / FT_PER_M, 4)]
            except Exception:
                pass
            return routes.make_response(data=out)
        except Exception as e:
            log_route_error("inspect_element", e)
            logger.error("inspect_element failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/remove_miters/", methods=["POST"])
    def remove_miters(doc, request):
        """Quita los ingletes (cortes en angulo) de los elementos framing
        aplicando DisallowJoinAtEnd en ambos extremos, dejando cortes
        perpendiculares. Body: {"dry_run": true|false, "types": [...]}"""
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) \
                        if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            dry_run = bool(body.get("dry_run", False))
            typ_filter = set(
                _norm(t) for t in body.get("types") or [])
            cat = DB.BuiltInCategory.OST_StructuralFraming
            els = DB.FilteredElementCollector(doc)\
                .OfCategory(cat).WhereElementIsNotElementType().ToElements()
            changed = []
            errors = []
            t = _new_txn(doc, u"Quitar ingletes (joins de geometria)")
            t.Start()
            try:
                for el in els:
                    try:
                        tn = _norm(get_element_name(el.Symbol))
                        if typ_filter and tn not in typ_filter:
                            continue
                        try:
                            lc = el.Location
                            curve = lc.Curve if hasattr(lc, "Curve") else None
                        except Exception:
                            curve = None
                        if curve is None:
                            continue
                        did = False
                        try:
                            jopt = DB.JoinGeometryOptions()
                            joined_ids = DB.JoinGeometryUtils.GetJoinedElements(
                                doc, el, jopt)
                            for jid in list(joined_ids):
                                try:
                                    other = doc.GetElement(jid)
                                    if other is None:
                                        continue
                                    if DB.JoinGeometryUtils.AreElementsJoined(
                                            doc, el, other):
                                        DB.JoinGeometryUtils.UnjoinGeometry(
                                            doc, el, other)
                                        did = True
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        if did:
                            changed.append(int(str(el.Id).replace(
                                "ElementId(", "").replace(")", "")))
                    except Exception as e1:
                        if len(errors) < 5:
                            errors.append(str(e1)[:200])
                if dry_run:
                    t.RollBack()
                else:
                    t.Commit()
            except Exception:
                try:
                    if t.HasStarted() and not t.HasEnded():
                        t.RollBack()
                except Exception:
                    pass
                raise
            return routes.make_response(data={
                "status": "success",
                "dry_run": dry_run,
                "changed": len(changed),
                "ids": changed[:300],
                "errors": errors,
            })
        except Exception as e:
            log_route_error("remove_miters", e)
            logger.error("remove_miters failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/lift_correas/", methods=["POST"])
    def lift_correas(doc, request):
        """Sube las correas (HSS100x50x4.5, longitud ~5.05, eje Y) de modo que
        su centro quede a R_arco + offset_m radial respecto al centro del arco
        (para apoyarse sobre la brida superior). El offset actual recomendado
        es 0.10 m (50 mm semiprofundidad arco + 50 mm correa).

        Body: {"dry_run": true|false, "offset_m": 0.10}
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) \
                        if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            dry_run = bool(body.get("dry_run", False))
            offset_m = float(body.get("offset_m", 0.10))

            xc = 11.325
            zc = -2.3

            cat = DB.BuiltInCategory.OST_StructuralFraming
            items = []
            for inst in DB.FilteredElementCollector(doc)\
                            .OfCategory(cat)\
                            .WhereElementIsNotElementType()\
                            .ToElements():
                try:
                    tn = _norm(get_element_name(inst.Symbol))
                    if tn != "hss100x50x45":
                        continue
                    lc = inst.Location
                    curve = lc.Curve if hasattr(lc, "Curve") else None
                    if curve is None or not isinstance(curve, DB.Line):
                        continue
                    if abs(curve.Length / FT_PER_M - 5.05) > 0.05:
                        continue
                    p = curve.GetEndPoint(0)
                    x = p.X / FT_PER_M
                    z = p.Z / FT_PER_M
                    r_now = math.sqrt((x - xc) * (x - xc) + (z - zc) * (z - zc))
                    ux = (x - xc) / r_now
                    uz = (z - zc) / r_now
                    items.append({
                        "eid": inst.Id,
                        "x_m": x, "z_m": z,
                        "r_m": r_now,
                        "ux": ux, "uz": uz,
                        "delta_m": offset_m,
                    })
                except Exception:
                    continue
            moved = 0
            skipped = 0
            errors = []
            if not dry_run:
                t = _new_txn(doc, u"Subir correas sobre el arco")
                t.Start()
                try:
                    for it in items:
                        try:
                            el = doc.GetElement(it["eid"])
                            lc = el.Location
                            curve = lc.Curve
                            p = curve.GetEndPoint(0)
                            x = p.X / FT_PER_M
                            z = p.Z / FT_PER_M
                            r_now = math.sqrt((x - xc) ** 2 + (z - zc) ** 2)
                            ux = (x - xc) / r_now
                            uz = (z - zc) / r_now
                            DB.ElementTransformUtils.MoveElement(
                                doc, el.Id,
                                DB.XYZ(ux * offset_m * FT_PER_M, 0.0,
                                       uz * offset_m * FT_PER_M))
                            moved += 1
                        except Exception as e1:
                            skipped += 1
                            if len(errors) < 5:
                                errors.append(str(e1)[:200])
                    t.Commit()
                except Exception:
                    try:
                        if t.HasStarted() and not t.HasEnded():
                            t.RollBack()
                    except Exception:
                        pass
                    raise
            return routes.make_response(data={
                "status": "success",
                "dry_run": dry_run,
                "offset_m": offset_m,
                "correas": len(items),
                "moved": moved,
                "skipped": skipped,
                "errors": errors,
                "sample": [{"x": round(i["x_m"], 3),
                            "z": round(i["z_m"], 3),
                            "r": round(i["r_m"], 3)} for i in items[:6]],
            })
        except Exception as e:
            log_route_error("lift_correas", e)
            logger.error("lift_correas failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/adapt_truss_to_arches/", methods=["POST"])
    def adapt_truss_to_arches(doc, request):
        """Re-adapta el entramado del tijeral al arco ya corregido.

        Tras mover los arcos al centro del .s2k (11.325, -2.5), todos los
        miembros que apoyaban en el arco viejo (centro -2.3) quedaron +0.2 m
        arriba. Como la geometria actual = .s2k + 0.2 m vertical, basta moverlos
        -0.2 m en Z para re-asentarlos EXACTAMENTE sobre los arcos.

        Las correas (HSS100x50x4.5 rectas, L~5.05, eje Y) no se bajan 0.2 sino
        que se mueven RADIALMENTE para dejar su centro a R=14.26 m respecto del
        centro del arco (apoyadas sobre la brida superior: arco R=14.16 + 0.05
        semiprofundidad + 0.05 correa). Los arcos curvos (HSS100x50x3/4.5 con
        LocationCurve Arc) se conservan intactos.

        Body opcional:
          {"dz_m": 0.20, "correa_r_m": 14.26, "dry_run": true|false}
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) \
                        if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            dry_run = bool(body.get("dry_run", False))
            try:
                dz_m = float(body.get("dz_m", 0.20))
            except Exception:
                dz_m = 0.20
            try:
                target_r = float(body.get("correa_r_m", 14.26))
            except Exception:
                target_r = 14.26

            xc, zc = 11.325, -2.5
            vec_down = DB.XYZ(0.0, 0.0, -dz_m * FT_PER_M)

            cat = DB.BuiltInCategory.OST_StructuralFraming
            els = DB.FilteredElementCollector(doc)\
                .OfCategory(cat).WhereElementIsNotElementType().ToElements()

            to_move = []      # (eid, vec)  -> traslacion pura en Z
            correas = []      # (eid, x_m, z_m, r_m) -> correas a mover radial
            arcs_kept = 0
            for inst in els:
                try:
                    lc = inst.Location
                    curve = lc.Curve if hasattr(lc, "Curve") else None
                    if curve is None:
                        continue
                    if isinstance(curve, DB.Arc):
                        arcs_kept += 1
                        continue
                    if not isinstance(curve, DB.Line):
                        continue
                    tn = _norm(get_element_name(inst.Symbol))
                    if tn == "hss100x50x45" and \
                            abs(curve.Length / FT_PER_M - 5.05) < 0.05:
                        p = curve.GetEndPoint(0)
                        x = p.X / FT_PER_M
                        z = p.Z / FT_PER_M
                        r = math.sqrt((x - xc) ** 2 + (z - zc) ** 2)
                        correas.append({
                            "eid": inst.Id, "x_m": x, "z_m": z,
                            "r_m": r, "target_r_m": target_r,
                        })
                        continue
                    to_move.append((inst.Id, vec_down))
                except Exception:
                    continue

            moved_z = 0
            moved_c = 0
            errors = []
            if not dry_run:
                t = _new_txn(doc, u"Adaptar entramado a los arcos")
                t.Start()
                try:
                    for eid, vec in to_move:
                        try:
                            DB.ElementTransformUtils.MoveElement(doc, eid, vec)
                            moved_z += 1
                        except Exception as e1:
                            if len(errors) < 5:
                                errors.append("z: " + str(e1)[:160])
                    for c in correas:
                        try:
                            delta = c["target_r_m"] - c["r_m"]
                            ux = (c["x_m"] - xc) / c["r_m"]
                            uz = (c["z_m"] - zc) / c["r_m"]
                            DB.ElementTransformUtils.MoveElement(
                                doc, c["eid"],
                                DB.XYZ(ux * delta * FT_PER_M, 0.0,
                                       uz * delta * FT_PER_M))
                            moved_c += 1
                        except Exception as e1:
                            if len(errors) < 5:
                                errors.append("correa: " + str(e1)[:160])
                    t.Commit()
                except Exception:
                    try:
                        if t.HasStarted() and not t.HasEnded():
                            t.RollBack()
                    except Exception:
                        pass
                    raise

            return routes.make_response(data={
                "status": "success",
                "dry_run": dry_run,
                "dz_m": dz_m,
                "correa_r_m": target_r,
                "members_to_move": len(to_move),
                "correas_to_move": len(correas),
                "arcs_kept": arcs_kept,
                "moved_z": moved_z,
                "moved_correas": moved_c,
                "correa_sample": [{
                    "x": round(c["x_m"], 3), "z": round(c["z_m"], 3),
                    "r": round(c["r_m"], 3), "delta_m": round(
                        c["target_r_m"] - c["r_m"], 3)} for c in correas[:6]],
                "errors": errors,
            })
        except Exception as e:
            log_route_error("adapt_truss_to_arches", e)
            logger.error("adapt_truss_to_arches failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/recreate_diagonals/", methods=["POST"])
    def recreate_diagonals(doc, request):
        """Recrea las diagonales HSS50x50x2.5 para eliminar los ingletes
        (cortes en angulo quemados en el solido). Borra cada diagonal existente
        y la vuelve a crear con la MI SMA curva (extremos rectos/perpical).

        Body: {"dry_run": true|false}
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) \
                        if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            dry_run = bool(body.get("dry_run", False))

            cat = DB.BuiltInCategory.OST_StructuralFraming
            diags = [e for e in DB.FilteredElementCollector(doc)
                       .OfCategory(cat).WhereElementIsNotElementType()
                       .ToElements() if _is_diag(e)]
            level = lowest_level(doc)

            planned = []
            for d in diags:
                try:
                    dloc = d.Location
                    if not hasattr(dloc, "Curve"):
                        continue
                    dcurve = dloc.Curve
                    if not isinstance(dcurve, DB.Line):
                        continue
                    sym = d.Symbol
                    p0 = dcurve.GetEndPoint(0)
                    p1 = dcurve.GetEndPoint(1)
                    mark = ""
                    mp = d.LookupParameter("Mark")
                    if mp is not None and not mp.IsReadOnly:
                        mv = mp.AsString() or ""
                        mark = mv
                    planned.append({
                        "eid": int(str(d.Id).replace("ElementId(", "").replace(")", "")),
                        "mark": mark,
                        "p0_x": round(p0.X / FT_PER_M, 4),
                        "p0_z": round(p0.Z / FT_PER_M, 4),
                        "p1_x": round(p1.X / FT_PER_M, 4),
                        "p1_z": round(p1.Z / FT_PER_M, 4),
                    })
                except Exception:
                    continue

            if dry_run:
                return routes.make_response(data={
                    "status": "success",
                    "dry_run": True,
                    "total_diags": len(diags),
                    "planned": len(planned),
                    "sample": planned[:8],
                })

            recreated = 0
            skipped = 0
            errors = []
            t = _new_txn(doc, u"Recrear diagonales sin ingletes")
            t.Start()
            try:
                for d in diags:
                    try:
                        dloc = d.Location
                        if not hasattr(dloc, "Curve"):
                            skipped += 1
                            continue
                        dcurve = dloc.Curve
                        if not isinstance(dcurve, DB.Line):
                            skipped += 1
                            continue
                        sym = d.Symbol
                        if not sym.IsActive:
                            sym.Activate()
                        p0 = dcurve.GetEndPoint(0)
                        p1 = dcurve.GetEndPoint(1)
                        mark = ""
                        mp = d.LookupParameter("Mark")
                        if mp is not None and not mp.IsReadOnly:
                            mv = mp.AsString() or ""
                            mark = mv
                        new_line = DB.Line.CreateBound(p0, p1)
                        doc.Delete(d.Id)
                        inst = doc.Create.NewFamilyInstance(
                            new_line, sym, level, DB.Structure.StructuralType.Beam)
                        try:
                            _SFU.DisallowJoinAtEnd(inst, 0)
                            _SFU.DisallowJoinAtEnd(inst, 1)
                        except Exception as je:
                            if len(errors) < 5:
                                errors.append("Disallow:" + str(je)[:120])
                        if mark:
                            nm = inst.LookupParameter("Mark")
                            if nm is not None and not nm.IsReadOnly:
                                try:
                                    nm.Set(mark)
                                except Exception:
                                    pass
                        recreated += 1
                    except Exception as e1:
                        skipped += 1
                        if len(errors) < 5:
                            errors.append(str(e1)[:200])
                t.Commit()
            except Exception:
                try:
                    if t.HasStarted() and not t.HasEnded():
                        t.RollBack()
                except Exception:
                    pass
                raise
            return routes.make_response(data={
                "status": "success",
                "dry_run": dry_run,
                "total_diags": len(planned),
                "recreated": recreated,
                "skipped": skipped,
                "errors": errors,
            })
        except Exception as e:
            log_route_error("recreate_diagonals", e)
            logger.error("recreate_diagonals failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/check_truss_gaps/", methods=["POST"])
    def check_truss_gaps(doc, request):
        """SOLO LECTURA. Coherencia del tigeral: compara cada extremo de los
        miembros (montantes verticales, diagonales HSS50x50x2.5, correas) contra
        la curva de la cuerda superior (HSS100x50x3). Reporta el gap (distancia
        del extremo a la curva) y el radio actual de cada arco para detectar
        desplazamientos respecto al diseno (R sup=14.16, R inf=13.66, centro
        (11.325, -2.500)).
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            cat = DB.BuiltInCategory.OST_StructuralFraming
            els = DB.FilteredElementCollector(doc)\
                .OfCategory(cat).WhereElementIsNotElementType().ToElements()

            arcs_sup = []
            arcs_inf = []
            members = []
            for el in els:
                try:
                    tn = _norm(get_element_name(el.Symbol))
                    lc = el.Location
                    curve = lc.Curve if hasattr(lc, "Curve") else None
                    if curve is None:
                        continue
                    if tn == "hss100x50x3":
                        arcs_sup.append((el, curve))
                    elif tn == "hss100x50x45":
                        if isinstance(curve, DB.Arc):
                            arcs_inf.append((el, curve))
                        else:
                            members.append((el, tn, curve))
                    else:
                        members.append((el, tn, curve))
                except Exception:
                    continue

            arc_report = []
            for lab, arcs in (("sup", arcs_sup), ("inf", arcs_inf)):
                if not arcs:
                    continue
                for el, ac in arcs:
                    try:
                        if isinstance(ac, DB.Arc):
                            center = ac.Center
                            r = ac.Radius / FT_PER_M
                            arc_report.append({
                                "arc": lab,
                                "id": int(str(el.Id).replace("ElementId(", "").replace(")", "")),
                                "type": _norm(get_element_name(el.Symbol)),
                                "R_m": round(r, 4),
                                "cx_m": round(center.X / FT_PER_M, 4),
                                "cz_m": round(center.Z / FT_PER_M, 4),
                            })
                    except Exception:
                        continue

            gaps = []
            sup_curves = [c for _, c in arcs_sup]
            for el, tn, curve in members:
                try:
                    p0 = curve.GetEndPoint(0)
                    p1 = curve.GetEndPoint(1)
                    # extremo ALTO (mayor Z radial) es el que debe tocar la cuerda sup
                    hi = p0 if p0.Z >= p1.Z else p1
                    best = None
                    for ac in sup_curves:
                        try:
                            pr = ac.Project(hi)
                            if pr and (best is None or pr.Distance < best[0]):
                                best = (pr.Distance, pr.XYZPoint)
                        except Exception:
                            pass
                    if best is not None:
                        gap_m = best[0] / FT_PER_M
                        # radio radial del extremo-alto respecto al centro del arco
                        rhi_m = None
                        sup_c = DB.XYZ(0, 0, 0)
                        for el2, ac2 in arcs_sup:
                            try:
                                if isinstance(ac2, DB.Arc):
                                    sup_c = ac2.Center
                                    break
                            except Exception:
                                pass
                        rhi_m = math.sqrt(
                            (hi.X - sup_c.X) ** 2 + (hi.Z - sup_c.Z) ** 2) / FT_PER_M
                        gaps.append({
                            "id": int(str(el.Id).replace("ElementId(", "").replace(")", "")),
                            "type": tn,
                            "end_x": round(hi.X / FT_PER_M, 3),
                            "end_z": round(hi.Z / FT_PER_M, 3),
                            "gap_m": round(gap_m, 4),
                            "r_hi_m": round(rhi_m, 4) if rhi_m else None,
                        })
                except Exception:
                    continue

            gaps.sort(key=lambda g: -g["gap_m"])
            return routes.make_response(data={
                "status": "success",
                "arcs": arc_report,
                "n_arcs_sup": len(arcs_sup),
                "n_arcs_inf": len(arcs_inf),
                "n_members": len(members),
                "gaps_over_005": [g for g in gaps if g["gap_m"] > 0.05],
                "worst10": gaps[:10],
            })
        except Exception as e:
            log_route_error("check_truss_gaps", e)
            logger.error("check_truss_gaps failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/restore_arches/", methods=["POST"])
    def restore_arches(doc, request):
        """Recrea los arcos (7 superiores HSS100x50x3 + 7 inferiores HSS100x50x4.5)
        con la geometria exacta de diseno del .s2k:
          - Sup:  centro (11.325, -2.5), R=14.16, nodos (0,6) / (11.325,11.66) / (22.65,6)
          - Inf:  centro (11.325, -2.5), R=13.66, nodos (0.4,5.7) / (11.325,11.16) / (22.25,5.7)
        Preserva la coordenada Y de cada plano existente y el Mark.
        Body: {"dry_run": true|false}
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) \
                        if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            dry_run = bool(body.get("dry_run", False))

            DESIGN = {
                "hss100x50x3": {
                    "start": [0.0, 0.0, 6.0],
                    "mid": [11.325, 0.0, 11.66],
                    "end": [22.65, 0.0, 6.0],
                    "R": 14.16,
                },
                "hss100x50x45": {
                    "start": [0.4, 0.0, 5.7],
                    "mid": [11.325, 0.0, 11.16],
                    "end": [22.25, 0.0, 5.7],
                    "R": 13.66,
                },
            }

            cat = DB.BuiltInCategory.OST_StructuralFraming
            arcs = []
            for el in DB.FilteredElementCollector(doc)\
                           .OfCategory(cat).WhereElementIsNotElementType()\
                           .ToElements():
                try:
                    tn = _norm(get_element_name(el.Symbol))
                    if tn not in DESIGN:
                        continue
                    lc = el.Location
                    curve = lc.Curve if hasattr(lc, "Curve") else None
                    if curve is None or not isinstance(curve, DB.Arc):
                        continue
                    y = curve.GetEndPoint(0).Y / FT_PER_M
                    mark = ""
                    mp = el.LookupParameter("Mark")
                    if mp is not None and not mp.IsReadOnly:
                        mv = mp.AsString() or ""
                        mark = mv
                    arcs.append({"el": el, "tn": tn, "y": y, "mark": mark,
                                 "sym": el.Symbol})
                except Exception:
                    continue

            if dry_run:
                return routes.make_response(data={
                    "status": "success",
                    "dry_run": True,
                    "planned": len(arcs),
                    "sample": [{"type": a["tn"], "y": round(a["y"], 3)}
                               for a in arcs[:8]],
                })

            level = lowest_level(doc)
            recreated = 0
            skipped = 0
            errors = []
            t = _new_txn(doc, u"Restaurar arcos al diseno s2k")
            t.Start()
            try:
                for a in arcs:
                    try:
                        d = DESIGN[a["tn"]]
                        sym = a["sym"]
                        if not sym.IsActive:
                            sym.Activate()
                        start = _xyz([d["start"][0], a["y"], d["start"][2]])
                        mid = _xyz([d["mid"][0], a["y"], d["mid"][2]])
                        end = _xyz([d["end"][0], a["y"], d["end"][2]])
                        arc = DB.Arc.Create(start, end, mid)
                        doc.Delete(a["el"].Id)
                        inst = doc.Create.NewFamilyInstance(
                            arc, sym, level, DB.Structure.StructuralType.Beam)
                        if a["mark"]:
                            nm = inst.LookupParameter("Mark")
                            if nm is not None and not nm.IsReadOnly:
                                try:
                                    nm.Set(a["mark"])
                                except Exception:
                                    pass
                        recreated += 1
                    except Exception as e1:
                        skipped += 1
                        if len(errors) < 5:
                            errors.append(str(e1)[:200])
                t.Commit()
            except Exception:
                try:
                    if t.HasStarted() and not t.HasEnded():
                        t.RollBack()
                except Exception:
                    pass
                raise
            return routes.make_response(data={
                "status": "success",
                "dry_run": dry_run,
                "planned": len(arcs),
                "recreated": recreated,
                "skipped": skipped,
                "errors": errors,
            })
        except Exception as e:
            log_route_error("restore_arches", e)
            logger.error("restore_arches failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/snap_web_to_chords/", methods=["POST"])
    def snap_web_to_chords(doc, request):
        """Re-apunta los extremos de los miembros verticales y diagonales del
        tigeral (HSS50x50x2.5) a las CUERDAS (arcos R sup=14.16 / R inf=13.66).
        Proyecta cada extremo del miembro sobre la curva Arc MAS CERCANA (de las
        14 reales) y recrea el miembro con el extremo tocando la cuerda.

        Body: {"dry_run": true|false, "tol_m": 0.30}
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) \
                        if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            dry_run = bool(body.get("dry_run", False))
            tol_m = float(body.get("tol_m", 0.30))
            TOL = tol_m * FT_PER_M

            cat = DB.BuiltInCategory.OST_StructuralFraming
            # SOLO curvas de arco reales
            arch_curves = []
            for el in DB.FilteredElementCollector(doc)\
                           .OfCategory(cat).WhereElementIsNotElementType()\
                           .ToElements():
                try:
                    tn = _norm(get_element_name(el.Symbol))
                    if tn not in ("hss100x50x3", "hss100x50x45"):
                        continue
                    lc = el.Location
                    curve = lc.Curve if hasattr(lc, "Curve") else None
                    if curve is not None and isinstance(curve, DB.Arc):
                        arch_curves.append(curve)
                except Exception:
                    continue

            members = [e for e in DB.FilteredElementCollector(doc)
                       .OfCategory(cat).WhereElementIsNotElementType()
                       .ToElements() if _is_diag(e)]
            level = lowest_level(doc)

            def nearest(pt):
                best = None
                for ac in arch_curves:
                    try:
                        pr = ac.Project(pt)
                        if pr and (best is None or pr.Distance < best[0]):
                            best = (pr.Distance, pr.XYZPoint)
                    except Exception:
                        pass
                return best

            planned = 0
            details = []
            for m in members:
                try:
                    mloc = m.Location
                    mcurve = mloc.Curve if hasattr(mloc, "Curve") else None
                    if mcurve is None or not isinstance(mcurve, DB.Line):
                        continue
                    p0 = mcurve.GetEndPoint(0)
                    p1 = mcurve.GetEndPoint(1)
                    b0 = nearest(p0)
                    b1 = nearest(p1)
                    if b0 is None or b1 is None:
                        continue
                    if b0[0] <= TOL and b1[0] <= TOL:
                        new_line = DB.Line.CreateBound(b0[1], b1[1])
                        details.append({
                            "id": int(str(m.Id).replace("ElementId(", "").replace(")", "")),
                            "old0": [round(p0.X / FT_PER_M, 3), round(p0.Z / FT_PER_M, 3)],
                            "new0": [round(b0[1].X / FT_PER_M, 3), round(b0[1].Z / FT_PER_M, 3)],
                            "old1": [round(p1.X / FT_PER_M, 3), round(p1.Z / FT_PER_M, 3)],
                            "new1": [round(b1[1].X / FT_PER_M, 3), round(b1[1].Z / FT_PER_M, 3)],
                        })
                        planned += 1
                except Exception:
                    continue

            if dry_run:
                return routes.make_response(data={
                    "status": "success",
                    "dry_run": True,
                    "arch_curves": len(arch_curves),
                    "planned": planned,
                    "sample": details[:6],
                })

            recreated = 0
            skipped = 0
            errors = []
            t = _new_txn(doc, u"Apuntar miembros a cuerdas")
            t.Start()
            try:
                for m in members:
                    try:
                        mloc = m.Location
                        mcurve = mloc.Curve if hasattr(mloc, "Curve") else None
                        if mcurve is None or not isinstance(mcurve, DB.Line):
                            skipped += 1
                            continue
                        p0 = mcurve.GetEndPoint(0)
                        p1 = mcurve.GetEndPoint(1)
                        b0 = nearest(p0)
                        b1 = nearest(p1)
                        if b0 is None or b1 is None:
                            skipped += 1
                            continue
                        if b0[0] > TOL or b1[0] > TOL:
                            skipped += 1
                            continue
                        sym = m.Symbol
                        if not sym.IsActive:
                            sym.Activate()
                        new_line = DB.Line.CreateBound(b0[1], b1[1])
                        doc.Delete(m.Id)
                        inst = doc.Create.NewFamilyInstance(
                            new_line, sym, level, DB.Structure.StructuralType.Beam)
                        try:
                            _SFU.DisallowJoinAtEnd(inst, 0)
                            _SFU.DisallowJoinAtEnd(inst, 1)
                        except Exception:
                            pass
                        recreated += 1
                    except Exception as e1:
                        skipped += 1
                        if len(errors) < 5:
                            errors.append(str(e1)[:200])
                t.Commit()
            except Exception:
                try:
                    if t.HasStarted() and not t.HasEnded():
                        t.RollBack()
                except Exception:
                    pass
                raise
            return routes.make_response(data={
                "status": "success",
                "dry_run": dry_run,
                "arch_curves": len(arch_curves),
                "recreated": recreated,
                "skipped": skipped,
                "errors": errors,
            })
        except Exception as e:
            log_route_error("snap_web_to_chords", e)
            logger.error("snap_web_to_chords failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/diagnose_montants/", methods=["POST"])
    def diagnose_montants(doc, request):
        """SOLO LECTURA. Para cada tijeral (plano Y unico) identifica los
        miembros del entramado (HSS50x50x2.5 / HSS50x50x2, largos < 3 m) y
        reporta cual es la MONTANTE CENTRAL (extremo en el centro x=11.325 del
        cordon superior) y su inclinacion (dx horizontal entre extremos).

        Una montante central correcta es RECTA VERTICAL: |dx| < 2 cm.
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            members = [e for e in DB.FilteredElementCollector(doc)
                       .OfCategory(DB.BuiltInCategory.OST_StructuralFraming)
                       .WhereElementIsNotElementType().ToElements()
                       if _is_member_web(e)]
            planes = {}
            for m in members:
                try:
                    lc = m.Location
                    c = lc.Curve if hasattr(lc, "Curve") else None
                    if c is None or not isinstance(c, DB.Line):
                        continue
                    p = c.GetEndPoint(0)
                    q = c.GetEndPoint(1)
                    y = round((p.Y + q.Y) / 2.0 / FT_PER_M, 3)
                    planes.setdefault(y, []).append({
                        "id": int(str(m.Id).replace("ElementId(", "").replace(")", "")),
                        "type": _norm(get_element_name(m.Symbol)),
                        "p1": [round(p.X / FT_PER_M, 3), round(p.Z / FT_PER_M, 3)],
                        "p2": [round(q.X / FT_PER_M, 3), round(q.Z / FT_PER_M, 3)],
                    })
                except Exception:
                    continue
            out = []
            for y, items in sorted(planes.items()):
                # montante central = extremo con x mas cercana a centro (11.325)
                # y con longitud vertical tipica (< = 2.5 m) que tope el cordeue sup
                centers = []
                for it in items:
                    dxa = abs(it["p1"][0] - 11.325)
                    dxb = abs(it["p2"][0] - 11.325)
                    xmin = min(it["p1"][0], it["p2"][0])
                    xmax = max(it["p1"][0], it["p2"][0])
                    if xmin <= 11.33 and xmax >= 11.32:
                        lenxy = abs(it["p2"][1] - it["p1"][1])
                        if lenxy < 4.0:
                            q0 = it["p1"] if it["p1"][1] > it["p2"][1] else it["p2"]
                            d = {"y": y, "id": it["id"], "type": it["type"],
                                 "top": q0, "dx": it["p2"][0] - it["p1"][0],
                                 "len_z": lenxy, "cent_x": min(dxa, dxb)}
                            d["inclined"] = abs(d["dx"]) > 0.02
                            centers.append(d)
                out.extend(centers)
            return routes.make_response(data={
                "status": "success",
                "memb_planes": len(planes),
                "central_candidates": len(out),
                "inclined": [c for c in out if c["inclined"]],
                "all": out,
            })
        except Exception as e:
            log_route_error("diagnose_montants", e)
            logger.error("diagnose_montants failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/fix_central_montants/", methods=["POST"])
    def fix_central_montants(doc, request):
        """Reconstruye las 7 MONTANTES CENTRALES de cada tijeral como RECTAS
        VERTICALES exactas, segun el s2k:
          nodo superior (x=11.325, z=11.66) <-> nodo inferior (x=11.325, z=11.16)
        en cada eje Y = 0, 5.05, 10.1, 15.15, 20.2, 25.25, 30.3 (Longitud 0.5 m).

        detecta por quebrada del entramado el miembro HSS50x50x2.5 cuyo bbox
        cruza el centro x=11.325 y le fija geometria vertical (linea de 0.5 m).
        Body: {"dry_run": true|false}
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) \
                        if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            dry_run = bool(body.get("dry_run", False))
            FT = FT_PER_M

            XC = 11.325
            ZUP = 11.66
            ZLO = 11.16
            LEVELS = [0.0, 5.05, 10.1, 15.15, 20.2, 25.25, 30.3]

            members = [e for e in DB.FilteredElementCollector(doc)
                       .OfCategory(DB.BuiltInCategory.OST_StructuralFraming)
                       .WhereElementIsNotElementType().ToElements()
                       if _is_member_web(e)]

            def is_vertical(x):
                return abs(x - XC) < 0.03

            planned = []
            seen = set()
            found_levels = set()
            for m in members:
                try:
                    lc = m.Location
                    c = lc.Curve if hasattr(lc, "Curve") else None
                    if c is None or not isinstance(c, DB.Line):
                        continue
                    p = c.GetEndPoint(0)
                    q = c.GetEndPoint(1)
                    xa, xb = p.X / FT, q.X / FT
                    ya, yb = p.Y / FT, q.Y / FT
                    za, zb = p.Z / FT, q.Z / FT
                    # cruza el centro y es corto (< 3 m)
                    if min(xa, xb) <= XC + 0.02 and max(xa, xb) >= XC - 0.02 \
                       and max(za, zb) - min(za, zb) < 3.0 \
                       and abs(ya - yb) < 0.02:
                        y = round((ya + yb) / 2.0, 2)
                        if any(abs(y - pl) < 0.1 for pl in LEVELS):
                            eid = int(str(m.Id).replace("ElementId(", "").replace(")", ""))
                            if eid in seen:
                                continue
                            seen.add(eid)
                            found_levels.add(y)
                            planned.append({
                                "id": eid, "y": y,
                                "type": _norm(get_element_name(m.Symbol)),
                                "sym_name": get_element_name(m.Symbol),
                                "old_p1": [round(xa, 3), round(ya, 3), round(za, 3)],
                                "old_p2": [round(xb, 3), round(yb, 3), round(zb, 3)],
                                "new_p1": [XC, y, ZLO],
                                "new_p2": [XC, y, ZUP],
                            })
                except Exception:
                    continue

            # si falta alguna montante central (p. ej. ya borrada), planificarla
            # como creacion nueva usando el simbolo de cualquier HSS50x50x2.5
            # existente en el modelo
            fallback_sym = None
            for m in members:
                try:
                    if _norm(get_element_name(m.Symbol)) == "hss50x50x25":
                        fallback_sym = get_element_name(m.Symbol)
                        break
                except Exception:
                    continue
            for pl in LEVELS:
                y = round(pl, 2)
                if any(abs(y - d["y"]) < 0.1 for d in planned):
                    continue
                planned.append({
                    "id": None, "y": y,
                    "type": "hss50x50x25",
                    "sym_name": fallback_sym,
                    "old_p1": None, "old_p2": None,
                    "new_p1": [XC, y, ZLO],
                    "new_p2": [XC, y, ZUP],
                })

            planned = sorted(planned, key=lambda d: d["y"])
            if dry_run:
                return routes.make_response(data={
                    "status": "success", "dry_run": True,
                    "planned": planned,
                })

            level = lowest_level(doc)
            wanted = set(d["id"] for d in planned if d["id"] is not None)

            # --- Txn 1: borrar las centrales viejas (solo las que existen) ---
            _mark("fix_central: txn1 delete")
            t = _new_txn(doc, u"Enderezar montantes centrales: borrar")
            t.Start()
            deleted = 0
            try:
                for m in members:
                    mid = int(str(m.Id).replace("ElementId(", "").replace(")", ""))
                    if mid in wanted:
                        doc.Delete(m.Id)
                        deleted += 1
                t.Commit()
            except Exception:
                try:
                    if t.HasStarted() and not t.HasEnded():
                        t.RollBack()
                except Exception:
                    pass
                raise
            _mark("fix_central: txn1 done deleted={}".format(deleted))

            # --- Txn 2: crear las verticales desplazadas en X (no tocan las
            # cuerdas, evita el calculo de corte) ---
            _mark("fix_central: txn2 create")
            created_ids = []
            t = _new_txn(doc, u"Enderezar montantes centrales: crear")
            t.Start()
            try:
                # capturar los avisos/errores reales de Revit en vez de tragarlos
                class _Cap(DB.IFailuresPreprocessor):
                    def PreprocessFailures(self, fa):
                        try:
                            for f in fa.GetFailureMessages():
                                try:
                                    _mark("fix_central FAIL: {} :: {}".format(
                                        f.GetSeverity(), f.GetDescriptionText()))
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        return DB.FailureProcessingResult.ProceedWithCommit
                try:
                    opts = doc.GetFailureHandlingOptions()
                    opts.SetFailuresPreprocessor(_Cap())
                    t.SetFailureHandlingOptions(opts)
                except Exception:
                    pass
                # symbol REAL y activo: tomado de un miembro HSS50x50x2.5 vivo
                live_sym = None
                for el in members:
                    try:
                        if _norm(get_element_name(el.Symbol)) == "hss50x50x25":
                            live_sym = el.Symbol
                            break
                    except Exception:
                        continue
                if live_sym is not None and not live_sym.IsActive:
                    live_sym.Activate()
                _mark("fix_central: txn2 live_sym={}".format(
                    get_element_name(live_sym) if live_sym else None))
                for d in planned:
                    y = d["y"]
                    sym = live_sym
                    if sym is None:
                        _mark("fix_central: txn2 sym MISSING y={}".format(y))
                        continue
                    off_x = 4.0  # desplazada 4 m para evitar cortes
                    line = DB.Line.CreateBound(
                        DB.XYZ((XC + off_x) * FT, y * FT, ZLO * FT),
                        DB.XYZ((XC + off_x) * FT, y * FT, ZUP * FT))
                    # vertical -> Brace (igual que import_s2k: dz > TOL usa
                    # StructuralType.Brace; un Beam vertical devuelve None)
                    inst = None
                    try:
                        inst = doc.Create.NewFamilyInstance(
                            line, sym, level, DB.Structure.StructuralType.Brace)
                    except Exception as e1:
                        _mark("fix_central: txn2 Brace err y={} {}".format(y, str(e1)[:120]))
                    if inst is None:
                        try:
                            inst = doc.Create.NewFamilyInstance(
                                line, sym, level, DB.Structure.StructuralType.Beam)
                        except Exception as e2:
                            _mark("fix_central: txn2 Beam err y={} {}".format(y, str(e2)[:120]))
                    if inst is None:
                        try:
                            inst = doc.Create.NewFamilyInstance(
                                line, sym, level)
                        except Exception as e3:
                            _mark("fix_central: txn2 noStype err y={} {}".format(y, str(e3)[:120]))
                    if inst is None:
                        _mark("fix_central: txn2 inst NONE y={}".format(y))
                    else:
                        # desunir ANTES de mover: evita que el join estire el
                        # miembro hacia las cuerdas al desplazarlo
                        try:
                            _SFU.DisallowJoinAtEnd(inst, 0)
                            _SFU.DisallowJoinAtEnd(inst, 1)
                        except Exception as e4:
                            _mark("fix_central: txn2 disallow err y={} {}".format(y, str(e4)[:120]))
                    created_ids.append((inst, y))
                t.Commit()
            except Exception:
                try:
                    if t.HasStarted() and not t.HasEnded():
                        t.RollBack()
                except Exception:
                    pass
                raise
            _mark("fix_central: txn2 done n={}".format(len(created_ids)))

            # --- Txn 3: mover cada nueva al centro exacto y desunir ---
            _mark("fix_central: txn3 move")
            t = _new_txn(doc, u"Enderezar montantes centrales: mover")
            t.Start()
            moved = 0
            try:
                for inst, y in created_ids:
                    if inst is None:
                        continue
                    vec = DB.XYZ(-4.0 * FT, 0.0, 0.0)
                    DB.ElementTransformUtils.MoveElement(doc, inst.Id, vec)
                    try:
                        _SFU.DisallowJoinAtEnd(inst, 0)
                        _SFU.DisallowJoinAtEnd(inst, 1)
                    except Exception:
                        pass
                    moved += 1
                t.Commit()
            except Exception:
                try:
                    if t.HasStarted() and not t.HasEnded():
                        t.RollBack()
                except Exception:
                    pass
                raise
            _mark("fix_central: txn3 done moved={}".format(moved))

            return routes.make_response(data={
                "status": "success", "dry_run": dry_run,
                "deleted": deleted,
                "created": len(created_ids),
                "moved": moved,
                "planned_count": len(planned),
            })
        except Exception as e:
            log_route_error("fix_central_montants", e)
            logger.error("fix_central_montants failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/fix_truss_nodes/", methods=["POST"])
    def fix_truss_nodes(doc, request):
        """Corrige el entramado de los tijerales SOLO con coordenadas del modelo
        actual (no usa el s2k). Para cada plano Y detecta la geometria real y:

          1. NUDO CENTRAL: re-apunta las 2 diagonales centrales (las que suben
             al montante central) para que su extremo superior quede EXACTA-
             MENTE en el tope del montante central detectado en el modelo.
          2. MONTANTE DE EXTREMO: crea un montante vertical (mismo simbolo que
             el entramado) en x=0.40, desde la brida inferior hasta la brida
             superior reales (los arcos existentes en ese plano Y).
          3. CORREAS: alinea cada correa (HSS100x50x4.5, direccion Y) al nodo
             real mas cercano de la brida superior, recomputando su Z para
             conservar el radio del arco en el que ya estaba.

        Body: {"dry_run": true|false, "fix_center": true, "add_edge_montants":
               true, "align_purlins": true}
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) \
                        if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            dry_run = bool(body.get("dry_run", False))
            do_center = bool(body.get("fix_center", True))
            do_edge = bool(body.get("add_edge_montants", True))
            do_purlins = bool(body.get("align_purlins", True))
            FT = FT_PER_M

            cat = DB.BuiltInCategory.OST_StructuralFraming
            els = DB.FilteredElementCollector(doc)\
                .OfCategory(cat).WhereElementIsNotElementType().ToElements()

            web = []
            tops = []
            bots = []
            purlins = []
            for el in els:
                try:
                    lc = el.Location
                    curve = lc.Curve if hasattr(lc, "Curve") else None
                    if curve is None:
                        continue
                    tn = _norm(get_element_name(el.Symbol))
                    if _is_member_web(el):
                        if isinstance(curve, DB.Line):
                            web.append((el, curve))
                    elif tn == "hss100x50x3":
                        if isinstance(curve, DB.Arc):
                            tops.append((el, curve))
                    elif tn == "hss100x50x45":
                        if isinstance(curve, DB.Arc):
                            bots.append((el, curve))
                        elif isinstance(curve, DB.Line):
                            p = curve.GetEndPoint(0)
                            q = curve.GetEndPoint(1)
                            if abs(p.Y - q.Y) > 0.5 * FT and abs(p.X - q.X) < 0.1 * FT:
                                purlins.append((el, curve))
                except Exception:
                    continue

            def arc_z(arc, x_m):
                c = arc.Center
                r = arc.Radius / FT
                dx = x_m - c.X / FT
                d2 = r * r - dx * dx
                if d2 < 0:
                    return None
                return c.Z / FT + math.sqrt(d2)

            planes = {}
            for el, c in web:
                p = c.GetEndPoint(0)
                q = c.GetEndPoint(1)
                y = round((p.Y + q.Y) / 2.0 / FT, 2)
                planes.setdefault(y, []).append((el, c))

            node_xs = set()
            level = lowest_level(doc)
            web_sym = None
            plan = []
            center_els = {}
            purlin_els = {}

            for y in sorted(planes):
                mems = planes[y]
                top_arc = None
                bot_arc = None
                for el, c in tops:
                    if abs(c.Center.Y / FT - y) < 0.05:
                        top_arc = c
                        break
                for el, c in bots:
                    if abs(c.Center.Y / FT - y) < 0.05:
                        bot_arc = c
                        break

                # montante central real: vertical corto que cruza x=11.325
                mont = None
                for el, c in mems:
                    p = c.GetEndPoint(0)
                    q = c.GetEndPoint(1)
                    xa, xb = p.X / FT, q.X / FT
                    za, zb = p.Z / FT, q.Z / FT
                    if min(xa, xb) <= 11.325 + 0.03 and max(xa, xb) >= 11.325 - 0.03 \
                       and abs(za - zb) < 3.0:
                        mont = (el, c)
                        break
                mont_top = None
                if mont is not None:
                    p = mont[1].GetEndPoint(0)
                    q = mont[1].GetEndPoint(1)
                    mont_top = q if q.Z >= p.Z else p
                if web_sym is None:
                    for el, c in mems:
                        web_sym = el.Symbol
                        if not web_sym.IsActive:
                            web_sym.Activate()
                        break

                mont_id = None
                if mont is not None:
                    mont_id = int(str(mont[0].Id).replace("ElementId(", "").replace(")", ""))

                ctop = None
                if mont_top is not None:
                    ctop = (mont_top.X / FT, mont_top.Y / FT, mont_top.Z / FT)

                # 1) nodo central: diagonales cuyo extremo superior queda cerca
                #    del tope del montante (gap < 0.4 m) sin ser el montante
                center_fix = []
                if do_center and ctop is not None:
                    for el, c in mems:
                        eid = int(str(el.Id).replace("ElementId(", "").replace(")", ""))
                        if mont_id is not None and mont_id == eid:
                            continue
                        p = c.GetEndPoint(0)
                        q = c.GetEndPoint(1)
                        hi = q if q.Z >= p.Z else p
                        hx, hz = hi.X / FT, hi.Z / FT
                        if 0.01 < math.hypot(hx - ctop[0], hz - ctop[2]) < 0.4:
                            center_fix.append({
                                "y": y,
                                "id": eid,
                                "el": el,
                                "old_top": [round(hx, 3), round(hz, 3)],
                                "new_top": [round(ctop[0], 3), round(ctop[2], 3)],
                            })
                            center_els[eid] = el
                            plan.append({"type": "center_diag", "y": y,
                                         "id": eid,
                                         "old": center_fix[-1]["old_top"],
                                         "new": center_fix[-1]["new_top"]})

                # nodos reales de la brida superior = extremo superior de cada
                # miembro (el que toca el arco sup). Se excluyen las diagonales
                # centrales que aun no tocan la brida (gap < 0.4 al nudo).
                for el, c in mems:
                    if mont_id is not None and mont_id == \
                       int(str(el.Id).replace("ElementId(", "").replace(")", "")):
                        continue
                    p = c.GetEndPoint(0)
                    q = c.GetEndPoint(1)
                    hi = q if q.Z >= p.Z else p
                    hx, hz = hi.X / FT, hi.Z / FT
                    if ctop is not None and math.hypot(hx - ctop[0], hz - ctop[2]) < 0.4:
                        continue
                    node_xs.add(round(hx, 2))
                if ctop is not None:
                    node_xs.add(round(ctop[0], 2))

                # 2) montante de extremo en x=0.40 sobre arcos reales.
                #    Idempotente: si ya existe un vertical cerca de x=0.40 en
                #    este plano no se planifica otra creacion.
                if do_edge and top_arc is not None and bot_arc is not None:
                    already = False
                    for el, c in mems:
                        pa = c.GetEndPoint(0)
                        qa = c.GetEndPoint(1)
                        xa0, xa1 = pa.X / FT, qa.X / FT
                        za0, za1 = pa.Z / FT, qa.Z / FT
                        if min(xa0, xa1) <= 0.40 + 0.05 and max(xa0, xa1) >= 0.40 - 0.05 \
                           and abs(xa0 - xa1) < 0.03 and abs(za0 - za1) > 0.5:
                            already = True
                            break
                    if not already:
                        zt = arc_z(top_arc, 0.40)
                        zb = arc_z(bot_arc, 0.40)
                        if zt is not None and zb is not None:
                            plan.append({
                                "type": "edge_montant", "y": y, "x": 0.40,
                                "from": [0.40, y, round(zb, 3)],
                                "to": [0.40, y, round(zt, 3)],
                            })

            # 3) correas: mapeo X actual -> nodo real mas cercano
            purlin_plan = []
            if do_purlins and node_xs:
                sorted_nodes = sorted(node_xs)
                cx, cz = 11.325, -2.5
                for el, c in purlins:
                    p = c.GetEndPoint(0)
                    x_m = p.X / FT
                    nearest = min(sorted_nodes, key=lambda nx: abs(nx - x_m))
                    if abs(nearest - x_m) < 0.005:
                        continue
                    r = math.hypot(x_m - cx, p.Z / FT - cz)
                    nz = cz + math.sqrt(r * r - (nearest - cx) ** 2)
                    cur = c.GetEndPoint(0)
                    q = c.GetEndPoint(1)
                    y_a, y_b = cur.Y / FT, q.Y / FT
                    z_a, z_b = cur.Z / FT, q.Z / FT
                    purlin_plan.append({
                        "id": int(str(el.Id).replace("ElementId(", "").replace(")", "")),
                        "x_old": round(x_m, 3),
                        "x_new": round(nearest, 3),
                        "z_old": round(z_a, 3),
                        "z_new": round(nz, 3),
                        "y": [round(y_a, 2), round(y_b, 2)],
                    })
                    purlin_els[purlin_plan[-1]["id"]] = el

            if dry_run:
                return routes.make_response(data={
                    "status": "success", "dry_run": True,
                    "planes": len(planes),
                    "node_xs": sorted(node_xs),
                    "center_fixes": len([x for x in plan if x["type"] == "center_diag"]),
                    "edge_montants": len([x for x in plan if x["type"] == "edge_montant"]),
                    "purlins_to_move": len(purlin_plan),
                    "plan": plan,
                    "purlin_sample": purlin_plan[:10],
                })

            # ---------------- EXECUTE ----------------
            errors = []
            center_done = 0
            edge_done = 0
            purlin_done = 0

            # recrear diagonales centrales apuntando al nudo del montante
            if do_center:
                t = _new_txn(doc, u"Fix nudo central: diagonales")
                t.Start()
                try:
                    for pp in plan:
                        if pp["type"] != "center_diag":
                            continue
                        try:
                            el = center_els.get(int(pp["id"]))
                            if el is None:
                                continue
                            loc = el.Location
                            if not hasattr(loc, "Curve"):
                                continue
                            cv = loc.Curve
                            if not isinstance(cv, DB.Line):
                                continue
                            p0 = cv.GetEndPoint(0)
                            p1 = cv.GetEndPoint(1)
                            hi = p1 if p1.Z >= p0.Z else p0
                            lo = p0 if p1.Z >= p0.Z else p1
                            sym = el.Symbol
                            mark = ""
                            mp = el.LookupParameter("Mark")
                            if mp is not None and not mp.IsReadOnly:
                                mark = mp.AsString() or ""
                            ntop = DB.XYZ(pp["new"][0] * FT, hi.Y, pp["new"][1] * FT)
                            new_line = DB.Line.CreateBound(lo, ntop)
                            doc.Delete(el.Id)
                            inst = doc.Create.NewFamilyInstance(
                                new_line, sym, level,
                                DB.Structure.StructuralType.Beam)
                            try:
                                _SFU.DisallowJoinAtEnd(inst, 0)
                                _SFU.DisallowJoinAtEnd(inst, 1)
                            except Exception:
                                pass
                            if mark:
                                nm = inst.LookupParameter("Mark")
                                if nm is not None and not nm.IsReadOnly:
                                    try:
                                        nm.Set(mark)
                                    except Exception:
                                        pass
                            center_done += 1
                        except Exception as e1:
                            if len(errors) < 5:
                                errors.append("center:" + str(e1)[:160])
                    t.Commit()
                except Exception:
                    try:
                        if t.HasStarted() and not t.HasEnded():
                            t.RollBack()
                    except Exception:
                        pass
                    raise

            # crear montantes de extremo en x=0.40
            if do_edge and web_sym is not None:
                t = _new_txn(doc, u"Fix montantes de extremo x=0.40")
                t.Start()
                try:
                    for pp in plan:
                        if pp["type"] != "edge_montant":
                            continue
                        try:
                            y = pp["y"]
                            p0 = DB.XYZ(0.40 * FT, y * FT, pp["from"][2] * FT)
                            p1 = DB.XYZ(0.40 * FT, y * FT, pp["to"][2] * FT)
                            line = DB.Line.CreateBound(p0, p1)
                            inst = doc.Create.NewFamilyInstance(
                                line, web_sym, level,
                                DB.Structure.StructuralType.Beam)
                            try:
                                _SFU.DisallowJoinAtEnd(inst, 0)
                                _SFU.DisallowJoinAtEnd(inst, 1)
                            except Exception:
                                pass
                            edge_done += 1
                        except Exception as e1:
                            if len(errors) < 5:
                                errors.append("edge:" + str(e1)[:160])
                    t.Commit()
                except Exception:
                    try:
                        if t.HasStarted() and not t.HasEnded():
                            t.RollBack()
                    except Exception:
                        pass
                    raise

            # mover correas al nodo mas cercano conservando radio
            if do_purlins and purlin_plan:
                t = _new_txn(doc, u"Fix correas: alinear a nodos")
                t.Start()
                try:
                    for rec in purlin_plan:
                        try:
                            el = purlin_els.get(int(rec["id"]))
                            if el is None:
                                continue
                            dx = (rec["x_new"] - rec["x_old"]) * FT
                            dz = (rec["z_new"] - rec["z_old"]) * FT
                            vec = DB.XYZ(dx, 0.0, dz)
                            try:
                                _SFU.DisallowJoinAtEnd(el, 0)
                                _SFU.DisallowJoinAtEnd(el, 1)
                            except Exception:
                                pass
                            DB.ElementTransformUtils.MoveElement(
                                doc, el.Id, vec)
                            purlin_done += 1
                        except Exception as e1:
                            if len(errors) < 5:
                                errors.append("purlin:" + str(e1)[:160])
                    t.Commit()
                except Exception:
                    try:
                        if t.HasStarted() and not t.HasEnded():
                            t.RollBack()
                    except Exception:
                        pass
                    raise

            return routes.make_response(data={
                "status": "success",
                "center_diags_fixed": center_done,
                "edge_montants_created": edge_done,
                "purlins_aligned": purlin_done,
                "node_xs": sorted(node_xs),
                "errors": errors,
            })
        except Exception as e:
            log_route_error("fix_truss_nodes", e)
            logger.error("fix_truss_nodes failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/add_montants_at_purlins/", methods=["POST"])
    def add_montants_at_purlins(doc, request):
        """Crea montantes verticales (HSS50x50x2.5, mismo simbolo que el
        entramado) en CADA nodo de correa de la brida superior, para los 7
        planos Y del tijeral.

        Regla del usuario: si el espaciado de correas es congruente (igual),
        prevalecen las correas y se crean montantes verticales en sus X.
        Evaluado en el modelo: 17 X de correas con intervalo uniforme sobre el
        arco (R~14.16, centro (11.325,-2.5)) -> las correas prevalecen.

        Para cada plano Y y cada X de correa detectada en el modelo:
          * si ya existe un vertical real (dx<0.03, dz>0.5) cerca de esa X
            (tolerancia 0.06 m) -> se omite (idempotente).
          * el montante de extremo existente en x~0.40 se RECREA en x=0.0
            (correa de borde) sobre los arcos reales del plano.
          * si no existe, se crea de brida inferior a brida superior usando
            los arcos reales detectados en ese plano.

        Body: {"dry_run": true|false, "move_edge": true}
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) \
                        if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            dry_run = bool(body.get("dry_run", False))
            do_move_edge = bool(body.get("move_edge", True))
            FT = FT_PER_M

            cat = DB.BuiltInCategory.OST_StructuralFraming
            els = DB.FilteredElementCollector(doc)\
                .OfCategory(cat).WhereElementIsNotElementType().ToElements()

            web = []
            tops = []
            bots = []
            purlins = []
            for el in els:
                try:
                    lc = el.Location
                    curve = lc.Curve if hasattr(lc, "Curve") else None
                    if curve is None:
                        continue
                    tn = _norm(get_element_name(el.Symbol))
                    if _is_member_web(el):
                        if isinstance(curve, DB.Line):
                            web.append((el, curve))
                    elif tn == "hss100x50x3":
                        if isinstance(curve, DB.Arc):
                            tops.append((el, curve))
                    elif tn == "hss100x50x45":
                        if isinstance(curve, DB.Arc):
                            bots.append((el, curve))
                        elif isinstance(curve, DB.Line):
                            p = curve.GetEndPoint(0)
                            q = curve.GetEndPoint(1)
                            if abs(p.Y - q.Y) > 0.5 * FT and abs(p.X - q.X) < 0.1 * FT:
                                purlins.append((el, curve))
                except Exception:
                    continue

            def arc_z(arc, x_m):
                c = arc.Center
                r = arc.Radius / FT
                dx = x_m - c.X / FT
                d2 = r * r - dx * dx
                if d2 < 0:
                    return None
                return c.Z / FT + math.sqrt(d2)

            # X reales de correas (independiente del plano). Normalizamos el
            # borde a 0.0 para que no haya duplicados tipo 0.0/0.01.
            purlin_xs = sorted(set(round(c.GetEndPoint(0).X / FT, 3)
                                    for el, c in purlins))
            px_norm = []
            for x in purlin_xs:
                if any(abs(x - px) < 0.02 for px in px_norm):
                    continue
                if abs(x) < 0.05:
                    px_norm.append(0.0)
                else:
                    px_norm.append(x)
            purlin_xs = sorted(set(px_norm))

            planes = {}
            for el, c in web:
                p = c.GetEndPoint(0)
                q = c.GetEndPoint(1)
                y = round((p.Y + q.Y) / 2.0 / FT, 2)
                planes.setdefault(y, []).append((el, c))

            web_sym = None
            level = lowest_level(doc)
            plan = []      # montantes nuevos
            moves = []     # recreaciones del montante de extremo 0.40 -> 0.0

            for y in sorted(planes):
                mems = planes[y]
                top_arc = None
                bot_arc = None
                for el, c in tops:
                    if abs(c.Center.Y / FT - y) < 0.05:
                        top_arc = c
                        break
                for el, c in bots:
                    if abs(c.Center.Y / FT - y) < 0.05:
                        bot_arc = c
                        break
                if web_sym is None:
                    for el, c in mems:
                        web_sym = el.Symbol
                        if not web_sym.IsActive:
                            web_sym.Activate()
                        break

                # verticales reales ya existentes en este plano: (x, el, curve)
                verts = []
                for el, c in mems:
                    p = c.GetEndPoint(0)
                    q = c.GetEndPoint(1)
                    xa, xb = p.X / FT, q.X / FT
                    za, zb = p.Z / FT, q.Z / FT
                    if abs(xa - xb) < 0.03 and abs(za - zb) > 0.2:
                        verts.append(((xa + xb) / 2.0, el, c))
                has_x = set(round(v[0], 3) for v in verts)

                # montante de extremo x~0.40 -> recrear en x=0.0 (correa borde)
                if do_move_edge and 0.0 in purlin_xs:
                    edge_el = None
                    for x, el, c in verts:
                        if 0.30 <= x <= 0.50:
                            edge_el = el
                            break
                    if edge_el is not None and \
                            not any(abs(0.0 - hx) < 0.06 for hx in has_x):
                        zt = arc_z(top_arc, 0.0) if top_arc else None
                        zb = arc_z(bot_arc, 0.0) if bot_arc else None
                        if zt is not None and zb is not None:
                            moves.append({
                                "y": y, "el": edge_el,
                                "from": [0.0, y, round(zb, 3)],
                                "to": [0.0, y, round(zt, 3)],
                            })
                            has_x.add(0.0)

                # montante nuevo en cada X de correa no cubierta
                for x in purlin_xs:
                    if abs(x) < 0.06:
                        continue
                    if any(abs(x - hx) < 0.06 for hx in has_x):
                        continue
                    zt = arc_z(top_arc, x) if top_arc else None
                    zb = arc_z(bot_arc, x) if bot_arc else None
                    if zt is None or zb is None:
                        continue
                    plan.append({
                        "type": "montant", "y": y, "x": x,
                        "from": [x, y, round(zb, 3)],
                        "to": [x, y, round(zt, 3)],
                    })
                    has_x.add(x)

            if dry_run:
                return routes.make_response(data={
                    "status": "success", "dry_run": True,
                    "planes": len(planes),
                    "purlin_xs": purlin_xs,
                    "create_montants": len(plan),
                    "move_edge": len(moves),
                    "plan": plan,
                    "moves": moves,
                })

            # ---------------- EXECUTE ----------------
            errors = []
            created = 0
            moved = 0

            if moves and web_sym is not None:
                t = _new_txn(doc, u"Montantes: extremo a x=0.0 (correa borde)")
                t.Start()
                try:
                    for rec in moves:
                        try:
                            el = rec.get("el")
                            if el is None:
                                continue
                            y = rec["y"]
                            doc.Delete(el.Id)
                            p0 = DB.XYZ(0.0, y * FT, rec["from"][2] * FT)
                            p1 = DB.XYZ(0.0, y * FT, rec["to"][2] * FT)
                            line = DB.Line.CreateBound(p0, p1)
                            inst = doc.Create.NewFamilyInstance(
                                line, web_sym, level,
                                DB.Structure.StructuralType.Beam)
                            try:
                                _SFU.DisallowJoinAtEnd(inst, 0)
                                _SFU.DisallowJoinAtEnd(inst, 1)
                            except Exception:
                                pass
                            moved += 1
                        except Exception as e1:
                            if len(errors) < 5:
                                errors.append("move_edge:" + str(e1)[:160])
                    t.Commit()
                except Exception:
                    try:
                        if t.HasStarted() and not t.HasEnded():
                            t.RollBack()
                    except Exception:
                        pass
                    raise

            if plan and web_sym is not None:
                t = _new_txn(doc, u"Montantes en nodos de correas")
                t.Start()
                try:
                    for rec in plan:
                        try:
                            p0 = DB.XYZ(rec["x"] * FT, rec["y"] * FT,
                                        rec["from"][2] * FT)
                            p1 = DB.XYZ(rec["x"] * FT, rec["y"] * FT,
                                        rec["to"][2] * FT)
                            line = DB.Line.CreateBound(p0, p1)
                            inst = doc.Create.NewFamilyInstance(
                                line, web_sym, level,
                                DB.Structure.StructuralType.Beam)
                            try:
                                _SFU.DisallowJoinAtEnd(inst, 0)
                                _SFU.DisallowJoinAtEnd(inst, 1)
                            except Exception:
                                pass
                            created += 1
                        except Exception as e1:
                            if len(errors) < 5:
                                errors.append("montant:" + str(e1)[:160])
                    t.Commit()
                except Exception:
                    try:
                        if t.HasStarted() and not t.HasEnded():
                            t.RollBack()
                    except Exception:
                        pass
                    raise

            return routes.make_response(data={
                "status": "success",
                "create_montants": created,
                "move_edge": moved,
                "purlin_xs": purlin_xs,
                "errors": errors,
            })
        except Exception as e:
            log_route_error("add_montants_at_purlins", e)
            logger.error("add_montants_at_purlins failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/fix_montants_radial/", methods=["POST"])
    def fix_montants_radial(doc, request):
        """Corrige las montantes del tijeral para que queden ALINEADAS CON LA
        CURVATURA de los arcos (radiales, perpendiculares a las cuerdas):

          1. BORRA las montantes VERTICALES erroneas (dx~0, creadas por
             add_montants_at_purlins) que duplican nodos interiores, salvo la
             montante central en x=11.325 (que en la clave si es vertical).
          2. CREA las montantes RADIALES de extremo que faltan: el extremo del
             arco superior (x=0 / x=22.65, z=6.0) se une con el extremo del
             arco inferior (x=0.40 / x=22.25, z=5.70) a lo largo de la misma
             linea radial (centro (11.325,-2.5), R_top=14.16, R_bot=13.66).

        Body: {"dry_run": true|false}
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) \
                        if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            dry_run = bool(body.get("dry_run", False))
            FT = FT_PER_M

            cat = DB.BuiltInCategory.OST_StructuralFraming
            els = DB.FilteredElementCollector(doc)\
                .OfCategory(cat).WhereElementIsNotElementType().ToElements()

            web = []
            tops = []
            bots = []
            for el in els:
                try:
                    lc = el.Location
                    curve = lc.Curve if hasattr(lc, "Curve") else None
                    if curve is None:
                        continue
                    tn = _norm(get_element_name(el.Symbol))
                    if _is_member_web(el):
                        if isinstance(curve, DB.Line):
                            web.append((el, curve))
                    elif tn == "hss100x50x3":
                        if isinstance(curve, DB.Arc):
                            tops.append((el, curve))
                    elif tn == "hss100x50x45":
                        if isinstance(curve, DB.Arc):
                            bots.append((el, curve))
                except Exception:
                    continue

            # centro y radios de los arcos (iguales en los 7 planos)
            C = None
            R_top = None
            R_bot = None
            for el, c in tops:
                C = (c.Center.X / FT, c.Center.Z / FT)
                R_top = c.Radius / FT
                break
            for el, c in bots:
                R_bot = c.Radius / FT
                break
            if C is None or R_top is None or R_bot is None:
                return routes.make_response(
                    data={"error": "No se detectaron arcos superior/inferior"},
                    status=500)

            # 1) montantes verticales erroneas a borrar (excluye la central).
            #    Solo las HSS50x50x2.5 del alma que cruzan desde la cuerda
            #    inferior (z~5.7..11) hacia la superior: se descartan los
            #    "stubs" HSS50x50x2 en x=0/x=22.65 (z 5.0..5.5) y otros apoyos.
            to_delete = []
            for el, c in web:
                tn = _norm(get_element_name(el.Symbol))
                if "hss50x50x25" not in tn:
                    continue
                p = c.GetEndPoint(0)
                q = c.GetEndPoint(1)
                xa, xb = p.X / FT, q.X / FT
                za, zb = p.Z / FT, q.Z / FT
                zmax = max(za, zb)
                if abs(xa - xb) < 0.03 and abs(za - zb) > 0.2 and zmax > 5.6:
                    xm = (xa + xb) / 2.0
                    if abs(xm - C[0]) > 0.05:
                        to_delete.append(el)

            # 2) montantes radiales de extremo que faltan
            planes = {}
            for el, c in web:
                p = c.GetEndPoint(0)
                q = c.GetEndPoint(1)
                y = round((p.Y + q.Y) / 2.0 / FT, 2)
                planes.setdefault(y, []).append((el, c))

            end_montants = []
            web_sym = None
            level = lowest_level(doc)
            for y in sorted(planes):
                mems = planes[y]
                top_arc = None
                bot_arc = None
                for el, c in tops:
                    if abs(c.Center.Y / FT - y) < 0.05:
                        top_arc = c
                        break
                for el, c in bots:
                    if abs(c.Center.Y / FT - y) < 0.05:
                        bot_arc = c
                        break
                if web_sym is None:
                    for el, c in mems:
                        web_sym = el.Symbol
                        if not web_sym.IsActive:
                            web_sym.Activate()
                        break
                if top_arc is None or bot_arc is None:
                    continue
                # extremos del arco superior
                te0 = top_arc.GetEndPoint(0)
                te1 = top_arc.GetEndPoint(1)
                if te0.X < te1.X:
                    t_left, t_right = te0, te1
                else:
                    t_left, t_right = te1, te0
                # extremos del arco inferior
                be0 = bot_arc.GetEndPoint(0)
                be1 = bot_arc.GetEndPoint(1)
                if be0.X < be1.X:
                    b_left, b_right = be0, be1
                else:
                    b_left, b_right = be1, be0

                for tag, tpt, bpt in (("left", t_left, b_left),
                                      ("right", t_right, b_right)):
                    tm = (tpt.X / FT, tpt.Y / FT, tpt.Z / FT)
                    bm = (bpt.X / FT, bpt.Y / FT, bpt.Z / FT)
                    already = False
                    for el, c in mems:
                        pa = c.GetEndPoint(0)
                        qa = c.GetEndPoint(1)
                        pts = [(pa.X / FT, pa.Y / FT, pa.Z / FT),
                               (qa.X / FT, qa.Y / FT, qa.Z / FT)]
                        if (math.hypot(pts[0][0] - tm[0], pts[0][2] - tm[2]) < 0.06
                                and math.hypot(pts[1][0] - bm[0], pts[1][2] - bm[2]) < 0.06) \
                           or (math.hypot(pts[1][0] - tm[0], pts[1][2] - tm[2]) < 0.06
                                and math.hypot(pts[0][0] - bm[0], pts[0][2] - bm[2]) < 0.06):
                            already = True
                            break
                    if not already:
                        end_montants.append({
                            "y": y, "side": tag,
                            "from": [round(bm[0], 3), y, round(bm[2], 3)],
                            "to": [round(tm[0], 3), y, round(tm[2], 3)],
                        })

            if dry_run:
                return routes.make_response(data={
                    "status": "success", "dry_run": True,
                    "center": [round(C[0], 3), round(C[1], 3)],
                    "R_top": round(R_top, 3), "R_bot": round(R_bot, 3),
                    "wrong_verticals_to_delete": len(to_delete),
                    "wrong_ids": [int(str(el.Id).replace("ElementId(", "").replace(")", ""))
                                  for el in to_delete],
                    "end_montants_to_create": len(end_montants),
                    "end_montants": end_montants,
                })

            # ---------------- EXECUTE ----------------
            errors = []
            deleted = 0
            created = 0

            if to_delete:
                t = _new_txn(doc, u"Montantes: borrar verticales erroneas")
                t.Start()
                try:
                    for el in to_delete:
                        try:
                            doc.Delete(el.Id)
                            deleted += 1
                        except Exception as e1:
                            if len(errors) < 5:
                                errors.append("del:" + str(e1)[:160])
                    t.Commit()
                except Exception:
                    try:
                        if t.HasStarted() and not t.HasEnded():
                            t.RollBack()
                    except Exception:
                        pass
                    raise

            if end_montants and web_sym is not None:
                t = _new_txn(doc, u"Montantes radiales de extremo")
                t.Start()
                try:
                    for rec in end_montants:
                        try:
                            p0 = DB.XYZ(rec["from"][0] * FT, rec["y"] * FT,
                                        rec["from"][2] * FT)
                            p1 = DB.XYZ(rec["to"][0] * FT, rec["y"] * FT,
                                        rec["to"][2] * FT)
                            line = DB.Line.CreateBound(p0, p1)
                            inst = doc.Create.NewFamilyInstance(
                                line, web_sym, level,
                                DB.Structure.StructuralType.Beam)
                            try:
                                _SFU.DisallowJoinAtEnd(inst, 0)
                                _SFU.DisallowJoinAtEnd(inst, 1)
                            except Exception:
                                pass
                            created += 1
                        except Exception as e1:
                            if len(errors) < 5:
                                errors.append("create:" + str(e1)[:160])
                    t.Commit()
                except Exception:
                    try:
                        if t.HasStarted() and not t.HasEnded():
                            t.RollBack()
                    except Exception:
                        pass
                    raise

            return routes.make_response(data={
                "status": "success",
                "wrong_verticals_deleted": deleted,
                "end_montants_created": created,
                "errors": errors,
            })
        except Exception as e:
            log_route_error("fix_montants_radial", e)
            logger.error("fix_montants_radial failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/fix_correas_align/", methods=["POST"])
    def fix_correas_align(doc, request):
        """Alinea las CORREAS (HSS100x50x4.5 corridas en Y) con las montantes.

        Mueve cada correa para que su centro de gravedad coincida EXACTAMENTE
        con el nodo de la brida superior (tope de la montante), de modo que la
        correa queda apoyada directamente sobre la brida y alineada con la
        montante. El .s2k define la correa centrada en el nodo de la brida
        superior.

        Body: {"dry_run": true|false}
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) \
                        if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            dry_run = bool(body.get("dry_run", False))
            FT = FT_PER_M

            def _eid(el):
                return int(str(el.Id).replace("ElementId(", "").replace(")", ""))

            cat = DB.BuiltInCategory.OST_StructuralFraming
            els = DB.FilteredElementCollector(doc)\
                .OfCategory(cat).WhereElementIsNotElementType().ToElements()

            purlins = []
            mont_tops = []   # (y_plane, x_m, z_m)
            for el in els:
                try:
                    lc = el.Location
                    curve = lc.Curve if hasattr(lc, "Curve") else None
                    if curve is None or not isinstance(curve, DB.Line):
                        continue
                    tn = _norm(get_element_name(el.Symbol))
                    if tn == "hss100x50x45":
                        p = curve.GetEndPoint(0)
                        q = curve.GetEndPoint(1)
                        if abs(p.Y - q.Y) > 0.5 * FT and abs(p.X - q.X) < 0.1 * FT:
                            purlins.append((el, curve))
                    elif _is_member_web(el):
                        length = curve.Length / FT
                        if abs(length - 0.5) < 0.05:
                            p = curve.GetEndPoint(0)
                            q = curve.GetEndPoint(1)
                            top = p if p.Z > q.Z else q
                            yp = round((p.Y + q.Y) / 2.0 / FT, 2)
                            mont_tops.append((yp, top.X / FT, top.Z / FT))
                except Exception:
                    continue

            plan = []
            skipped = []
            for el, curve in purlins:
                try:
                    p0 = curve.GetEndPoint(0)
                    p1 = curve.GetEndPoint(1)
                    x0 = p0.X / FT
                    y0 = p0.Y / FT
                    z0 = p0.Z / FT
                    y1 = p1.Y / FT
                    y_plane = round(y0, 2)
                    best = None
                    for yp, mx, mz in mont_tops:
                        if abs(yp - y_plane) > 0.05:
                            continue
                        d = abs(mx - x0)
                        if d < 0.30 and (best is None or d < best[0]):
                            best = (d, mx, mz)
                    if best is None:
                        skipped.append(_eid(el))
                        continue
                    mx, mz = best[1], best[2]
                    plan.append({
                        "id": _eid(el),
                        "from0": [round(x0, 3), round(y0, 3), round(z0, 3)],
                        "from1": [round(p1.X / FT, 3), round(y1, 3),
                                  round(p1.Z / FT, 3)],
                        "to0": [round(mx, 3), round(y0, 3), round(mz, 3)],
                        "to1": [round(mx, 3), round(y1, 3), round(mz, 3)],
                    })
                except Exception:
                    continue

            if dry_run:
                return routes.make_response(data={
                    "status": "success", "dry_run": True,
                    "total_purlins": len(purlins),
                    "montant_tops": len(mont_tops),
                    "to_move": len(plan),
                    "skipped": len(skipped),
                    "skipped_ids": skipped[:20],
                    "plan": plan[:14],
                })

            errors = []
            moved = 0
            t = _new_txn(doc, u"Correas: alinear a montantes")
            t.Start()
            try:
                for rec in plan:
                    try:
                        el = None
                        for e2, c2 in purlins:
                            if _eid(e2) == rec["id"]:
                                el = e2
                                break
                        if el is None:
                            continue
                        dx = (rec["to0"][0] - rec["from0"][0]) * FT
                        dz = (rec["to0"][2] - rec["from0"][2]) * FT
                        delta = DB.XYZ(dx, 0, dz)
                        DB.ElementTransformUtils.MoveElement(doc, el.Id, delta)
                        moved += 1
                    except Exception as e1:
                        if len(errors) < 5:
                            errors.append("move:" + str(e1)[:160])
                t.Commit()
            except Exception:
                try:
                    if t.HasStarted() and not t.HasEnded():
                        t.RollBack()
                except Exception:
                    pass
                raise

            return routes.make_response(data={
                "status": "success",
                "moved": moved,
                "total_purlins": len(purlins),
                "errors": errors,
            })
        except Exception as e:
            log_route_error("fix_correas_align", e)
            logger.error("fix_correas_align failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/fix_correas_on_chord/", methods=["POST"])
    def fix_correas_on_chord(doc, request):
        """Apoya las CORREAS sobre el CANTO SUPERIOR de la brida superior.

        Las correas estan centradas en el nodo de la brida superior (coinciden
        con el centro del arco). Este fix las desplaza +OFF PERPENDICULAR
        al arco (direccion radial, centro del arco HSS100x50x3) para que la
        cara inferior de la correa (HSS150x50x3, canto 0.15) apoye sobre la
        cara superior de la brida (HSS100x50x3, canto 0.10): offset
        0.075 + 0.05 = 0.125 m.

        Body: {"dry_run": true|false, "offset_m": 0.125}
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) \
                        if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            dry_run = bool(body.get("dry_run", False))
            try:
                OFF = float(body.get("offset_m", 0.125))
            except Exception:
                OFF = 0.125
            FT = FT_PER_M

            def _eid(el):
                return int(str(el.Id).replace("ElementId(", "").replace(")", ""))

            cat = DB.BuiltInCategory.OST_StructuralFraming
            els = DB.FilteredElementCollector(doc)\
                .OfCategory(cat).WhereElementIsNotElementType().ToElements()

            purlins = []
            mont_tops = []   # (y_plane, x_m, z_m)
            for el in els:
                try:
                    lc = el.Location
                    curve = lc.Curve if hasattr(lc, "Curve") else None
                    if curve is None or not isinstance(curve, DB.Line):
                        continue
                    tn = _norm(get_element_name(el.Symbol))
                    if tn == "hss150x50x3":
                        p = curve.GetEndPoint(0)
                        q = curve.GetEndPoint(1)
                        if abs(p.Y - q.Y) > 0.5 * FT and abs(p.X - q.X) < 0.1 * FT:
                            purlins.append((el, curve))
                    elif _is_member_web(el):
                        length = curve.Length / FT
                        if abs(length - 0.5) < 0.05:
                            p = curve.GetEndPoint(0)
                            q = curve.GetEndPoint(1)
                            top = p if p.Z > q.Z else q
                            yp = round((p.Y + q.Y) / 2.0 / FT, 2)
                            mont_tops.append((yp, top.X / FT, top.Z / FT))
                except Exception:
                    continue

            # centro/R del arco superior real (HSS100x50x3, DB.Arc)
            arc_center = None
            arc_radius = None
            for el in els:
                try:
                    lc = el.Location
                    curve = lc.Curve if hasattr(lc, "Curve") else None
                    if isinstance(curve, DB.Arc):
                        if _norm(get_element_name(el.Symbol)) == "hss100x50x3":
                            arc_center = (curve.Center.X / FT, curve.Center.Z / FT)
                            arc_radius = curve.Radius / FT
                            break
                except Exception:
                    continue
            if arc_center is None or arc_radius is None:
                return routes.make_response(
                    data={"error": "Arco superior HSS100x50x3 no detectado"},
                    status=500)

            CX, CZ, R = arc_center[0], arc_center[1], arc_radius

            plan = []
            skipped = []
            for el, curve in purlins:
                try:
                    p0 = curve.GetEndPoint(0)
                    p1 = curve.GetEndPoint(1)
                    x0 = p0.X / FT
                    y0 = p0.Y / FT
                    z0 = p0.Z / FT
                    y1 = p1.Y / FT
                    y_plane = round(y0, 2)
                    # nodo de la montante donde esta centrada la correa:
                    # tomar la montante mas cercana en el mismo plano Y
                    best = None
                    for yp, mx, mz in mont_tops:
                        if abs(yp - y_plane) > 0.05:
                            continue
                        d = abs(mx - x0)
                        if best is None or d < best[0]:
                            best = (d, mx, mz)
                    if best is None:
                        skipped.append(_eid(el))
                        continue
                    mx, mz = best[1], best[2]
                    # vector radial unitario (perpendicular al arco)
                    dxn = mx - CX
                    dzn = mz - CZ
                    nn = math.hypot(dxn, dzn)
                    if nn < 1e-6:
                        ux, uz = 0.0, 1.0
                    else:
                        ux, uz = dxn / nn, dzn / nn
                    tx = mx + OFF * ux
                    tz = mz + OFF * uz
                    plan.append({
                        "id": _eid(el),
                        "from0": [round(x0, 3), round(y0, 3), round(z0, 3)],
                        "from1": [round(p1.X / FT, 3), round(y1, 3),
                                  round(p1.Z / FT, 3)],
                        "to0": [round(tx, 3), round(y0, 3), round(tz, 3)],
                        "to1": [round(tx, 3), round(y1, 3), round(tz, 3)],
                    })
                except Exception:
                    continue

            if dry_run:
                return routes.make_response(data={
                    "status": "success", "dry_run": True,
                    "center": [round(CX, 3), round(CZ, 3)],
                    "radius": round(R, 3),
                    "offset_m": OFF,
                    "total_purlins": len(purlins),
                    "to_move": len(plan),
                    "skipped": len(skipped),
                    "skipped_ids": skipped[:20],
                    "plan": plan[:14],
                })

            errors = []
            moved = 0
            t = _new_txn(doc, u"Correas: apoyar sobre canto de la brida")
            t.Start()
            try:
                for rec in plan:
                    try:
                        el = None
                        for e2, c2 in purlins:
                            if _eid(e2) == rec["id"]:
                                el = e2
                                break
                        if el is None:
                            continue
                        a = DB.XYZ(rec["to0"][0] * FT, rec["to0"][1] * FT,
                                   rec["to0"][2] * FT)
                        b = DB.XYZ(rec["to1"][0] * FT, rec["to1"][1] * FT,
                                   rec["to1"][2] * FT)
                        new_line = DB.Line.CreateBound(a, b)
                        for end_i in (0, 1):
                            try:
                                _SFU.DisallowJoinAtEnd(el, end_i)
                            except Exception:
                                pass
                        try:
                            if el.Pinned:
                                el.Pinned = False
                        except Exception:
                            pass
                        loc = el.Location
                        if isinstance(loc, DB.LocationCurve):
                            loc.Curve = new_line
                            moved += 1
                        else:
                            delta = DB.XYZ(
                                rec["to0"][0] * FT - rec["from0"][0] * FT,
                                0, rec["to0"][2] * FT - rec["from0"][2] * FT)
                            DB.ElementTransformUtils.MoveElement(
                                doc, el.Id, delta)
                            moved += 1
                    except Exception as e1:
                        if len(errors) < 5:
                            errors.append("move:" + str(e1)[:160])
                t.Commit()
            except Exception:
                try:
                    if t.HasStarted() and not t.HasEnded():
                        t.RollBack()
                except Exception:
                    pass
                raise

            return routes.make_response(data={
                "status": "success",
                "moved": moved,
                "total_purlins": len(purlins),
                "errors": errors,
            })
        except Exception as e:
            log_route_error("fix_correas_on_chord", e)
            logger.error("fix_correas_on_chord failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/retarget_by_ids/", methods=["POST"])
    def retarget_by_ids(doc, request):
        """Reasigna el FamilySymbol SOLO a los elementos indicados por id.

        Body: {"ids": [123, 456], "to_type": "HSS150x50x3",
               "to_family": "HSS-Secci\u00f3n estructural hueca",
               "category": "framing|columns"}
        Cambia el tipo de cada elemento de la lista. Si un id no se encuentra
        o ya es el tipo destino, se omite.
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) \
                        if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            raw_ids = body.get("ids") or []
            to_type = body.get("to_type")
            to_fam = body.get("to_family") or ""
            category = body.get("category") or u"framing"
            if not raw_ids or not to_type:
                return routes.make_response(
                    data={"error": "ids and to_type required"}, status=400)

            ids = set()
            for r in raw_ids:
                try:
                    ids.add(int(str(r).replace("ElementId(", "").replace(")", "")))
                except Exception:
                    pass

            cat_map = {u"framing": DB.BuiltInCategory.OST_StructuralFraming,
                       u"columns": DB.BuiltInCategory.OST_StructuralColumns}
            cat = cat_map.get(u"{}".format(category).lower())
            if cat is None:
                return routes.make_response(
                    data={"error": "bad category"}, status=400)

            target = None
            if to_fam:
                for sym in DB.FilteredElementCollector(doc)\
                          .OfClass(DB.FamilySymbol).ToElements():
                    if _norm(get_element_name(sym.Family)) == \
                            _norm(to_fam) and \
                            _norm(get_element_name(sym)) == \
                            _norm(to_type):
                        target = sym
                        break
            if target is None:
                for sym in DB.FilteredElementCollector(doc)\
                          .OfClass(DB.FamilySymbol).ToElements():
                    if _norm(get_element_name(sym)) == \
                            _norm(to_type):
                        target = sym
                        break
            if target is None:
                return routes.make_response(
                    data={"error": u"target type not found: {} / {}".format(
                        to_fam, to_type)}, status=404)

            changed = []
            not_found = []
            already = []
            txn = DB.Transaction(doc, u"Retarget by ids")
            txn.Start()
            try:
                for inst in DB.FilteredElementCollector(doc)\
                              .OfCategory(cat)\
                              .WhereElementIsNotElementType()\
                              .ToElements():
                    eid = int(str(inst.Id).replace("ElementId(", "").replace(")", ""))
                    if eid not in ids:
                        continue
                    cur = _norm(get_element_name(inst.Symbol))
                    if cur == _norm(to_type):
                        already.append(eid)
                        continue
                    if not target.IsActive:
                        target.Activate()
                    inst.Symbol = target
                    changed.append(eid)
                txn.Commit()
            except Exception:
                try:
                    if txn.HasStarted() and not txn.HasEnded():
                        txn.RollBack()
                except Exception:
                    pass
                raise

            return routes.make_response(data={
                "status": "success",
                "requested": len(ids),
                "changed": changed,
                "count": len(changed),
                "already": already,
                "not_found": not_found,
            })
        except Exception as e:
            log_route_error("retarget_by_ids", e)
            logger.error("retarget_by_ids failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/lower_tensor_ends/", methods=["POST"])
    def lower_tensor_ends(doc, request):
        """Baja SOLO el extremo de los tensores O 16 que conecta con la columna.

        Los tensores (sistema San Andres, perfil O 16) tienen un extremo sobre
        la columna (x~0 MXm22.65, z~5.8) y el otro en el centro del tijeral
        (z~9.97). Esta ruta mueve unicamente el extremo que toca la columna
        -DROP m (bajar), dejando intacto el otro extremo y el resto de la
        geometria.

        Body: {"drop_m": 0.2, "dry_run": false}
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) \
                        if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            dry_run = bool(body.get("dry_run", False))
            try:
                DROP = float(body.get("drop_m", 0.2))
            except Exception:
                DROP = 0.2
            FT = FT_PER_M

            def _eid(el):
                return int(str(el.Id).replace("ElementId(", "").replace(")", ""))

            cat = DB.BuiltInCategory.OST_StructuralFraming
            els = DB.FilteredElementCollector(doc)\
                .OfCategory(cat).WhereElementIsNotElementType().ToElements()

            tensors = []
            for el in els:
                try:
                    tn = _norm(get_element_name(el.Symbol))
                    if tn != "o16":
                        continue
                    lc = el.Location
                    curve = lc.Curve if hasattr(lc, "Curve") else None
                    if curve is None or not isinstance(curve, DB.Line):
                        continue
                    tensors.append((el, curve))
                except Exception:
                    continue

            plan = []
            skipped = []
            for el, curve in tensors:
                try:
                    p0 = curve.GetEndPoint(0)
                    p1 = curve.GetEndPoint(1)
                    x0 = p0.X / FT; y0 = p0.Y / FT; z0 = p0.Z / FT
                    x1 = p1.X / FT; y1 = p1.Y / FT; z1 = p1.Z / FT
                    near0 = min(x0, abs(x0 - 22.65)) < 0.5 and z0 < 7.0
                    near1 = min(x1, abs(x1 - 22.65)) < 0.5 and z1 < 7.0
                    if near0 == near1:
                        skipped.append(_eid(el))
                        continue
                    if near0:
                        t = [x0, y0, z0 - DROP]; o = (x1, y1, z1)
                    else:
                        t = [x1, y1, z1 - DROP]; o = (x0, y0, z0)
                    plan.append({
                        "id": _eid(el),
                        "eid": el.Id,
                        "col0_to": [round(v, 3) for v in t],
                        "other0": [round(v, 3) for v in o],
                    })
                except Exception:
                    skipped.append(_eid(el))

            if dry_run:
                return routes.make_response(data={
                    "status": "success", "dry_run": True,
                    "drop_m": DROP,
                    "total_tensors": len(tensors),
                    "to_move": len(plan),
                    "skipped": len(skipped),
                    "skipped_ids": skipped[:20],
                    "plan": plan[:16],
                })

            errors = []
            moved = 0
            txn = _new_txn(doc, u"Tensores O 16: bajar extremo en columna")
            txn.Start()
            try:
                for rec in plan:
                    try:
                        el = doc.GetElement(rec["eid"])
                        if el is None:
                            continue
                        lc = el.Location
                        curve = lc.Curve if hasattr(lc, "Curve") else None
                        if curve is None:
                            continue
                        p0 = curve.GetEndPoint(0)
                        p1 = curve.GetEndPoint(1)
                        newA = DB.XYZ(rec["col0_to"][0] * FT,
                                      rec["col0_to"][1] * FT,
                                      rec["col0_to"][2] * FT)
                        x0m = p0.X / FT
                        x1m = p1.X / FT
                        if min(x0m, abs(x0m - 22.65)) < 0.5:
                            newB = DB.XYZ(p1.X, p1.Y, p1.Z)
                        else:
                            newB = DB.XYZ(p0.X, p0.Y, p0.Z)
                        new_line = DB.Line.CreateBound(newB, newA)
                        sym = el.Symbol
                        mark_param = el.LookupParameter("Mark")
                        mark_val = mark_param.AsString() \
                            if mark_param and not mark_param.IsReadOnly else None
                        lvl = lowest_level(doc)
                        elid = el.Id
                        doc.Delete(elid)
                        new_inst = doc.Create.NewFamilyInstance(
                            new_line, sym, lvl, DB.Structure.StructuralType.Brace)
                        if mark_val is not None:
                            nm = new_inst.LookupParameter("Mark")
                            if nm and not nm.IsReadOnly:
                                try:
                                    nm.Set(mark_val)
                                except Exception:
                                    pass
                        moved += 1
                    except Exception as e1:
                        if len(errors) < 8:
                            errors.append(
                                "recreate id=%s: %s" % (rec["id"], str(e1)[:180]))
                txn.Commit()
            except Exception:
                try:
                    if txn.HasStarted() and not txn.HasEnded():
                        txn.RollBack()
                except Exception:
                    pass
                raise

            return routes.make_response(data={
                "status": "success",
                "moved": moved,
                "total_tensors": len(tensors),
                "errors": errors,
            })
        except Exception as e:
            log_route_error("lower_tensor_ends", e)
            logger.error("lower_tensor_ends failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/extend_bridas_inferior/", methods=["POST"])
    def extend_bridas_inferior(doc, request):
        """Extiende las bridas inferiores HSS100x50x4.5 hasta la cara de la columna.

        Las 7 bridas inferiores son arcos de R=13.66, centro (11.325, y, -2.3),
        que hoy terminan en x=0.4 (izq) y x=22.25 (der), z=5.9. Esta ruta las
        extiende sobre el mismo circulo hasta x=0.1 y x=22.55 (cara de las
        columnas HSS de 200 mm centradas en x=0 y x=22.65).

        Body: {"dry_run": false}
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) \
                        if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            dry_run = bool(body.get("dry_run", False))
            FT = FT_PER_M
            TARGET_L = 0.1
            TARGET_R = 22.55

            def _eid(el):
                return int(str(el.Id).replace("ElementId(", "").replace(")", ""))

            cat = DB.BuiltInCategory.OST_StructuralFraming
            els = DB.FilteredElementCollector(doc)\
                .OfCategory(cat).WhereElementIsNotElementType().ToElements()

            bridas = []
            for el in els:
                try:
                    tn = _norm(get_element_name(el.Symbol))
                    if tn != "hss100x50x45":
                        continue
                    lc = el.Location
                    curve = lc.Curve if hasattr(lc, "Curve") else None
                    if curve is None or not isinstance(curve, DB.Arc):
                        continue
                    bridas.append((el, curve))
                except Exception:
                    continue

            plan = []
            for el, arc in bridas:
                try:
                    cen = arc.Center
                    rad = arc.Radius
                    cx_m = cen.X / FT
                    cy_m = cen.Y / FT
                    cz_m = cen.Z / FT
                    r_m = rad / FT
                    zL = cz_m + math.sqrt(max(0.0, r_m * r_m - (TARGET_L - cx_m) ** 2))
                    zR = cz_m + math.sqrt(max(0.0, r_m * r_m - (TARGET_R - cx_m) ** 2))
                    mid_z = cz_m + r_m
                    plan.append({
                        "id": _eid(el),
                        "eid": el.Id,
                        "old_pts": [
                            [round(arc.GetEndPoint(0).X / FT, 3),
                             round(cy_m, 3),
                             round(arc.GetEndPoint(0).Z / FT, 3)],
                            [round(arc.GetEndPoint(1).X / FT, 3),
                             round(cy_m, 3),
                             round(arc.GetEndPoint(1).Z / FT, 3)],
                        ],
                        "new": [round(TARGET_L, 3), round(zL, 3),
                                round(TARGET_R, 3), round(zR, 3)],
                        "mid": [round(cx_m, 3), round(cy_m, 3), round(mid_z, 3)],
                    })
                except Exception:
                    continue

            if dry_run:
                return routes.make_response(data={
                    "status": "success", "dry_run": True,
                    "total_bridas": len(bridas),
                    "to_extend": len(plan),
                    "plan": plan[:16],
                })

            errors = []
            moved = 0
            txn = _new_txn(doc, u"Extender bridas inferiores hasta columnas")
            txn.Start()
            try:
                for rec in plan:
                    try:
                        el = doc.GetElement(rec["eid"])
                        if el is None:
                            continue
                        sym = el.Symbol
                        mark_param = el.LookupParameter("Mark")
                        mark_val = mark_param.AsString() \
                            if mark_param and not mark_param.IsReadOnly else None
                        stype = getattr(el, "StructuralType", None) \
                            or DB.Structure.StructuralType.Beam
                        lvl = lowest_level(doc)
                        x1f = rec["new"][0] * FT
                        z1f = rec["new"][1] * FT
                        x2f = rec["new"][2] * FT
                        z2f = rec["new"][3] * FT
                        start = DB.XYZ(x1f, rec["mid"][1] * FT, z1f)
                        end = DB.XYZ(x2f, rec["mid"][1] * FT, z2f)
                        mid = DB.XYZ(rec["mid"][0] * FT,
                                     rec["mid"][1] * FT,
                                     rec["mid"][2] * FT)
                        new_arc = DB.Arc.Create(start, end, mid)
                        elid = el.Id
                        doc.Delete(elid)
                        new_inst = doc.Create.NewFamilyInstance(
                            new_arc, sym, lvl, stype)
                        if mark_val is not None:
                            nm = new_inst.LookupParameter("Mark")
                            if nm and not nm.IsReadOnly:
                                try:
                                    nm.Set(mark_val)
                                except Exception:
                                    pass
                        moved += 1
                    except Exception as e2:
                        if len(errors) < 8:
                            errors.append(
                                "recreate id=%s: %s" % (rec["id"], str(e2)[:220]))
                txn.Commit()
            except Exception:
                try:
                    if txn.HasStarted() and not txn.HasEnded():
                        txn.RollBack()
                except Exception:
                    pass
                raise

            return routes.make_response(data={
                "status": "success",
                "moved": moved,
                "total_bridas": len(bridas),
                "errors": errors,
            })
        except Exception as e:
            log_route_error("extend_bridas_inferior", e)
            logger.error("extend_bridas_inferior failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/disallow_by_ids/", methods=["POST"])
    def disallow_by_ids(doc, request):
        """Aplica DisallowJoinAtEnd a ambos extremos de los elementos cuyas
        ids se pasan en el body: {"ids": [2103189, 2103190, ...]}
        """
        try:
            data = request.data
            if isinstance(data, str):
                data = json.loads(data)
            ids = list(data.get("ids", []))
            t = DB.Transaction(doc, "DisallowJoinAtEnd por ids")
            t.Start()
            ok, fail = [], []
            for i in ids:
                el = doc.GetElement(DB.ElementId(int(i)))
                if el is None or not hasattr(el, "GetCurves"):
                    fail.append({"id": i, "reason": "not framing"})
                    continue
                try:
                    _SFU.DisallowJoinAtEnd(el, 0)
                    _SFU.DisallowJoinAtEnd(el, 1)
                    ok.append(i)
                except Exception as e:
                    fail.append({"id": i, "reason": str(e)})
            t.Commit()
            return routes.make_response(
                data={"ok": ok, "fail": fail, "count_ok": len(ok)},
                status=200,
            )
        except Exception as e:
            log_route_error(e)
            return routes.make_response(
                data={"error": str(e)}, status=500,
            )

    @api.route("/remall_arc_165/", methods=["POST"])
    def remall_arc_165(doc, request):
        """Remalla el entramado del arco a paso uniforme sobre el arco.

        Paso por defecto 1.65 m sobre la brida superior (R~14.16). Correas y
        radiales se colocan en nodos simetricos alrededor de la corona. El
        ultimo tramo cerca a la columna se elimina (no se crea nodo en la
        columna, sin recortes).

        Body: {"dry_run": true, "step_m": 1.65}
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) \
                        if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            dry_run = bool(body.get("dry_run", False))
            try:
                STEP = float(body.get("step_m", 1.65))
            except Exception:
                STEP = 1.65
            try:
                LIFT = float(body.get("lift_m", 0.125))
            except Exception:
                LIFT = 0.125
            FT = FT_PER_M

            cat = DB.BuiltInCategory.OST_StructuralFraming
            els = DB.FilteredElementCollector(doc)\
                .OfCategory(cat).WhereElementIsNotElementType().ToElements()

            top_arcs = []
            bot_arcs = []
            web_els = []
            corr_els = []
            for el in els:
                try:
                    lc = el.Location
                    curve = lc.Curve if hasattr(lc, "Curve") else None
                    if curve is None:
                        continue
                    tn = _norm(get_element_name(el.Symbol))
                    if tn == "hss100x50x3" and isinstance(curve, DB.Arc):
                        top_arcs.append((el, curve, curve.Center.Y / FT))
                        continue
                    if tn == "hss100x50x45" and isinstance(curve, DB.Arc):
                        bot_arcs.append((el, curve, curve.Center.Y / FT))
                        continue
                    if tn == "hss150x50x3":
                        corr_els.append(el)
                        continue
                    if "hss50x50x2" in tn and isinstance(curve, DB.Line):
                        p = curve.GetEndPoint(0)
                        q = curve.GetEndPoint(1)
                        if abs(p.Y - q.Y) < 0.05 * FT:
                            web_els.append(el)
                except Exception:
                    continue

            level = lowest_level(doc)
            web_sym = None
            corr_sym = None
            for s in DB.FilteredElementCollector(doc)\
                     .OfClass(DB.FamilySymbol).ToElements():
                n = _norm(get_element_name(s))
                if web_sym is None and "hss50x50x2" in n:
                    web_sym = s
                if corr_sym is None and n == "hss150x50x3":
                    corr_sym = s
                if web_sym and corr_sym:
                    break
            for s in (web_sym, corr_sym):
                if s is not None and not s.IsActive:
                    s.Activate()

            # nodos por plano Y sobre la brida superior (paso 1.65 m sobre arco)
            plans = []
            for el_t, arc_t, cy in sorted(top_arcs, key=lambda t: t[2]):
                botc = None
                for el_b, arc_b, by in bot_arcs:
                    if abs(by - cy) < 0.05:
                        botc = arc_b
                        break
                if botc is None:
                    continue
                cx = arc_t.Center.X / FT
                cz = arc_t.Center.Z / FT
                rt = arc_t.Radius / FT
                rb = botc.Radius / FT
                # angulo de cada extremo del arco: izquierdo pasa por (0,6.2),
                # derecho por (22.65,6.2), ambos con centro (cx,cz)
                ang_left = math.atan2((6.2 - cz), (0.0 - cx))
                ang_right = math.atan2((6.2 - cz), (22.65 - cx))
                mid = math.pi / 2.0
                step = STEP / rt
                span_half = abs(mid - ang_left)
                k = int(span_half // step)
                angs = [mid]
                for i in range(1, k + 1):
                    angs.append(mid - i * step)
                    angs.append(mid + i * step)
                angs.sort()
                nodes = []
                for a in angs:
                    ca = math.cos(a)
                    sa = math.sin(a)
                    tx = cx + rt * ca
                    tz = cz + rt * sa
                    bx = cx + rb * ca
                    bz = cz + rb * sa
                    nodes.append((a, tx, tz, bx, bz))
                plans.append({
                    "cy": round(cy, 3),
                    "cx": round(cx, 3),
                    "n": len(nodes),
                    "k": k,
                    "step_arc_m": round(STEP, 3),
                    # tramo sin nodos hasta la columna (se deja vacio)
                    "gap_left_m": round((ang_right - angs[0]) * rt, 3),
                    "gap_right_m": round((angs[-1] - ang_left) * rt, 3),
                    "nodes": nodes,
                })

            total_web_new = sum(pl["n"] * 2 - 1 for pl in plans)
            total_corr_new = 6 * sum(pl["n"] for pl in plans) // 7

            if dry_run:
                return routes.make_response(data={
                    "status": "success", "dry_run": True,
                    "step_m": STEP,
                    "planes": len(plans),
                    "n_nodes_por_portico": [pl["n"] for pl in plans],
                    "gap_por_portico": [[pl["gap_left_m"], pl["gap_right_m"]]
                                        for pl in plans],
                    "web_borrar": len(web_els),
                    "correas_borrar": len(corr_els),
                    "web_nuevo": total_web_new,
                    "correas_nuevas": total_corr_new,
                    "primer_plano": plans[0] if plans else None,
                })

            errors = []
            created_web = 0
            created_corr = 0
            try:
                import os
                dbg = os.path.join(os.environ.get("TEMP", "C:/Users/aintc/AppData/Local/Temp"),
                                   "remall_plan_dbg.json")
                lines = []
                for pl in plans:
                    lines.append({
                        "cy": pl["cy"], "n": pl["n"], "k": pl["k"],
                        "gap_l": pl["gap_left_m"], "gap_r": pl["gap_right_m"],
                        "nodes": pl["nodes"],
                    })
                with open(dbg, "w") as fh:
                    json.dump(lines, fh, indent=1)
            except Exception:
                pass
            t = _new_txn(doc, "Remallado arco paso 1.65")
            t.Start()
            try:
                for el in web_els:
                    try:
                        doc.Delete(el.Id)
                    except Exception:
                        pass
                for el in corr_els:
                    try:
                        doc.Delete(el.Id)
                    except Exception:
                        pass

                bays = [0.0, 5.05, 10.1, 15.15, 20.2, 25.25]
                created_log = []
                for pl in plans:
                    cy = pl["cy"]
                    nodes = pl["nodes"]
                    n = len(nodes)
                    for i in range(n):
                        a, tx, tz, bx, bz = nodes[i]
                        try:
                            bot_pt = DB.XYZ(bx * FT, cy * FT, bz * FT)
                            top_pt = DB.XYZ(tx * FT, cy * FT, tz * FT)
                            line = DB.Line.CreateBound(bot_pt, top_pt)
                            ni = doc.Create.NewFamilyInstance(
                                line, web_sym, level,
                                DB.Structure.StructuralType.Brace)
                            _SFU.DisallowJoinAtEnd(ni, 0)
                            _SFU.DisallowJoinAtEnd(ni, 1)
                            created_web += 1
                            created_log.append(("rad", cy, bx, bz, tx, tz,
                                                element_id_value(ni.Id)))
                        except Exception as e2:
                            if len(errors) < 8:
                                errors.append(
                                    "radial y=%s i=%s: %s" % (cy, i, str(e2)[:160]))
                        if i < n - 1:
                            a2, tx2, tz2, bx2, bz2 = nodes[i + 1]
                            try:
                                d = DB.Line.CreateBound(
                                    DB.XYZ(bx * FT, cy * FT, bz * FT),
                                    DB.XYZ(tx2 * FT, cy * FT, tz2 * FT))
                                ni = doc.Create.NewFamilyInstance(
                                    d, web_sym, level,
                                    DB.Structure.StructuralType.Brace)
                                _SFU.DisallowJoinAtEnd(ni, 0)
                                _SFU.DisallowJoinAtEnd(ni, 1)
                                created_web += 1
                                created_log.append(("diag", cy, bx, bz, tx2, tz2,
                                                    element_id_value(ni.Id)))
                            except Exception as e2:
                                if len(errors) < 8:
                                    errors.append(
                                        "diag y=%s i=%s: %s" % (cy, i, str(e2)[:160]))
                try:
                    with open(os.path.join(
                        os.environ.get("TEMP", "C:/Users/aintc/AppData/Local/Temp"),
                        "remall_created.json"), "w") as fh:
                        json.dump(created_log, fh)
                except Exception:
                    pass
                # correas: 1 por nodo X del arco y por bahia Y (compartidas entre
                # porticos; las posiciones X de todos los porticos son iguales)
                # se levantan LIFT sobre la brida superior (apoyadas encima)
                ref_nodes = plans[0]["nodes"] if plans else []
                for i in range(len(ref_nodes)):
                    a, tx, tz, bx, bz = ref_nodes[i]
                    cz_c = tz + LIFT
                    for y0 in bays:
                        try:
                            c = DB.Line.CreateBound(
                                DB.XYZ(tx * FT, y0 * FT, cz_c * FT),
                                DB.XYZ(tx * FT, (y0 + 5.05) * FT, cz_c * FT))
                            doc.Create.NewFamilyInstance(
                                c, corr_sym, level,
                                DB.Structure.StructuralType.Beam)
                            created_corr += 1
                        except Exception as e2:
                            if len(errors) < 8:
                                errors.append(
                                    "correa i=%s y0=%s: %s" % (
                                        i, y0, str(e2)[:160]))
                t.Commit()
            except Exception:
                try:
                    if t.HasStarted() and not t.HasEnded():
                        t.RollBack()
                except Exception:
                    pass
                raise

            return routes.make_response(data={
                "status": "success",
                "web_borrado": len(web_els),
                "correas_borradas": len(corr_els),
                "web_creado": created_web,
                "correas_creadas": created_corr,
                "errors": errors,
            })
        except Exception as e:
            log_route_error("remall_arc_165", e)
            logger.error("remall_arc_165 failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/probe_web_mesh/", methods=["POST"])
    def probe_web_mesh(doc, request):
        """SOLO LECTURA. Lista todos los miembros HSS50x50x2 / HSS50x50x2.5
        (entramado web) del modelo, agrupados por plano Y, con sus extremos
        (X, Z) en metros y tipo. Util para comparar la malla actual contra
        el .s2k y detectar montantes/diagonales faltantes o desplazados.
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            members = [e for e in DB.FilteredElementCollector(doc)
                       .OfCategory(DB.BuiltInCategory.OST_StructuralFraming)
                       .WhereElementIsNotElementType().ToElements()
                       if _is_member_web(e)]
            planes = {}
            for m in members:
                try:
                    lc = m.Location
                    c = lc.Curve if hasattr(lc, "Curve") else None
                    if c is None or not isinstance(c, DB.Line):
                        continue
                    p = c.GetEndPoint(0)
                    q = c.GetEndPoint(1)
                    y = round((p.Y + q.Y) / 2.0 / FT_PER_M, 2)
                    eid = int(str(m.Id).replace("ElementId(", "").replace(")", ""))
                    planes.setdefault(y, []).append({
                        "id": eid,
                        "type": _norm(get_element_name(m.Symbol)),
                        "p1": [round(p.X / FT_PER_M, 3), round(p.Z / FT_PER_M, 3)],
                        "p2": [round(q.X / FT_PER_M, 3), round(q.Z / FT_PER_M, 3)],
                    })
                except Exception:
                    continue
            out = []
            for y, items in sorted(planes.items()):
                out.append({"y": y, "count": len(items), "members": items})
            return routes.make_response(data={
                "status": "success",
                "planes": len(planes),
                "total": len(members),
                "mesh": out,
            })
        except Exception as e:
            log_route_error("probe_web_mesh", e)
            logger.error("probe_web_mesh failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/probe_purlins_meta/", methods=["POST"])
    def probe_purlins_meta(doc, request):
        """SOLO LECTURA. Lista las correas HSS150x50x3 (largas) del modelo con
        su X y Z de linea central, para ubicar la correa de extremo sin montante.
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            cat = DB.BuiltInCategory.OST_StructuralFraming
            els = DB.FilteredElementCollector(doc)\
                .OfCategory(cat).WhereElementIsNotElementType().ToElements()
            purlins = []
            for el in els:
                try:
                    tn = _norm(get_element_name(el.Symbol))
                    if tn != "hss150x50x3":
                        continue
                    lc = el.Location
                    c = lc.Curve if hasattr(lc, "Curve") else None
                    if c is None:
                        continue
                    p = c.GetEndPoint(0)
                    q = c.GetEndPoint(1)
                    x = round((p.X + q.X) / 2.0 / FT_PER_M, 3)
                    z = round((p.Z + q.Z) / 2.0 / FT_PER_M, 3)
                    purlins.append({
                        "id": int(str(el.Id).replace("ElementId(", "").replace(")", "")),
                        "x_m": x, "z_m": z,
                        "len_m": round(c.Length / FT_PER_M, 3),
                    })
                except Exception:
                    continue
            purlins.sort(key=lambda r: r["x_m"])
            return routes.make_response(data={
                "status": "success",
                "count": len(purlins),
                "purlins": purlins,
            })
        except Exception as e:
            log_route_error("probe_purlins_meta", e)
            logger.error("probe_purlins_meta failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/probe_arches/", methods=["POST"])
    def probe_arches(doc, request):
        """SOLO LECTURA. Lista los arcos reales de brida superior (HSS100x50x3)
        e inferior (HSS100x50x4.5) del modelo: plano Y, centro, radio, extremos.
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            cat = DB.BuiltInCategory.OST_StructuralFraming
            els = DB.FilteredElementCollector(doc)\
                .OfCategory(cat).WhereElementIsNotElementType().ToElements()
            out = {"sup": [], "inf": []}
            for el in els:
                try:
                    tn = _norm(get_element_name(el.Symbol))
                    if tn not in ("hss100x50x3", "hss100x50x45"):
                        continue
                    lc = el.Location
                    c = lc.Curve if hasattr(lc, "Curve") else None
                    if c is None or not isinstance(c, DB.Arc):
                        continue
                    eid = int(str(el.Id).replace("ElementId(", "").replace(")", ""))
                    rec = {
                        "id": eid,
                        "y_m": round(c.Center.Y / FT_PER_M, 2),
                        "cx_m": round(c.Center.X / FT_PER_M, 3),
                        "cz_m": round(c.Center.Z / FT_PER_M, 3),
                        "r_m": round(c.Radius / FT_PER_M, 3),
                        "s_m": [round(c.GetEndPoint(0).X / FT_PER_M, 3),
                                round(c.GetEndPoint(0).Z / FT_PER_M, 3)],
                        "e_m": [round(c.GetEndPoint(1).X / FT_PER_M, 3),
                                round(c.GetEndPoint(1).Z / FT_PER_M, 3)],
                        "ang_deg": round(math.degrees(c.EndAngle - c.StartAngle), 2),
                    }
                    out["sup" if tn == "hss100x50x3" else "inf"].append(rec)
                except Exception:
                    continue
            for k in ("sup", "inf"):
                out[k].sort(key=lambda r: r["y_m"])
            return routes.make_response(data={
                "status": "success",
                "sup": out["sup"], "inf": out["inf"],
            })
        except Exception as e:
            log_route_error("probe_arches", e)
            logger.error("probe_arches failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/fix_edge_purlins/", methods=["POST"])
    def fix_edge_purlins(doc, request):
        """Completa los extremos del arco superior:
          1. Detecta las 2 correas de borde (HSS150x50x3 en X min y X max) y la
             penultima en cada lado.
          2. Calcula la nueva posicion de la correa de borde desplazandola
             REDUCE_M m (0.10) a lo largo de la curvatura del arco superior
             (circulo centro (11.325,-2.3), R=14.16) hacia el centro, y la
             mueve (dx, dz) manteniendo su Y.
          3. Asegura la MONTANTE de extremo en cada plano Y del tijeral
             (HSS50x50x2 desde el arranque de la brida inferior hasta la brida
             superior en la nueva X de la correa de borde), recreando la
             izquierda y creando la derecha que falta.
        Body: {"dry_run": true|false}
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) \
                        if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            dry_run = bool(body.get("dry_run", False))
            FT = FT_PER_M

            REDUCE_M = 0.10
            CX = 11.325
            CZ = -2.3
            R = 14.16
            Y_LEVELS = [0.0, 5.05, 10.1, 15.15, 20.2, 25.25, 30.3]

            cat = DB.BuiltInCategory.OST_StructuralFraming
            els = DB.FilteredElementCollector(doc)\
                .OfCategory(cat).WhereElementIsNotElementType().ToElements()

            purlins = []
            web_els = []
            top_arcs = {}
            web_sym = None
            for el in els:
                try:
                    lc = el.Location
                    curve = lc.Curve if hasattr(lc, "Curve") else None
                    if curve is None:
                        continue
                    tn = _norm(get_element_name(el.Symbol))
                    if tn == "hss150x50x3":
                        if isinstance(curve, DB.Line) and curve.Length > 5 * FT:
                            purlins.append(el)
                    elif _is_member_web(el) and isinstance(curve, DB.Line):
                        web_els.append(el)
                        if web_sym is None:
                            web_sym = el.Symbol
                    elif tn == "hss100x50x3" and isinstance(curve, DB.Arc):
                        y = round(curve.Center.Y / FT, 2)
                        top_arcs.setdefault(y, curve)
                except Exception:
                    continue

            if web_sym is not None and not web_sym.IsActive:
                web_sym.Activate()

            # ---- correas: ordenar por X, detectar bordes y penultimas ----
            p_infos = []
            for el in purlins:
                c = el.Location.Curve
                p0 = c.GetEndPoint(0)
                p1 = c.GetEndPoint(1)
                x = round((p0.X + p1.X) / 2.0 / FT, 3)
                z = round((p0.Z + p1.Z) / 2.0 / FT, 3)
                p_infos.append({
                    "el": el, "id": element_id_value(el.Id),
                    "x": x, "z": z,
                    "p0": [p0.X, p0.Y, p0.Z], "p1": [p1.X, p1.Y, p1.Z],
                })
            p_infos.sort(key=lambda r: r["x"])
            left = p_infos[0]
            right = p_infos[-1]
            left2 = p_infos[1]
            right2 = p_infos[-2]

            def z_arc(x_m):
                dx = x_m - CX
                d2 = R * R - dx * dx
                if d2 < 0:
                    return None
                return CZ + math.sqrt(d2)

            def arc_angle(x_m, z_m):
                return math.atan2(z_m - CZ, x_m - CX)

            def shift_toward_center(x_m, z_m, pen_x, pen_z, reduce_m):
                a0 = arc_angle(x_m, z_m)
                ap = arc_angle(pen_x, pen_z)
                da = abs(a0 - ap)
                da_new = da - reduce_m / R
                if da_new < 0.0:
                    da_new = 0.0
                if x_m < CX:
                    a_new = ap + da_new
                else:
                    a_new = ap - da_new
                nx = CX + R * math.cos(a_new)
                nz = CZ + R * math.sin(a_new)
                return round(nx, 4), round(nz, 4)

            left_nx, left_nz = shift_toward_center(
                left["x"], left["z"], left2["x"], left2["z"], REDUCE_M)
            right_nx, right_nz = shift_toward_center(
                right["x"], right["z"], right2["x"], right2["z"], REDUCE_M)

            left["nx"], left["nz"] = left_nx, left_nz
            right["nx"], right["nz"] = right_nx, right_nz
            left["dx_m"] = round(left_nx - left["x"], 4)
            left["dz_m"] = round(left_nz - left["z"], 4)
            right["dx_m"] = round(right_nx - right["x"], 4)
            right["dz_m"] = round(right_nz - right["z"], 4)

            # ---- montantes de extremo: geometria objetivo por plano ----
            # arranque brida inferior: izq (0.4, 5.9), der (22.25, 5.9) segun s2k
            edge_plan = []
            for y in Y_LEVELS:
                edge_plan.append({
                    "y": y, "side": "L",
                    "x": left_nx, "z_top": left_nz,
                    "p0": [0.4, y, 5.9], "p1": [left_nx, y, left_nz],
                })
                edge_plan.append({
                    "y": y, "side": "R",
                    "x": right_nx, "z_top": right_nz,
                    "p0": [22.25, y, 5.9], "p1": [right_nx, y, right_nz],
                })

            # identificar montantes de extremo existentes (tope en X~0 izq)
            existing = []
            for el, c in [(e, e.Location.Curve) for e in web_els]:
                p0 = c.GetEndPoint(0)
                p1 = c.GetEndPoint(1)
                xa, xb = p0.X / FT, p1.X / FT
                za, zb = p0.Z / FT, p1.Z / FT
                ya, yb = p0.Y / FT, p1.Y / FT
                if abs(ya - yb) > 0.05:
                    continue
                y = round((ya + yb) / 2.0, 2)
                # tope en el arranque sup X~0 (borde izq) o X~22.65 (borde der)
                topx = xb if zb > za else xa
                topz = zb if zb > za else za
                if abs(topx - 0.0) < 0.06 and abs(topz - 6.2) < 0.1:
                    existing.append({"id": element_id_value(el.Id), "y": y,
                                     "side": "L", "el": el})
                elif abs(topx - 22.65) < 0.06 and abs(topz - 6.2) < 0.1:
                    existing.append({"id": element_id_value(el.Id), "y": y,
                                     "side": "R", "el": el})

            if dry_run:
                return routes.make_response(data={
                    "status": "success", "dry_run": True,
                    "purlins": [{"id": r["id"], "x": r["x"], "z": r["z"]}
                                for r in p_infos],
                    "left": {"id": left["id"], "x": left["x"], "z": left["z"],
                             "nx": left_nx, "nz": left_nz,
                             "dx_m": left["dx_m"], "dz_m": left["dz_m"]},
                    "right": {"id": right["id"], "x": right["x"], "z": right["z"],
                              "nx": right_nx, "nz": right_nz,
                              "dx_m": right["dx_m"], "dz_m": right["dz_m"]},
                    "penult_left": {"id": left2["id"], "x": left2["x"],
                                    "z": left2["z"]},
                    "penult_right": {"id": right2["id"], "x": right2["x"],
                                     "z": right2["z"]},
                    "arc": {"cx": CX, "cz": CZ, "r": R},
                    "edge_plan": edge_plan,
                    "existing_edge_montants": existing,
                })

            errors = []
            moved = 0

            # ---- Txn 1: mover las 2 correas de borde (dx, 0, dz) ----
            t = _new_txn(doc, u"Correas de borde: desplazar 10 cm sobre arco")
            t.Start()
            try:
                for rec in (left, right):
                    try:
                        dx = rec["dx_m"]
                        dz = rec["dz_m"]
                        if abs(dx) < 1e-6 and abs(dz) < 1e-6:
                            continue
                        delta = DB.XYZ(dx * FT, 0.0, dz * FT)
                        DB.ElementTransformUtils.MoveElement(doc, rec["el"].Id, delta)
                        moved += 1
                    except Exception as e1:
                        if len(errors) < 8:
                            errors.append("move purlin %s: %s" % (
                                rec["id"], str(e1)[:160]))
                t.Commit()
            except Exception:
                try:
                    if t.HasStarted() and not t.HasEnded():
                        t.RollBack()
                except Exception:
                    pass
                raise

            # ---- Txn 2: montantes de extremo ----
            created = 0
            if web_sym is not None:
                t = _new_txn(doc, u"Montantes de extremo (correas de borde)")
                t.Start()
                try:
                    # borrar montantes de extremo izq existentes (se recrean)
                    for ex in existing:
                        try:
                            if ex["side"] == "L":
                                doc.Delete(ex["el"].Id)
                        except Exception:
                            pass
                    for rec in edge_plan:
                        try:
                            if rec["side"] == "R":
                                continue  # derecho se crea en txn3
                            p0 = DB.XYZ(rec["p0"][0] * FT, rec["p0"][1] * FT,
                                        rec["p0"][2] * FT)
                            p1 = DB.XYZ(rec["p1"][0] * FT, rec["p1"][1] * FT,
                                        rec["p1"][2] * FT)
                            line = DB.Line.CreateBound(p0, p1)
                            inst = doc.Create.NewFamilyInstance(
                                line, web_sym, lowest_level(doc),
                                DB.Structure.StructuralType.Brace)
                            try:
                                _SFU.DisallowJoinAtEnd(inst, 0)
                                _SFU.DisallowJoinAtEnd(inst, 1)
                            except Exception:
                                pass
                            created += 1
                        except Exception as e1:
                            if len(errors) < 8:
                                errors.append("edge L y=%s: %s" % (
                                    rec["y"], str(e1)[:160]))
                    t.Commit()
                except Exception:
                    try:
                        if t.HasStarted() and not t.HasEnded():
                            t.RollBack()
                    except Exception:
                        pass
                    raise

                t = _new_txn(doc, u"Montantes de extremo derecho")
                t.Start()
                try:
                    for rec in edge_plan:
                        try:
                            if rec["side"] == "L":
                                continue
                            p0 = DB.XYZ(rec["p0"][0] * FT, rec["p0"][1] * FT,
                                        rec["p0"][2] * FT)
                            p1 = DB.XYZ(rec["p1"][0] * FT, rec["p1"][1] * FT,
                                        rec["p1"][2] * FT)
                            line = DB.Line.CreateBound(p0, p1)
                            inst = doc.Create.NewFamilyInstance(
                                line, web_sym, lowest_level(doc),
                                DB.Structure.StructuralType.Brace)
                            try:
                                _SFU.DisallowJoinAtEnd(inst, 0)
                                _SFU.DisallowJoinAtEnd(inst, 1)
                            except Exception:
                                pass
                            created += 1
                        except Exception as e1:
                            if len(errors) < 8:
                                errors.append("edge R y=%s: %s" % (
                                    rec["y"], str(e1)[:160]))
                    t.Commit()
                except Exception:
                    try:
                        if t.HasStarted() and not t.HasEnded():
                            t.RollBack()
                    except Exception:
                        pass
                    raise

            return routes.make_response(data={
                "status": "success",
                "purlins_moved": moved,
                "edge_montants_created": created,
                "left": {"id": left["id"], "nx": left_nx, "nz": left_nz},
                "right": {"id": right["id"], "nx": right_nx, "nz": right_nz},
                "errors": errors,
            })
        except Exception as e:
            log_route_error("fix_edge_purlins", e)
            logger.error("fix_edge_purlins failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/align_extreme_members/", methods=["POST"])
    def align_extreme_members(doc, request):
        """Alinea la montante y diagonal del extremo derecho del primer tijeral
        (plano Y=0, extremo X~22.65):

          1. MONTANTE: mantiene su nudo inferior (distancia/angulo actual sobre
             el arco inferior) y se reorienta para quedar PERPENDICULAR a la
             curvatura: ambos extremos sobre la misma linea radial que pasa por
             el centro del arco (nudo sup sobre el arco superior).
          2. DIAGONAL: se alinea punto a punto de montante a montante siguiendo
             el patron del tijeral: del nudo INFERIOR de la montante del extremo
             al nudo SUPERIOR de la montante contigua hacia el centro.

        Body: {"dry_run": true|false, "montant_id": 2132256, "diag_id": 2132460}
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) \
                        if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            dry_run = bool(body.get("dry_run", False))
            m_id = int(body.get("montant_id", 0))
            d_id = int(body.get("diag_id", 0))
            FT = FT_PER_M

            cat = DB.BuiltInCategory.OST_StructuralFraming
            els = DB.FilteredElementCollector(doc)\
                .OfCategory(cat).WhereElementIsNotElementType().ToElements()

            montant = doc.GetElement(DB.ElementId(long(m_id))) if m_id else None
            diag = doc.GetElement(DB.ElementId(long(d_id))) if d_id else None
            if montant is None or diag is None:
                # auto-deteccion: montante del extremo derecho del primer
                # tijeral (Y=0): miembro web corto cuyo nudo inferior (menor Z)
                # tiene la mayor X; la diagonal es el miembro web largo que
                # comparte ese nudo inferior.
                cand = []
                for el in els:
                    lc = el.Location
                    curve = lc.Curve if hasattr(lc, "Curve") else None
                    if curve is None or not isinstance(curve, DB.Line):
                        continue
                    if not _is_member_web(el):
                        continue
                    pa = curve.GetEndPoint(0)
                    pb = curve.GetEndPoint(1)
                    if abs((pa.Y + pb.Y) / 2.0 / FT - 0.0) > 0.05:
                        continue
                    length = math.hypot(
                        (pa.X - pb.X) / FT, (pa.Z - pb.Z) / FT)
                    cand.append((el, curve, pa, pb, length))
                montant = None
                m_curve = None
                m_bot = None
                for el, curve, pa, pb, length in cand:
                    if length > 0.8:
                        continue
                    bot = pa if pa.Z < pb.Z else pb
                    if montant is None or bot.X > m_bot.X:
                        montant, m_curve, m_bot = el, curve, bot
                diag = None
                if montant is not None:
                    for el, curve, pa, pb, length in cand:
                        if el.Id == montant.Id:
                            continue
                        if length <= 0.8:
                            continue
                        if _pts_close(pa, m_bot) or _pts_close(pb, m_bot):
                            diag = el
                            break
                if montant is None or diag is None:
                    return routes.make_response(
                        data={"error": "montante/diagonal del extremo no detectadas "
                                      "(pase montant_id y diag_id)"},
                        status=400)
                m_id = element_id_value(montant.Id)
                d_id = element_id_value(diag.Id)

            mcurve = montant.Location.Curve
            p = mcurve.GetEndPoint(0)
            q = mcurve.GetEndPoint(1)
            y = round((p.Y + q.Y) / 2.0 / FT, 2)

            top_arc = None
            bot_arc = None
            for el in els:
                lc = el.Location
                curve = lc.Curve if hasattr(lc, "Curve") else None
                if curve is None or not isinstance(curve, DB.Arc):
                    continue
                tn = _norm(get_element_name(el.Symbol))
                if abs(curve.Center.Y / FT - y) > 0.05:
                    continue
                if tn == "hss100x50x3":
                    top_arc = curve
                elif tn == "hss100x50x45":
                    bot_arc = curve
            if top_arc is None or bot_arc is None:
                return routes.make_response(
                    data={"error": "arcos sup/inf no encontrados en plano %s" % y},
                    status=500)

            C = (top_arc.Center.X / FT, top_arc.Center.Z / FT)
            R_top = top_arc.Radius / FT
            R_bot = bot_arc.Radius / FT

            # nudo inferior actual de la montante (extremo sobre arco inf = menor Z)
            p0m = mcurve.GetEndPoint(0)
            p1m = mcurve.GetEndPoint(1)
            bot_pt = p0m if p0m.Z < p1m.Z else p1m
            ang = math.atan2(bot_pt.Z / FT - C[1], bot_pt.X / FT - C[0])
            n_inf = (round(C[0] + R_bot * math.cos(ang), 4),
                     round(C[1] + R_bot * math.sin(ang), 4))
            n_sup = (round(C[0] + R_top * math.cos(ang), 4),
                     round(C[1] + R_top * math.sin(ang), 4))

            # montante contigua hacia el centro: montante (corta) cuyo nudo
            # superior es el mas cercano en X menor que el nudo inferior nuevo
            cont_sup = None
            for el in els:
                lc = el.Location
                curve = lc.Curve if hasattr(lc, "Curve") else None
                if curve is None or not isinstance(curve, DB.Line):
                    continue
                if el.Id == montant.Id or el.Id == diag.Id:
                    continue
                if not _is_member_web(el):
                    continue
                pa = curve.GetEndPoint(0)
                pb = curve.GetEndPoint(1)
                if abs((pa.Y + pb.Y) / 2.0 / FT - y) > 0.05:
                    continue
                ca = (pa.X / FT, pa.Z / FT)
                cb = (pb.X / FT, pb.Z / FT)
                if math.hypot(ca[0] - cb[0], ca[1] - cb[1]) > 0.8:
                    continue
                sup = ca if ca[1] > cb[1] else cb
                if sup[0] < n_inf[0] - 0.05:
                    if cont_sup is None or sup[0] > cont_sup[0]:
                        cont_sup = sup
            if cont_sup is None:
                return routes.make_response(
                    data={"error": "montante contigua no encontrada"},
                    status=500)
            cont_sup = (round(cont_sup[0], 4), round(cont_sup[1], 4))

            plan = {
                "plano_y": y,
                "centro": [round(C[0], 3), round(C[1], 3)],
                "R_top": round(R_top, 3),
                "R_bot": round(R_bot, 3),
                "montant": {
                    "id": m_id,
                    "old_inf_m": [round(bot_pt.X / FT, 4), round(bot_pt.Z / FT, 4)],
                    "new_inf_m": list(n_inf),
                    "new_sup_m": list(n_sup),
                },
                "diagonal": {
                    "id": d_id,
                    "new_inf_m": list(n_inf),
                    "new_sup_m": list(cont_sup),
                },
            }
            if dry_run:
                return routes.make_response(data={
                    "status": "success", "dry_run": True, "plan": plan})

            def _guid_of(inst):
                try:
                    gp = inst.get_Parameter(DB.BuiltInParameter.IFC_GUID)
                    if gp:
                        return gp.AsString() or ""
                except Exception:
                    pass
                return ""

            def _set_guid(inst, guid):
                if not guid:
                    return
                try:
                    gp = inst.get_Parameter(DB.BuiltInParameter.IFC_GUID)
                    if gp and not gp.IsReadOnly:
                        gp.Set(guid)
                except Exception:
                    pass

            m_sym = montant.Symbol
            d_sym = diag.Symbol
            if not m_sym.IsActive:
                m_sym.Activate()
            if not d_sym.IsActive:
                d_sym.Activate()
            level = lowest_level(doc)
            m_guid = _guid_of(montant)
            d_guid = _guid_of(diag)

            errors = []
            recreated = []
            t = _new_txn(doc, u"Alinear montante y diagonal del extremo")
            t.Start()
            try:
                for rec, orig, sym, guid in (
                        (("montant", n_inf, n_sup), montant, m_sym, m_guid),
                        (("diag", n_inf, cont_sup), diag, d_sym, d_guid)):
                    tag = rec[0]
                    a = rec[1]
                    b = rec[2]
                    try:
                        old_id = element_id_value(orig.Id)
                        p0 = DB.XYZ(a[0] * FT, y * FT, a[1] * FT)
                        p1 = DB.XYZ(b[0] * FT, y * FT, b[1] * FT)
                        line = DB.Line.CreateBound(p0, p1)
                        doc.Delete(orig.Id)
                        inst = doc.Create.NewFamilyInstance(
                            line, sym, level, DB.Structure.StructuralType.Brace)
                        try:
                            _SFU.DisallowJoinAtEnd(inst, 0)
                            _SFU.DisallowJoinAtEnd(inst, 1)
                        except Exception:
                            pass
                        _set_guid(inst, guid)
                        recreated.append({
                            "tag": tag,
                            "old_id": old_id,
                            "new_id": element_id_value(inst.Id),
                            "from_m": list(a),
                            "to_m": list(b),
                        })
                    except Exception as e1:
                        if len(errors) < 5:
                            errors.append("%s: %s" % (tag, str(e1)[:160]))
                t.Commit()
            except Exception:
                try:
                    if t.HasStarted() and not t.HasEnded():
                        t.RollBack()
                except Exception:
                    pass
                raise

            return routes.make_response(data={
                "status": "success",
                "recreated": recreated,
                "errors": errors,
            })
        except Exception as e:
            log_route_error("align_extreme_members", e)
            logger.error("align_extreme_members failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/symmetrize_web/", methods=["POST"])
    def symmetrize_web(doc, request):
        """Hace SIMETRICA la malla del tijeral respecto al eje central X=11.325:
        toma como referencia la mitad DERECHA (X>centro, que ya tiene la montante
        y diagonal del extremo corregidas) y la espeja hacia la IZQUIERDA.

        Por cada miembro derecho crea su espejo en la izquierda si falta, y borra
        los miembros izquierdos que no corresponden a ningun espejo (diagonales en
        zigzag invertido y elementos sobrantes de extremo).

        Body: {"dry_run": true|false, "planes": [0, 5.05] | [] = todos}
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) \
                        if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            dry_run = bool(body.get("dry_run", False))
            planes_req = body.get("planes") or []
            FT = FT_PER_M
            CX = 22.65 / 2.0

            cat = DB.BuiltInCategory.OST_StructuralFraming
            els = [e for e in DB.FilteredElementCollector(doc)
                   .OfCategory(cat).WhereElementIsNotElementType().ToElements()
                   if _is_member_web(e)]

            by_plane = {}
            for el in els:
                try:
                    lc = el.Location
                    c = lc.Curve if hasattr(lc, "Curve") else None
                    if c is None or not isinstance(c, DB.Line):
                        continue
                    p = c.GetEndPoint(0)
                    q = c.GetEndPoint(1)
                    y = round((p.Y + q.Y) / 2.0 / FT, 2)
                    by_plane.setdefault(y, []).append(el)
                except Exception:
                    continue

            def _key(pa, pb):
                a = (round(pa[0], 3), round(pa[1], 3))
                b = (round(pb[0], 3), round(pb[1], 3))
                return tuple(sorted([a, b]))

            def _endpoints(el):
                c = el.Location.Curve
                pa = c.GetEndPoint(0)
                pb = c.GetEndPoint(1)
                return (pa.X / FT, pa.Z / FT), (pb.X / FT, pb.Z / FT)

            def _midx(pa, pb):
                return (pa[0] + pb[0]) / 2.0

            all_planes = sorted(by_plane.keys())
            planes = [float(x) for x in planes_req] if planes_req else all_planes
            planes = [p for p in planes if p in by_plane]

            report = []
            errors = []
            created_list = []
            deleted_list = []
            if not dry_run:
                t = _new_txn(doc, u"Simetrizar malla del tijeral")
                t.Start()
            try:
                for y in planes:
                    mems = by_plane[y]
                    lookup = {}
                    for el in mems:
                        pa, pb = _endpoints(el)
                        lookup[_key(pa, pb)] = el
                    right = []
                    for el in mems:
                        pa, pb = _endpoints(el)
                        if _midx(pa, pb) > CX + 0.01:
                            right.append(el)
                    left = []
                    for el in mems:
                        pa, pb = _endpoints(el)
                        if _midx(pa, pb) < CX - 0.01:
                            left.append(el)
                    mirror_map = []
                    for el in right:
                        pa, pb = _endpoints(el)
                        ma = (round(CX * 2 - pa[0], 3), round(pa[1], 3))
                        mb = (round(CX * 2 - pb[0], 3), round(pb[1], 3))
                        key = _key(ma, mb)
                        mirror_map.append((el, key))
                    left_keys = set()
                    for el in left:
                        pa, pb = _endpoints(el)
                        left_keys.add(_key(pa, pb))
                    to_create = []
                    for el, key in mirror_map:
                        if key not in left_keys:
                            to_create.append(el)
                    valid_left_keys = set(k for _, k in mirror_map)
                    to_delete = []
                    for el in left:
                        pa, pb = _endpoints(el)
                        if _key(pa, pb) not in valid_left_keys:
                            to_delete.append(el)

                    report.append({
                        "plane_y": y,
                        "right_members": len(right),
                        "left_members": len(left),
                        "create_mirror": [element_id_value(el.Id) for el in to_create],
                        "delete_left": [element_id_value(el.Id) for el in to_delete],
                    })

                    if not dry_run:
                        level = lowest_level(doc)
                        for el in to_create:
                            try:
                                pa, pb = _endpoints(el)
                                ma = DB.XYZ((CX * 2 - pa[0]) * FT, y * FT, pa[1] * FT)
                                mb = DB.XYZ((CX * 2 - pb[0]) * FT, y * FT, pb[1] * FT)
                                line = DB.Line.CreateBound(ma, mb)
                                sym = el.Symbol
                                if not sym.IsActive:
                                    sym.Activate()
                                inst = doc.Create.NewFamilyInstance(
                                    line, sym, level,
                                    DB.Structure.StructuralType.Brace)
                                try:
                                    _SFU.DisallowJoinAtEnd(inst, 0)
                                    _SFU.DisallowJoinAtEnd(inst, 1)
                                except Exception:
                                    pass
                                created_list.append({
                                    "plane_y": y,
                                    "mirror_of": element_id_value(el.Id),
                                    "new_id": element_id_value(inst.Id),
                                    "from_m": [round(ma.X / FT, 3), round(ma.Z / FT, 3)],
                                    "to_m": [round(mb.X / FT, 3), round(mb.Z / FT, 3)],
                                })
                            except Exception as e1:
                                if len(errors) < 5:
                                    errors.append(
                                        "crear espejo de %s: %s" % (
                                            element_id_value(el.Id), str(e1)[:160]))
                        for el in to_delete:
                            try:
                                deleted_list.append({
                                    "plane_y": y,
                                    "id": element_id_value(el.Id),
                                })
                                doc.Delete(el.Id)
                            except Exception as e1:
                                if len(errors) < 5:
                                    errors.append(
                                        "borrar %s: %s" % (
                                            element_id_value(el.Id), str(e1)[:160]))
                if not dry_run:
                    t.Commit()
            except Exception:
                if not dry_run:
                    try:
                        if t.HasStarted() and not t.HasEnded():
                            t.RollBack()
                    except Exception:
                        pass
                raise

            return routes.make_response(data={
                "status": "success",
                "dry_run": dry_run,
                "cx_m": CX,
                "planes_checked": len(planes),
                "plan": report,
                "created": created_list,
                "deleted": deleted_list,
                "errors": errors,
            })
        except Exception as e:
            log_route_error("symmetrize_web", e)
            logger.error("symmetrize_web failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)
