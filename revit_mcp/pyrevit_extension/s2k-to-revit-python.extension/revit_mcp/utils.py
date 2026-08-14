# -*- coding: UTF-8 -*-
"""Utilidades IronPython 2.7 para las rutas de pyRevit."""

from pyrevit import DB
import re
import logging
import os
import tempfile
import traceback

logger = logging.getLogger(__name__)

DIM_RE = re.compile(r"hss\s*(\d+)\s*x\s*(\d+)\s*(?:x\s*([\d.]+))?")


def log_route_error(tag, e):
    """Escribe el traceback completo de una excepcion a un archivo temporal."""
    try:
        path = os.path.join(tempfile.gettempdir(), "revit_route_errors.log")
        with open(path, "a") as fh:
            fh.write(u"\n===== {} =====\n".format(tag))
            fh.write(u"msg: {}\n".format(str(e)))
            fh.write(traceback.format_exc())
            fh.write(u"\n")
    except Exception:
        pass


def normalize_string(text):
    """Devuelve siempre texto unicode (evita errores de codec en JSON)."""
    if text is None:
        return u"Unnamed"
    if isinstance(text, unicode):
        return text.strip()
    if isinstance(text, str):
        try:
            return text.decode("utf-8").strip()
        except (UnicodeDecodeError, AttributeError):
            return text.decode("latin-1").strip()
    try:
        return unicode(text).strip()
    except Exception:
        return u"Unnamed"


def element_id_value(element_id):
    """Valor entero de un ElementId (Revit 2025+ usa .Value, antes .IntegerValue)."""
    try:
        return int(element_id.Value)
    except AttributeError:
        return int(element_id.IntegerValue)


def get_element_name(element):
    try:
        return element.Name
    except Exception:
        pass
    try:
        return DB.Element.Name.__get__(element)
    except Exception:
        pass
    return u"Unnamed"


def _norm(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def section_dims(section_name):
    """Extrae dimensiones HSS de un nombre de seccion SAP2000 -> (h, b, t) o None."""
    m = DIM_RE.search(normalize_string(section_name).lower())
    if not m:
        return None
    h = int(m.group(1))
    b = int(m.group(2))
    t = float(m.group(3)) if m.group(3) else None
    return (h, b, t)


def collect_symbols(doc, category):
    """Simbolos (types) cargados de una categoria estructural."""
    symbols = DB.FilteredElementCollector(doc)\
                .OfCategory(category)\
                .WhereElementIsElementType()\
                .ToElements()
    return [s for s in symbols if s.Category and element_id_value(s.Category.Id) == int(category)]


def resolve_symbol(doc, section_name, category, fallback_symbol=None):
    """Busca el mejor FamilySymbol cargado para una seccion SAP2000.

    1. Coincidencia exacta normalizada (family + type).
    2. Coincidencia por dimensiones HSS (ej. HSS100x50x4.5).
    3. Primer simbolo disponible de la categoria.
    """
    candidates = collect_symbols(doc, category)
    if not candidates:
        return None

    target = _norm(section_name)
    dims = section_dims(section_name)

    for sym in candidates:
        name = _norm(u"{0} {1}".format(
            get_element_name(sym.Family), get_element_name(sym)))
        if name == target:
            return sym

    if dims:
        best = None
        best_score = -1
        for sym in candidates:
            fam = _norm(get_element_name(sym.Family))
            typ = _norm(get_element_name(sym))
            hay = u"{0} {1}".format(fam, typ)
            if "hss" not in hay and "rectang" not in hay:
                continue
            score = 0
            for dim in dims:
                if dim is not None and str(dim).replace(".0", "") in hay:
                    score += 1
            if score > best_score:
                best = sym
                best_score = score
        if best is not None and best_score > 0:
            return best

    if fallback_symbol is not None:
        return fallback_symbol
    return candidates[0]


def get_levels(doc):
    levels = DB.FilteredElementCollector(doc)\
              .OfCategory(DB.BuiltInCategory.OST_Levels)\
              .WhereElementIsNotElementType()\
              .ToElements()
    return [lvl for lvl in levels]


def find_level(doc, level_name):
    for lvl in get_levels(doc):
        if normalize_string(lvl.Name) == normalize_string(level_name):
            return lvl
    return None


def lowest_level(doc):
    levels = get_levels(doc)
    if not levels:
        return None
    return min(levels, key=lambda lvl: lvl.Elevation)
