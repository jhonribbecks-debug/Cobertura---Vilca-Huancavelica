# -*- coding: UTF-8 -*-
"""Rutas para crear los tipos de seccion estructural en Revit.

Las secciones del .s2k (p. ej. HSS100x50x4.5) no existen como tipos en Revit.
Este modulo crea los tipos usando las familias parametricas YA CARGADAS en el
proyecto (p. ej. "HSS Rectangular", "Round Bar") via Document.EditFamily(),
o desde archivos .rfa de una libreria de contenido si se indican rutas.

Flujo:
  1. Encuentra las familias base (tubo rectangular HSS, barra redonda, y
     columna HSS) en el proyecto o en la libreria.
  2. Abre la familia (EditFamily), crea el tipo con las dimensiones del .s2k
     (t3/t2/tf en metros -> pies internos), guarda un .rfa temporal y lo
     carga al proyecto.
  3. Devuelve un family_map listo para import_s2k.
"""

import logging
import os
import tempfile

from pyrevit import routes, DB

from revit_mcp.utils import (
    normalize_string,
    element_id_value,
    get_element_name,
    log_route_error,
)

logger = logging.getLogger(__name__)

FT_PER_M = 1.0 / 0.3048
DEFAULT_CONTENT_ROOT = r"C:\ProgramData\Autodesk\RVT 2027\Libraries"

DIM_TARGETS = {
    "depth": ("depth", "d", "height", "h", "altura", "alto", "ht"),
    "width": ("width", "b", "w", "anchura", "ancho", "base"),
    "thickness": ("grosor nominal de pared", "thickness", "wall thickness",
                  "wall", "t", "t1", "espesor"),
    "diameter": ("diameter", "dia", "d", "radius"),
}

# (familia, hint) para identificar familias base en el proyecto
HSS_FAMILY_HINTS = [
    ("hss", "hueca"),
    ("hss", "rectang"),
    ("hss", "square"),
    ("hss", "hollow"),
    ("rectang", "hollow"),
    ("rectang", "tube"),
    ("tubular",),
]
BAR_FAMILY_HINTS = [
    ("round", "bar"),
    ("barra", "redonda"),
    ("bar", "redonda"),
    ("circular", "bar"),
]
COLUMN_HSS_HINTS = [
    ("hss", "hueca"),
    ("hss", "rectang"),
    ("hss", "square"),
    ("hss",),
    ("hollow", "column"),
    ("secciones", "huecas"),
]


def _body(request):
    data = request.data
    if isinstance(data, str):
        import json
        data = json.loads(data)
    return data if isinstance(data, dict) else {}


def _safe_name(name):
    import re
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)


# --------------------------------------------------------------------------- #
# Descubrimiento de familias base
# --------------------------------------------------------------------------- #
def _find_loaded_family(doc, category, hints):
    """Busca una familia cargada en el proyecto cuyo nombre cumpla los hints."""
    from pyrevit import DB as _DB
    unique = {}
    for sym in _DB.FilteredElementCollector(doc)\
                   .OfCategory(category)\
                   .WhereElementIsElementType()\
                   .ToElements():
        fam_name = normalize_string(get_element_name(sym.Family)).lower()
        if fam_name in (u"", u"unnamed"):
            continue
        for h in hints:
            if all(x in fam_name for x in h):
                fid = element_id_value(sym.Family.Id)
                if fid not in unique:
                    unique[fid] = (h, sym.Family)
                break
    if not unique:
        return None
    ordered = sorted(unique.values(), key=lambda x: hints.index(x[0]))
    return ordered[0][1]


def _loaded_family_names(doc, category):
    """Nombres de familias cargadas de una categoria (para diagnostico)."""
    from pyrevit import DB as _DB
    names = set()
    for sym in _DB.FilteredElementCollector(doc)\
                   .OfCategory(category)\
                   .WhereElementIsElementType()\
                   .ToElements():
        names.add(normalize_string(get_element_name(sym.Family)))
    return sorted(names)


def _find_project_families(doc):
    col_cat = DB.BuiltInCategory.OST_StructuralColumns
    fr_cat = DB.BuiltInCategory.OST_StructuralFraming
    return {
        "hss_framing": _find_loaded_family(doc, fr_cat, HSS_FAMILY_HINTS),
        "bar_framing": _find_loaded_family(doc, fr_cat, BAR_FAMILY_HINTS),
        "hss_column": _find_loaded_family(doc, col_cat, COLUMN_HSS_HINTS),
    }


def _find_project_families_info(doc):
    col_cat = DB.BuiltInCategory.OST_StructuralColumns
    fr_cat = DB.BuiltInCategory.OST_StructuralFraming
    hss_framing = _find_loaded_family(doc, fr_cat, HSS_FAMILY_HINTS)
    bar_framing = _find_loaded_family(doc, fr_cat, BAR_FAMILY_HINTS)
    hss_column = _find_loaded_family(doc, col_cat, COLUMN_HSS_HINTS)
    return {
        "hss_framing": get_element_name(hss_framing) if hss_framing else None,
        "bar_framing": get_element_name(bar_framing) if bar_framing else None,
        "hss_column": get_element_name(hss_column) if hss_column else None,
        "framing_families": _loaded_family_names(doc, fr_cat),
        "column_families": _loaded_family_names(doc, col_cat),
    }


# --------------------------------------------------------------------------- #
# Manejo de documentos de familia
# --------------------------------------------------------------------------- #
def _load_family(doc, path):
    """Carga una familia .rfa al proyecto. Devuelve (familia, error)."""
    try:
        return doc.LoadFamily(path), None
    except Exception as e1:
        try:
            mp = DB.ModelPathUtils.ConvertUserPathToModelPath(path)
            return doc.LoadFamily(mp), None
        except Exception as e2:
            return None, u"{} | {}".format(str(e1), str(e2))


def _open_family(app, path):
    try:
        return app.OpenDocument(path)
    except Exception as e1:
        try:
            mp = DB.ModelPathUtils.ConvertUserPathToModelPath(path)
            return app.OpenDocument(mp)
        except Exception as e2:
            raise Exception(u"open family failed ({}): {} | {}".format(path, e1, e2))


# --------------------------------------------------------------------------- #
# Parametros y dimensiones
# --------------------------------------------------------------------------- #
def _length_params(fm):
    params = []
    for p in fm.GetParameters():
        if p.StorageType != DB.StorageType.Double:
            continue
        if p.IsReadOnly:
            continue
        name = normalize_string(get_element_name(p.Definition)).lower()
        if name:
            params.append((name, p))
    return params


def _assign_dims(fm, dims_ft):
    """Asigna dimensiones (pies internos) al tipo actual.

    dims_ft: {"depth": v, "width": v, "thickness": v} o {"diameter": v}
    Devuelve (seteados, faltantes, disponibles).
    """
    params = _length_params(fm)
    available = [name for (name, _p) in params]
    used = set()
    done = []
    missing = []
    for role, value in dims_ft.items():
        assigned = False
        for cand in DIM_TARGETS.get(role, (role,)):
            for (name, p) in params:
                if name == cand and id(p) not in used:
                    try:
                        if role == "diameter" and cand == "radius":
                            fm.Set(p, value / 2.0)
                        else:
                            fm.Set(p, value)
                        used.add(id(p))
                        done.append((role, cand))
                        assigned = True
                        break
                    except Exception:
                        continue
            if assigned:
                break
        if not assigned:
            missing.append(role)
    return done, missing, available


def _set_symbol_dims(symbol, dims_ft):
    """Asigna dimensiones a un FamilySymbol (tipo) directamente en el proyecto."""
    params = {}
    for p in symbol.Parameters:
        d = p.Definition
        if d is None:
            continue
        name = normalize_string(d.Name).lower()
        if p.StorageType == DB.StorageType.Double and not p.IsReadOnly and name:
            params[name] = p
    available = list(params.keys())
    used = set()
    done = []
    missing = []
    for role, value in dims_ft.items():
        assigned = False
        for cand in DIM_TARGETS.get(role, (role,)):
            for name, p in params.items():
                if name == cand and id(p) not in used:
                    try:
                        if role == "diameter" and cand == "radius":
                            p.Set(value / 2.0)
                        else:
                            p.Set(value)
                        used.add(id(p))
                        done.append((role, cand))
                        assigned = True
                        break
                    except Exception:
                        continue
            if assigned:
                break
        if not assigned:
            missing.append(role)
    return done, missing, available


def _symbols_of_family(doc, family_name):
    """FamilySymbols de una familia por nombre, en framing y columnas."""
    out = []
    for cat in (DB.BuiltInCategory.OST_StructuralFraming,
                DB.BuiltInCategory.OST_StructuralColumns):
        for sym in DB.FilteredElementCollector(doc)\
                      .OfCategory(cat)\
                      .WhereElementIsElementType()\
                      .ToElements():
            try:
                if normalize_string(get_element_name(sym.Family)) == \
                        normalize_string(family_name):
                    out.append(sym)
            except Exception:
                continue
    return out


def _find_type_in_family(doc, family_name, type_name):
    for sym in _symbols_of_family(doc, family_name):
        if normalize_string(get_element_name(sym)) == normalize_string(type_name):
            return sym
    return None


def _create_types_via_duplicate(doc, family_obj, type_specs):
    """Crea tipos en el proyecto duplicando un symbol base de la familia.

    Usa ElementType.Duplicate() directamente en el documento de proyecto, sin
    editar la familia ni recargarla (LoadFamily falla en este entorno).
    """
    created = []
    errors = []
    debug = {"method": "duplicate"}
    if family_obj is None or not type_specs:
        return [], [], None, debug
    family_name = get_element_name(family_obj)
    syms = _symbols_of_family(doc, family_name)
    if not syms:
        return [], [u"no symbols for family '{}'".format(family_name)], None, debug
    base = syms[0]
    debug["base_type"] = get_element_name(base)
    for spec in type_specs:
        type_name = spec["type_name"]
        dims_m = spec.get("dims_m") or {}
        dims_ft = {k: float(v) * FT_PER_M for k, v in dims_m.items()}
        try:
            existing = _find_type_in_family(doc, family_name, type_name)
            txn = DB.Transaction(doc, u"Create type " + type_name)
            txn.Start()
            try:
                new_sym = existing if existing is not None else base.Duplicate(type_name)
                done, missing, available = _set_symbol_dims(new_sym, dims_ft)
                txn.Commit()
            except Exception:
                try:
                    if txn.HasStarted() and not txn.HasEnded():
                        txn.RollBack()
                except Exception:
                    pass
                raise
            created.append({
                "type": type_name,
                "existing": existing is not None,
                "dims_m": dims_m,
                "params_set": done,
                "params_missing": missing,
                "available_params": available,
                "family": family_name,
                "loaded_count": 1,
            })
        except Exception as e:
            errors.append(u"{}: {}".format(type_name, str(e)))
    return created, errors, None, debug


# --------------------------------------------------------------------------- #
# Creacion de tipos
# --------------------------------------------------------------------------- #
def _count_project_types(doc, type_name):
    """Cuantos FamilySymbols del proyecto coinciden con el nombre del tipo."""
    from pyrevit import DB as _DB
    n = 0
    for cat in (DB.BuiltInCategory.OST_StructuralFraming,
                DB.BuiltInCategory.OST_StructuralColumns):
        for sym in _DB.FilteredElementCollector(doc)\
                      .OfCategory(cat)\
                      .WhereElementIsElementType()\
                      .ToElements():
            if normalize_string(get_element_name(sym)) == normalize_string(type_name):
                n += 1
    return n


def _create_types_in_family_doc(doc, fam_doc, family_name, type_specs,
                                family_obj=None):
    """Crea los tipos en un documento de familia abierto y los carga al proyecto.

    La familia ya cargada no se puede actualizar con LoadFamily (mismo GUID =
    no-op). Por eso se guarda la familia editada a un .rfa temporal, se cierra,
    se ELIMINA la familia del proyecto y se recarga desde el temporal.
    """
    created = []
    errors = []
    tmp = os.path.join(tempfile.gettempdir(), "s2k_sections")
    try:
        if not os.path.isdir(tmp):
            os.makedirs(tmp)
    except Exception:
        pass

    out = None
    debug = {}
    try:
        fm = fam_doc.FamilyManager
        debug["family_path"] = normalize_string(getattr(fam_doc, "PathName", None))
        debug["types_before"] = fm.Types.Size
        for spec in type_specs:
            type_name = spec["type_name"]
            dims_m = spec.get("dims_m") or {}
            dims_ft = {k: float(v) * FT_PER_M for k, v in dims_m.items()}
            try:
                target_type = None
                for t in fm.Types:
                    if normalize_string(t.Name) == normalize_string(type_name):
                        target_type = t
                        break
                txn = DB.Transaction(fam_doc, u"Set dims " + type_name)
                txn.Start()
                try:
                    if target_type is None:
                        fm.NewType(type_name)
                    else:
                        fm.CurrentType = target_type
                    done, missing, available = _assign_dims(fm, dims_ft)
                    txn.Commit()
                except Exception:
                    try:
                        if txn.HasStarted() and not txn.HasEnded():
                            txn.RollBack()
                    except Exception:
                        pass
                    raise
                created.append({
                    "type": type_name,
                    "existing": target_type is not None,
                    "dims_m": dims_m,
                    "params_set": done,
                    "params_missing": missing,
                    "available_params": available,
                    "family": family_name,
                })
            except Exception as e:
                errors.append(u"{}: {}".format(type_name, str(e)))

        # Guardar la familia completa una sola vez (contiene todos los tipos nuevos)
        debug["types_after"] = fm.Types.Size
        if created:
            out = os.path.join(tmp, "s2k_" + _safe_name(family_name) + ".rfa")
            opts = DB.SaveAsOptions()
            opts.OverwriteExistingFile = True
            fam_doc.SaveAs(out, opts)
            debug["out_exists"] = os.path.exists(out)
            try:
                reopened = doc.Application.OpenDocument(out)
                debug["reopened_type_count"] = reopened.FamilyManager.Types.Size
                debug["reopened_has_new"] = [
                    c["type"] for c in created
                    if any(normalize_string(t.Name) == normalize_string(c["type"])
                           for t in reopened.FamilyManager.Types)]
                reopened.Close(False)
            except Exception as e:
                debug["reopen_err"] = str(e)

        # Cerrar la familia editada ANTES de recargarla en el proyecto.
        try:
            fam_doc.Close(False)
        except Exception:
            pass

        load_err = None
        if out:
            _fam, load_err = _load_family(doc, out)
            debug["load_err"] = load_err
            try:
                debug["loaded_family_name"] = get_element_name(_fam) \
                    if _fam is not None else None
            except Exception:
                pass
            for c in created:
                c["out_path"] = out
                c["out_exists"] = os.path.exists(out)
                c["load_err"] = load_err
                c["deleted_existing"] = False
                c["loaded_count"] = _count_project_types(doc, c["type"])
    except Exception as e:
        errors.append(u"family '{}': {}".format(family_name, str(e)))
    finally:
        try:
            fam_doc.Close(False)
        except Exception:
            pass
    return created, errors, tmp, debug


def _create_types_via_edit(doc, family, type_specs):
    """Crea tipos usando Document.EditFamily sobre una familia cargada."""
    if family is None or not type_specs:
        return [], [], None, {}
    family_name = get_element_name(family)
    try:
        fam_doc = doc.EditFamily(family)
    except Exception as e:
        return [], [u"EditFamily '{}': {}".format(family_name, str(e))], None, {}
    return _create_types_in_family_doc(
        doc, fam_doc, family_name, type_specs, family_obj=family)


def _create_types_from_file(doc, family_path, type_specs):
    """Crea tipos abriendo un archivo .rfa de una libreria de contenido."""
    if not family_path or not os.path.isfile(family_path):
        return [], [u"no family file: {}".format(family_path)], None, {}
    try:
        fam_doc = _open_family(doc.Application, family_path)
    except Exception as e:
        return [], [u"open {}: {}".format(family_path, str(e))], None, {}
    if fam_doc is None:
        return [], [u"no se pudo abrir: {}".format(family_path)], None, {}
    return _create_types_in_family_doc(
        doc, fam_doc, os.path.splitext(os.path.basename(family_path))[0],
        type_specs, family_obj=None)


# --------------------------------------------------------------------------- #
# Agrupacion y nombres
# --------------------------------------------------------------------------- #
def _split_sections(sections):
    hss_types, round_types = {}, {}
    for sec_name, sec in sections.items():
        shape = normalize_string(sec.get("shape", "")).lower()
        t3 = sec.get("t3")
        if shape == "circle" or (t3 and not sec.get("t2")):
            round_types[sec_name] = sec
        else:
            hss_types[sec_name] = sec
    return hss_types, round_types


def _type_name_from_section(section_name, dims):
    import re
    name = normalize_string(section_name)
    m = re.search(r"hss\s*(\d+)\s*x\s*(\d+)\s*(?:x\s*([\d.]+))?", name.lower())
    if m:
        t = m.group(3) or "0"
        return u"HSS{}x{}x{}".format(m.group(1), m.group(2), t)
    m = re.search(r"\b(o\s*\d+/\d+)\b", name.lower())
    if m:
        return m.group(1).upper()
    if dims and dims.get("diameter"):
        mm = int(round(dims["diameter"] * 1000.0))
        return u"O {}".format(mm)
    return u"SECTION_{}".format(abs(hash(name)) % 100000)


def _group_by_dims(sections):
    by_dims = {}
    order = []
    for sec_name, sec in sections.items():
        shape = normalize_string(sec.get("shape", "")).lower()
        t3 = sec.get("t3")
        t2 = sec.get("t2")
        tf = sec.get("tf")
        if shape == "circle" or (t3 and not t2):
            dims = {"diameter": t3}
        else:
            dims = {"depth": t3, "width": t2, "thickness": tf}
        key = tuple(sorted((k, round(float(v), 6)) for k, v in dims.items()))
        if key not in by_dims:
            by_dims[key] = {
                "type_name": _type_name_from_section(sec_name, dims),
                "dims_m": dict(dims),
                "members": [],
            }
            order.append(key)
        by_dims[key]["members"].append(sec_name)
    return [by_dims[k] for k in order]


def _find_symbol_by_type(doc, type_name, categories):
    for cat in categories:
        for sym in DB.FilteredElementCollector(doc)\
                    .OfCategory(cat)\
                    .WhereElementIsElementType()\
                    .ToElements():
            try:
                if normalize_string(get_element_name(sym)) == normalize_string(type_name):
                    return sym
            except Exception:
                continue
    return None


def _build_family_map(doc, sections):
    col_cat = DB.BuiltInCategory.OST_StructuralColumns
    fr_cat = DB.BuiltInCategory.OST_StructuralFraming
    hss_types, round_types = _split_sections(sections)

    type_name_by_section = {}
    for group in _group_by_dims(hss_types) + _group_by_dims(round_types):
        for member in group["members"]:
            type_name_by_section[member] = group["type_name"]

    family_map = {}
    for sec_name in sections:
        type_name = type_name_by_section.get(sec_name)
        if not type_name:
            continue
        fsym = _find_symbol_by_type(doc, type_name, [fr_cat])
        csym = _find_symbol_by_type(doc, type_name, [col_cat])
        entry = {}
        if fsym:
            entry["framing"] = {
                "family": get_element_name(fsym.Family),
                "type": get_element_name(fsym),
            }
        if csym:
            entry["column"] = {
                "family": get_element_name(csym.Family),
                "type": get_element_name(csym),
            }
        family_map[sec_name] = entry
    return family_map


# --------------------------------------------------------------------------- #
# Rutas
# --------------------------------------------------------------------------- #
def register_sections_routes(api):
    @api.route("/find_base_families/", methods=["POST"])
    def find_base_families(doc, request):
        """Busca familias base en la libreria de contenido y en el proyecto."""
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            data = _body(request)
            content_root = data.get("content_base") or DEFAULT_CONTENT_ROOT

            hss_files = []
            bar_files = []
            for dirpath, _dirnames, filenames in os.walk(content_root):
                for fn in filenames:
                    if not fn.lower().endswith(".rfa"):
                        continue
                    n = fn.lower()
                    if ("hss" in n and "rectang" in n) or "rectang" in n and "hollow" in n:
                        hss_files.append(os.path.join(dirpath, fn))
                    if ("round" in n and "bar" in n) or ("bar" in n and "redonda" in n):
                        bar_files.append(os.path.join(dirpath, fn))

            info = _find_project_families_info(doc)
            return routes.make_response(data={
                "status": "success",
                "content_root": content_root,
                "library_hss_candidates": hss_files,
                "library_bar_candidates": bar_files,
                "project_families": info,
            })
        except Exception as e:
            log_route_error("find_base_families", e)
            logger.error("find_base_families failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/find_project_families/", methods=["POST"])
    def find_project_families(doc, request):
        """Devuelve las familias base detectadas en el proyecto cargado."""
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            return routes.make_response(data={
                "status": "success",
                "project_families": _find_project_families_info(doc),
            })
        except Exception as e:
            log_route_error("find_project_families", e)
            logger.error("find_project_families failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/ensure_sections/", methods=["POST"])
    def ensure_sections(doc, request):
        """Crea los tipos de seccion del .s2k en el proyecto de Revit.

        Body esperado:
        {
          "sections": { "<nombre s2k>": {"shape":"Box/Tube","t3":0.1,"t2":0.05,"tf":0.0045}, ... },
          "use_project": true,          # usar familias cargadas en el proyecto (defecto)
          "hss_family": "ruta opcional al .rfa del tubo rectangular",
          "bar_family": "ruta opcional al .rfa de la barra redonda",
          "content_base": "ruta raiz opcional de la libreria de contenido"
        }
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            data = _body(request)
            sections = data.get("sections") or {}
            if not sections:
                return routes.make_response(
                    data={"error": "No sections in payload"}, status=400)

            use_project = bool(data.get("use_project", True))
            content_root = data.get("content_base") or DEFAULT_CONTENT_ROOT
            hss_path = data.get("hss_family") or ""
            bar_path = data.get("bar_family") or ""

            hss_types, round_types = _split_sections(sections)
            hss_specs = _group_by_dims(hss_types)
            round_specs = _group_by_dims(round_types)

            created = []
            errors = []
            tmp_dirs = []
            debug_info = {}

            project = _find_project_families(doc) if use_project else {}

            # --- Tubos HSS ---
            if hss_specs:
                if use_project and project.get("hss_framing"):
                    c, e, tmpd, dbg = _create_types_via_duplicate(
                        doc, project["hss_framing"], hss_specs)
                else:
                    if not hss_path:
                        hss_path = data.get("hss_family") or ""
                    c, e, tmpd, dbg = _create_types_from_file(doc, hss_path, hss_specs)
                created.extend(c)
                errors.extend(e)
                if tmpd:
                    tmp_dirs.append(tmpd)
                debug_info["hss"] = dbg

                # Columna: crear el tipo tambien en la familia de columna HSS
                col_specs = [s for s in hss_specs
                             if any("COLUMNA" in m.upper() for m in s["members"])]
                if col_specs and use_project and project.get("hss_column"):
                    cc, ce, tmpd2, dbg2 = _create_types_via_duplicate(
                        doc, project["hss_column"], col_specs)
                    created.extend(cc)
                    errors.extend(ce)
                    if tmpd2:
                        tmp_dirs.append(tmpd2)
                    debug_info["column"] = dbg2

            # --- Barra redonda (tensor) ---
            if round_specs:
                if use_project and project.get("bar_framing"):
                    c, e, tmpd, dbg = _create_types_via_duplicate(
                        doc, project["bar_framing"], round_specs)
                else:
                    if not bar_path:
                        bar_path = data.get("bar_family") or ""
                    c, e, tmpd, dbg = _create_types_from_file(doc, bar_path, round_specs)
                created.extend(c)
                errors.extend(e)
                if tmpd:
                    tmp_dirs.append(tmpd)
                debug_info["bar"] = dbg

            family_map = _build_family_map(doc, sections)
            unmatched = [n for n in sections if n not in family_map]

            return routes.make_response(data={
                "status": "success",
                "created_types": created,
                "error_count": len(errors),
                "errors": errors[:50],
                "family_map": family_map,
                "unmatched_sections": unmatched,
                "debug_tmp_dirs": tmp_dirs,
                "debug_gettempdir": tempfile.gettempdir(),
                "debug_family": debug_info,
            })
        except Exception as e:
            log_route_error("ensure_sections", e)
            logger.error("ensure_sections failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/save_doc/", methods=["POST"])
    def save_doc(doc, request):
        """Guarda el documento de proyecto actual (equivalente a Ctrl+S)."""
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            doc.Save()
            return routes.make_response(data={
                "status": "success",
                "path": normalize_string(doc.PathName),
            })
        except Exception as e:
            log_route_error("save_doc", e)
            logger.error("save_doc failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/query_types/", methods=["POST"])
    def query_types(doc, request):
        """Lee parametros de tipos estructurales (verificacion de dimensiones)."""
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503)
            data = _body(request)
            names = data.get("types") or []
            categories = data.get("categories") or ["framing", "column"]
            cat_map = {
                "framing": DB.BuiltInCategory.OST_StructuralFraming,
                "column": DB.BuiltInCategory.OST_StructuralColumns,
            }
            results = {}
            for cat_label in categories:
                bcat = cat_map.get(cat_label)
                if bcat is None:
                    continue
                for sym in DB.FilteredElementCollector(doc)\
                              .OfCategory(bcat)\
                              .WhereElementIsElementType()\
                              .ToElements():
                    nm = get_element_name(sym)
                    if names and not any(normalize_string(nm) == normalize_string(n)
                                         for n in names):
                        continue
                    params = {}
                    for p in sym.Parameters:
                        d = p.Definition
                        if d is None:
                            continue
                        try:
                            val = p.AsValueString() or u""
                        except Exception:
                            val = u""
                        params[d.Name] = val
                    results.setdefault(cat_label, {})[nm] = {
                        "family": get_element_name(sym.Family),
                        "params": params,
                    }
            return routes.make_response(data={"status": "success", "types": results})
        except Exception as e:
            log_route_error("query_types", e)
            logger.error("query_types failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    logger.info("Sections routes registered successfully")
