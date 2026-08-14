# -*- coding: UTF-8 -*-
"""Rutas de estado y consulta - versión limpia."""

from pyrevit import routes, revit, DB
import json
import logging
import os

from revit_mcp.utils import normalize_string, element_id_value, collect_symbols, get_element_name, log_route_error, lowest_level

logger = logging.getLogger(__name__)

FT_PER_M = 1.0 / 0.3048
FT_PER_MM = 1.0 / 304.8
MM_TO_FEET = 1.0 / 304.8


def register_status_routes(api):
    @api.route("/status/", methods=["GET"])
    def revit_status():
        try:
            doc = revit.doc
            if doc:
                return routes.make_response(data={
                    "status": "active",
                    "health": "healthy",
                    "revit_available": True,
                    "document_title": normalize_string(doc.Title),
                    "api_name": "revit_mcp",
                })
            return routes.make_response(data={
                "status": "unhealthy",
                "revit_available": False,
                "api_name": "revit_mcp",
            })
        except Exception as e:
            log_route_error("revit_status", e)
            logger.error("revit_status failed: %s", str(e))
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/list_sheets/", methods=["POST"])
    def list_sheets(doc, request):
        try:
            if not doc:
                return routes.make_response(data={"error": "No active Revit document"}, status=503)
            sheets = []
            for s in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet).ToElements():
                sheets.append({
                    "id": element_id_value(s.Id),
                    "number": normalize_string(s.SheetNumber),
                    "name": normalize_string(s.Name),
                })
            return routes.make_response(data={"status": "success", "sheets": sheets, "count": len(sheets)})
        except Exception as e:
            log_route_error("list_sheets", e)
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/sheet_texts/", methods=["POST"])
    def sheet_texts(doc, request):
        try:
            if not doc:
                return routes.make_response(data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            view_id = body.get("view_id")
            if not view_id:
                return routes.make_response(data={"error": "view_id required"}, status=400)
            view = doc.GetElement(DB.ElementId(long(view_id)))
            if not view or not isinstance(view, DB.View):
                return routes.make_response(data={"error": "invalid view_id"}, status=400)
            texts = []
            seen = set()
            for el in DB.FilteredElementCollector(doc, view.Id)\
                        .OfCategory(DB.BuiltInCategory.OST_TextNotes)\
                        .WhereElementIsNotElementType()\
                        .ToElements():
                try:
                    eidv = element_id_value(el.Id)
                    if eidv in seen:
                        continue
                    seen.add(eidv)
                    tn_type_id = u""
                    tn_type_name = u""
                    try:
                        tn_type_id = element_id_value(el.GetTypeId())
                    except Exception:
                        pass
                    try:
                        tn_type_el = doc.GetElement(el.GetTypeId())
                        if tn_type_el:
                            tn_type_name = normalize_string(tn_type_el.Name)
                    except Exception:
                        pass
                    texts.append({
                        "id": eidv,
                        "text": getattr(el, "Text", u""),
                        "type_id": tn_type_id,
                        "type_name": tn_type_name,
                        "x": None,
                        "y": None,
                    })
                    try:
                        coord = el.Coord
                        if coord:
                            texts[-1]["x"] = round(coord.X * 304.8, 2)
                            texts[-1]["y"] = round(coord.Y * 304.8, 2)
                    except Exception:
                        pass
                except Exception:
                    pass
            placed_views = set()
            try:
                for vp in DB.FilteredElementCollector(doc, view.Id)\
                            .OfCategory(DB.BuiltInCategory.OST_Viewports)\
                            .WhereElementIsNotElementType()\
                            .ToElements():
                    vid = getattr(vp, "ViewId", None)
                    if vid:
                        placed_views.add(element_id_value(vid))
            except Exception:
                pass
            try:
                for si in DB.FilteredElementCollector(doc, view.Id)\
                            .OfClass(DB.ScheduleSheetInstance)\
                            .ToElements():
                    vid = getattr(si, "ScheduleId", None)
                    if vid:
                        placed_views.add(element_id_value(vid))
            except Exception:
                pass
            for target_view_id in set([element_id_value(view.Id)] + list(placed_views)):
                try:
                    for el in DB.FilteredElementCollector(doc, long(target_view_id))\
                                .OfCategory(DB.BuiltInCategory.OST_TextNotes)\
                                .WhereElementIsNotElementType()\
                                .ToElements():
                        try:
                            eidv = element_id_value(el.Id)
                            if eidv in seen:
                                continue
                            seen.add(eidv)
                            owner = getattr(el, "OwnerViewId", None)
                            tn_type_id = u""
                            tn_type_name = u""
                            try:
                                tn_type_id = element_id_value(el.GetTypeId())
                            except Exception:
                                pass
                            try:
                                tn_type_el = doc.GetElement(el.GetTypeId())
                                if tn_type_el:
                                    tn_type_name = normalize_string(tn_type_el.Name)
                            except Exception:
                                pass
                            texts.append({
                                "id": eidv,
                                "text": getattr(el, "Text", u""),
                                "owner_view_id": element_id_value(owner) if owner else target_view_id,
                                "type_id": tn_type_id,
                                "type_name": tn_type_name,
                                "x": None,
                                "y": None,
                            })
                            try:
                                coord = el.Coord
                                if coord:
                                    texts[-1]["x"] = round(coord.X * 304.8, 2)
                                    texts[-1]["y"] = round(coord.Y * 304.8, 2)
                            except Exception:
                                pass
                        except Exception:
                            pass
                except Exception:
                    pass
            return routes.make_response(data={"status": "success", "texts": texts, "count": len(texts)})
        except Exception as e:
            log_route_error("sheet_texts", e)
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/update_sheet_text/", methods=["POST"])
    def update_sheet_text(doc, request):
        try:
            if not doc:
                return routes.make_response(data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            text_id = body.get("text_id")
            new_text = body.get("text")
            if not text_id or new_text is None:
                return routes.make_response(data={"error": "text_id and text required"}, status=400)
            el = doc.GetElement(DB.ElementId(long(text_id)))
            if not el or not isinstance(el, DB.TextNote):
                return routes.make_response(data={"error": "invalid text_id"}, status=400)
            t = DB.Transaction(doc, "Actualizar TextNote")
            t.Start()
            try:
                el.Text = new_text
                t.Commit()
            except Exception:
                if t.HasStarted() and not t.HasEnded():
                    t.RollBack()
                raise
            return routes.make_response(data={"status": "success", "id": element_id_value(el.Id)})
        except Exception as e:
            log_route_error("update_sheet_text", e)
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/save_doc/", methods=["POST"])
    def save_doc(doc, request):
        try:
            if not doc:
                return routes.make_response(data={"error": "No active Revit document"}, status=503)
            t = DB.Transaction(doc, "Guardar documento")
            t.Start()
            try:
                doc.Save()
                t.Commit()
                return routes.make_response(data={"status": "success", "path": normalize_string(doc.PathName)})
            except Exception:
                if t.HasStarted() and not t.HasEnded():
                    t.RollBack()
                raise
        except Exception as e:
            log_route_error("save_doc", e)
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/list_text_note_types/", methods=["POST"])
    def list_text_note_types(doc, request):
        try:
            if not doc:
                return routes.make_response(data={"error": "No active Revit document"}, status=503)
            types = []
            seen = set()
            colls = []
            try:
                colls.append(DB.FilteredElementCollector(doc).OfClass(DB.TextNoteType).ToElements())
            except Exception:
                pass
            try:
                colls.append(DB.FilteredElementCollector(doc)
                             .OfCategory(DB.BuiltInCategory.OST_TextNotes)
                             .WhereElementIsElementType()
                             .ToElements())
            except Exception:
                pass
            for tnt in colls:
                try:
                    eidv = element_id_value(tnt.Id)
                    if eidv in seen:
                        continue
                    seen.add(eidv)
                    font = u""
                    size_ft = 0.0
                    bold = False
                    italic = False
                    try:
                        p = tnt.get_Parameter(DB.BuiltInParameter.TEXT_FONT)
                        if p:
                            font = normalize_string(p.AsString() or u"")
                    except Exception:
                        pass
                    try:
                        p = tnt.get_Parameter(DB.BuiltInParameter.TEXT_SIZE)
                        if p:
                            size_ft = p.AsDouble()
                    except Exception:
                        pass
                    try:
                        p = tnt.get_Parameter(DB.BuiltInParameter.TEXT_BOLD)
                        if p:
                            bold = bool(p.AsInteger())
                    except Exception:
                        pass
                    try:
                        p = tnt.get_Parameter(DB.BuiltInParameter.TEXT_ITALIC)
                        if p:
                            italic = bool(p.AsInteger())
                    except Exception:
                        pass
                    types.append({
                        "id": element_id_value(tnt.Id),
                        "name": normalize_string(tnt.Name),
                        "font": font,
                        "size_mm": round(size_ft * 304.8, 2),
                        "bold": bold,
                        "italic": italic,
                    })
                except Exception:
                    pass
            return routes.make_response(data={"status": "success", "types": types, "count": len(types)})
        except Exception as e:
            log_route_error("list_text_note_types", e)
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/update_text_note_type/", methods=["POST"])
    def update_text_note_type(doc, request):
        try:
            if not doc:
                return routes.make_response(data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            type_id = body.get("type_id")
            if not type_id:
                return routes.make_response(data={"error": "type_id required"}, status=400)
            tnt = doc.GetElement(DB.ElementId(long(type_id)))
            if not tnt or not isinstance(tnt, DB.TextNoteType):
                return routes.make_response(data={"error": "invalid type_id"}, status=400)
            font = body.get("font_name")
            size_mm = body.get("font_size_mm")
            bold = body.get("bold")
            italic = body.get("italic")
            t = DB.Transaction(doc, "Actualizar tipo de texto")
            t.Start()
            try:
                if font:
                    p = tnt.get_Parameter(DB.BuiltInParameter.TEXT_FONT)
                    if p:
                        p.Set(font)
                if size_mm is not None:
                    p = tnt.get_Parameter(DB.BuiltInParameter.TEXT_SIZE)
                    if p:
                        p.Set(float(size_mm) * FT_PER_MM)
                if bold is not None:
                    p = tnt.get_Parameter(DB.BuiltInParameter.TEXT_BOLD)
                    if p:
                        p.Set(1 if bold else 0)
                if italic is not None:
                    p = tnt.get_Parameter(DB.BuiltInParameter.TEXT_ITALIC)
                    if p:
                        p.Set(1 if italic else 0)
                t.Commit()
                return routes.make_response(data={"status": "success", "id": element_id_value(tnt.Id)})
            except Exception:
                if t.HasStarted() and not t.HasEnded():
                    t.RollBack()
                raise
        except Exception as e:
            log_route_error("update_text_note_type", e)
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/set_text_note_type/", methods=["POST"])
    def set_text_note_type(doc, request):
        """Asigna un TextNoteType (fuente/tamano) a una TextNote existente."""
        try:
            if not doc:
                return routes.make_response(data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            text_id = body.get("text_id")
            type_id = body.get("type_id")
            if not text_id or not type_id:
                return routes.make_response(data={"error": "text_id and type_id required"}, status=400)
            el = doc.GetElement(DB.ElementId(long(text_id)))
            if not el or not isinstance(el, DB.TextNote):
                return routes.make_response(data={"error": "invalid text_id"}, status=400)
            tnt = doc.GetElement(DB.ElementId(long(type_id)))
            if not tnt or not isinstance(tnt, DB.TextNoteType):
                return routes.make_response(data={"error": "invalid type_id"}, status=400)
            t = DB.Transaction(doc, "Aplicar tipo de texto")
            t.Start()
            try:
                el.ChangeType(tnt)
                t.Commit()
                return routes.make_response(data={"status": "success", "id": element_id_value(el.Id)})
            except Exception:
                if t.HasStarted() and not t.HasEnded():
                    t.RollBack()
                raise
        except Exception as e:
            log_route_error("set_text_note_type", e)
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/debug_text_type/", methods=["POST"])
    def debug_text_type(doc, request):
        """Resuelve un TextNoteType por id y devuelve nombre + parametros."""
        try:
            if not doc:
                return routes.make_response(data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            type_id = body.get("type_id")
            if not type_id:
                return routes.make_response(data={"error": "type_id required"}, status=400)
            el = doc.GetElement(DB.ElementId(long(type_id)))
            if not el:
                return routes.make_response(data={"error": "element not found"}, status=404)
            out = {
                "id": element_id_value(el.Id),
                "class": el.GetType().Name if hasattr(el, "GetType") else type(el).__name__,
            }
            try:
                out["name"] = normalize_string(el.Name)
            except Exception:
                out["name"] = u""
            for bip, key in [
                (DB.BuiltInParameter.TEXT_FONT, "font"),
                (DB.BuiltInParameter.TEXT_SIZE, "size_mm"),
            ]:
                try:
                    p = el.get_Parameter(bip)
                    if p:
                        if bip == DB.BuiltInParameter.TEXT_SIZE:
                            out[key] = round(p.AsDouble() * 304.8, 2)
                        else:
                            out[key] = normalize_string(p.AsString() or u"")
                except Exception:
                    pass
            return routes.make_response(data={"status": "success", "type": out})
        except Exception as e:
            log_route_error("debug_text_type", e)
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/create_text_note_type/", methods=["POST"])
    def create_text_note_type(doc, request):
        """Crea un TextNoteType nuevo duplicando uno existente."""
        try:
            if not doc:
                return routes.make_response(data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            base_id = body.get("base_type_id")
            name = body.get("name")
            if not base_id or not name:
                return routes.make_response(data={"error": "base_type_id and name required"}, status=400)
            base = doc.GetElement(DB.ElementId(long(base_id)))
            if not base or not isinstance(base, DB.TextNoteType):
                return routes.make_response(data={"error": "invalid base_type_id"}, status=400)
            new_type = None
            t = DB.Transaction(doc, "Crear tipo de texto")
            t.Start()
            try:
                new_type = base.Duplicate(name)
                t.Commit()
            except Exception:
                if t.HasStarted() and not t.HasEnded():
                    t.RollBack()
                raise
            if not new_type:
                return routes.make_response(data={"error": "duplicate failed"}, status=500)
            font = body.get("font_name")
            size_mm = body.get("font_size_mm")
            bold = body.get("bold")
            italic = body.get("italic")
            if font or size_mm is not None or bold is not None or italic is not None:
                t = DB.Transaction(doc, "Configurar tipo de texto")
                t.Start()
                try:
                    if font:
                        p = new_type.get_Parameter(DB.BuiltInParameter.TEXT_FONT)
                        if p:
                            p.Set(font)
                    if size_mm is not None:
                        p = new_type.get_Parameter(DB.BuiltInParameter.TEXT_SIZE)
                        if p:
                            p.Set(float(size_mm) * FT_PER_MM)
                    if bold is not None:
                        p = new_type.get_Parameter(DB.BuiltInParameter.TEXT_BOLD)
                        if p:
                            p.Set(1 if bold else 0)
                    if italic is not None:
                        p = new_type.get_Parameter(DB.BuiltInParameter.TEXT_ITALIC)
                        if p:
                            p.Set(1 if italic else 0)
                    t.Commit()
                except Exception:
                    if t.HasStarted() and not t.HasEnded():
                        t.RollBack()
                    raise
            return routes.make_response(data={"status": "success", "id": element_id_value(new_type.Id)})
        except Exception as e:
            log_route_error("create_text_note_type", e)
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/move_text_note/", methods=["POST"])
    def move_text_note(doc, request):
        """Reubica una TextNote (x_mm, y_mm relativos al centro de la vista)."""
        try:
            if not doc:
                return routes.make_response(data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            text_id = body.get("text_id")
            x_mm = body.get("x_mm")
            y_mm = body.get("y_mm")
            if not text_id or x_mm is None or y_mm is None:
                return routes.make_response(data={"error": "text_id, x_mm, y_mm required"}, status=400)
            x_mm = float(x_mm)
            y_mm = float(y_mm)
            el = doc.GetElement(DB.ElementId(long(text_id)))
            if not el or not isinstance(el, DB.TextNote):
                return routes.make_response(data={"error": "invalid text_id"}, status=400)
            t = DB.Transaction(doc, "Mover TextNote")
            t.Start()
            try:
                el.Coord = DB.XYZ(x_mm * FT_PER_MM, y_mm * FT_PER_MM, 0.0)
                t.Commit()
                return routes.make_response(data={"status": "success", "id": element_id_value(el.Id)})
            except Exception:
                if t.HasStarted() and not t.HasEnded():
                    t.RollBack()
                raise
        except Exception as e:
            log_route_error("move_text_note", e)
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/sheet_viewports/", methods=["POST"])
    def sheet_viewports(doc, request):
        """Lista los viewports colocados en una hoja con su posicion."""
        try:
            if not doc:
                return routes.make_response(data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            view_id = body.get("view_id")
            if not view_id:
                return routes.make_response(data={"error": "view_id required"}, status=400)
            view = doc.GetElement(DB.ElementId(long(view_id)))
            if not view or not isinstance(view, DB.ViewSheet):
                return routes.make_response(data={"error": "invalid sheet view_id"}, status=400)
            out = []
            for vp in DB.FilteredElementCollector(doc, view.Id)\
                        .OfCategory(DB.BuiltInCategory.OST_Viewports)\
                        .WhereElementIsNotElementType()\
                        .ToElements():
                item = {"id": element_id_value(vp.Id)}
                try:
                    vid = getattr(vp, "ViewId", None)
                    item["view_id"] = element_id_value(vid) if vid else None
                except Exception:
                    pass
                try:
                    b = getattr(vp, "GetBoxCenter", None)
                    if b:
                        c = b()
                        item["x_mm"] = round(c.X * 304.8, 2)
                        item["y_mm"] = round(c.Y * 304.8, 2)
                except Exception:
                    pass
                try:
                    item["label"] = normalize_string(vp.Label)
                except Exception:
                    pass
                try:
                    c = vp.GetBoxCenter()
                    item["x_mm"] = round(c.X * 304.8, 2)
                    item["y_mm"] = round(c.Y * 304.8, 2)
                except Exception:
                    pass
                try:
                    b = vp.GetBoxOutline()
                    if b:
                        mn = b.MinimumPoint
                        mx = b.MaximumPoint
                        item["w_mm"] = round((mx.X - mn.X) * 304.8, 2)
                        item["h_mm"] = round((mx.Y - mn.Y) * 304.8, 2)
                except Exception as e:
                    item["box_err"] = str(e)
                try:
                    v = doc.GetElement(vp.ViewId)
                    if v:
                        item["view_name"] = normalize_string(v.Name)
                except Exception:
                    pass
                out.append(item)
            return routes.make_response(data={"status": "success", "viewports": out, "count": len(out)})
        except Exception as e:
            log_route_error("sheet_viewports", e)
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/create_text_note/", methods=["POST"])
    def create_text_note(doc, request):
        """Crea una TextNote anotativa en una vista/hoja.

        body: {view_id, x_mm, y_mm, text, type_id?, align?}
        """
        try:
            if not doc:
                return routes.make_response(data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            view_id = body.get("view_id")
            if not view_id:
                return routes.make_response(data={"error": "view_id required"}, status=400)
            view = doc.GetElement(DB.ElementId(long(view_id)))
            if not view or not isinstance(view, DB.View):
                return routes.make_response(data={"error": "invalid view_id"}, status=400)
            text = body.get("text")
            if text is None:
                return routes.make_response(data={"error": "text required"}, status=400)
            try:
                x_mm = float(body.get("x_mm", 0.0))
            except Exception:
                x_mm = 0.0
            try:
                y_mm = float(body.get("y_mm", 0.0))
            except Exception:
                y_mm = 0.0
            text_type = None
            type_id = body.get("type_id")
            if type_id:
                try:
                    text_type = doc.GetElement(DB.ElementId(long(type_id)))
                except Exception:
                    text_type = None
            if not text_type:
                for sym in DB.FilteredElementCollector(doc)\
                            .OfClass(DB.TextNoteType)\
                            .ToElements():
                    text_type = sym
                    break
            options = DB.TextNoteOptions()
            try:
                options.Rotation = 0.0
            except Exception:
                pass
            t = DB.Transaction(doc, "Crear TextNote")
            t.Start()
            try:
                tn = DB.TextNote.Create(
                    doc, view.Id, DB.XYZ(x_mm * FT_PER_MM, y_mm * FT_PER_MM, 0.0),
                    text, text_type)
                t.Commit()
                return routes.make_response(data={
                    "status": "success",
                    "id": element_id_value(tn.Id),
                })
            except Exception:
                if t.HasStarted() and not t.HasEnded():
                    t.RollBack()
                raise
        except Exception as e:
            log_route_error("create_text_note", e)
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/debug_formatted_text/", methods=["POST"])
    def debug_formatted_text(doc, request):
        """Inspecciona el formato global de una TextNote:
        bold/italic/underline/subscript/superscript/caps."""
        try:
            if not doc:
                return routes.make_response(data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            text_id = body.get("text_id")
            if not text_id:
                return routes.make_response(data={"error": "text_id required"}, status=400)
            el = doc.GetElement(DB.ElementId(long(text_id)))
            if not el or not isinstance(el, DB.TextNote):
                return routes.make_response(data={"error": "invalid text_id"}, status=400)
            out = {"id": element_id_value(el.Id), "text": normalize_string(el.Text)}
            try:
                ft = el.GetFormattedText()
                for name, getter in [
                    ("bold", "GetBoldStatus"),
                    ("italic", "GetItalicStatus"),
                    ("underline", "GetUnderlineStatus"),
                    ("all_caps", "GetAllCapsStatus"),
                ]:
                    try:
                        v = getattr(ft, getter)()
                        out[name] = str(v).split(".")[-1]
                    except Exception:
                        pass
            except Exception as e:
                return routes.make_response(data={"error": "formatted text error: %s" % str(e)}, status=500)
            return routes.make_response(data={"status": "success", "text": out.pop("text"), "format": out})
        except Exception as e:
            log_route_error("debug_formatted_text", e)
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/debug_text_enums/", methods=["POST"])
    def debug_text_enums(doc, request):
        """Lista los enums de estilo de texto disponibles en el API."""
        try:
            out = {}
            for enum_name in ["TextUnderlineStatus", "TextStyleStatus", "TextCapsStatus", "TextSubscriptStatus", "TextSuperscriptStatus"]:
                try:
                    enum = getattr(DB, enum_name)
                    out[enum_name] = [m for m in dir(enum) if not m.startswith('_')]
                except Exception as e:
                    out[enum_name] = "ERR: %s" % str(e)
            try:
                import System
                out["system_enums"] = [
                    "System.TextStyleStatus",
                ]
                import clr
                clr.AddReference("RevitAPI")
                from Autodesk.Revit.DB import TextStyleStatus, TextUnderlineStatus
                out["TextStyleStatus_imported"] = [m for m in dir(TextStyleStatus) if not m.startswith('_')]
                out["TextUnderlineStatus_imported"] = [m for m in dir(TextUnderlineStatus) if not m.startswith('_')]
            except Exception as e:
                out["import_err"] = str(e)
            return routes.make_response(data={"status": "success", "enums": out})
        except Exception as e:
            log_route_error("debug_text_enums", e)
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/probe_set_text_format/", methods=["POST"])
    def probe_set_text_format(doc, request):
        """Prueba aplicar formatos con distintos metodos de FormattedText
        para descubrir la API correcta de Revit 2027."""
        try:
            if not doc:
                return routes.make_response(data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            text_id = body.get("text_id")
            if not text_id:
                return routes.make_response(data={"error": "text_id required"}, status=400)
            el = doc.GetElement(DB.ElementId(long(text_id)))
            if not el or not isinstance(el, DB.TextNote):
                return routes.make_response(data={"error": "invalid text_id"}, status=400)
            results = {}
            ft = el.GetFormattedText()
            # intento 1: SetBoldStatus con entero
            try:
                ft.SetBoldStatus(0)
                results["bold_int"] = "ok"
            except Exception as e:
                results["bold_int"] = "ERR: %s" % str(e)
            try:
                ft.SetBoldStatus(1)
                results["bold_int1"] = "ok"
            except Exception as e:
                results["bold_int1"] = "ERR: %s" % str(e)
            # intento 2: AsTextRange() -> probar metodos con find
            try:
                tr = ft.AsTextRange()
                results["tr_methods"] = [m for m in dir(tr) if not m.startswith('_')]
            except Exception as e:
                results["tr"] = "ERR: %s" % str(e)
            # intento 3: getters
            for name, meth in [("underline", "GetUnderlineStatus"), ("bold", "GetBoldStatus")]:
                try:
                    v = getattr(ft, meth)()
                    results[name] = repr(v) + " type=%s" % type(v).__name__
                except Exception as e:
                    results[name] = "ERR: %s" % str(e)
            return routes.make_response(data={"status": "success", "results": results})
        except Exception as e:
            log_route_error("probe_set_text_format", e)
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/set_formatted_text/", methods=["POST"])
    def set_formatted_text(doc, request):
        """Aplica formato uniforme a una TextNote: quita underline, negrita,
        cursiva y mayusculas. body: {text_id, remove_underline?, remove_bold?,
        remove_italic?, remove_caps?}"""
        try:
            if not doc:
                return routes.make_response(data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            text_id = body.get("text_id")
            if not text_id:
                return routes.make_response(data={"error": "text_id required"}, status=400)
            el = doc.GetElement(DB.ElementId(long(text_id)))
            if not el or not isinstance(el, DB.TextNote):
                return routes.make_response(data={"error": "invalid text_id"}, status=400)
            t = DB.Transaction(doc, "Formato de texto uniforme")
            t.Start()
            errors = []
            try:
                ft = el.GetFormattedText()
                if body.get("remove_underline", True):
                    try:
                        ft.SetUnderlineStatus(getattr(DB.FormatStatus, "None"))
                    except Exception as e:
                        errors.append("underline: %s" % str(e))
                if body.get("remove_bold", True):
                    try:
                        ft.SetBoldStatus(getattr(DB.FormatStatus, "None"))
                    except Exception as e:
                        errors.append("bold: %s" % str(e))
                if body.get("remove_italic", True):
                    try:
                        ft.SetItalicStatus(getattr(DB.FormatStatus, "None"))
                    except Exception as e:
                        errors.append("italic: %s" % str(e))
                if body.get("remove_caps", True):
                    try:
                        ft.SetAllCapsStatus(getattr(DB.FormatStatus, "None"))
                    except Exception as e:
                        errors.append("caps: %s" % str(e))
                el.SetFormattedText(ft)
                t.Commit()
                return routes.make_response(data={"status": "success", "id": element_id_value(el.Id), "errors": errors})
            except Exception:
                if t.HasStarted() and not t.HasEnded():
                    t.RollBack()
                raise
        except Exception as e:
            log_route_error("set_formatted_text", e)
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/sheet_outline/", methods=["POST"])
    def sheet_outline(doc, request):
        """Devuelve las dimensiones (Outline) de una hoja en mm."""
        try:
            if not doc:
                return routes.make_response(data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            view_id = body.get("view_id")
            if not view_id:
                return routes.make_response(data={"error": "view_id required"}, status=400)
            view = doc.GetElement(DB.ElementId(long(view_id)))
            if not view or not isinstance(view, DB.ViewSheet):
                return routes.make_response(data={"error": "invalid sheet view_id"}, status=400)
            out = {"id": element_id_value(view.Id), "number": normalize_string(view.SheetNumber), "name": normalize_string(view.Name)}
            err = u""
            try:
                bb = view.Outline
                if bb:
                    out["width_mm"] = round((bb.Max.U - bb.Min.U) * 304.8, 2)
                    out["height_mm"] = round((bb.Max.V - bb.Min.V) * 304.8, 2)
                    out["min_u"] = round(bb.Min.U * 304.8, 2)
                    out["min_v"] = round(bb.Min.V * 304.8, 2)
                    out["max_u"] = round(bb.Max.U * 304.8, 2)
                    out["max_v"] = round(bb.Max.V * 304.8, 2)
            except Exception as e:
                err = str(e)
            if not out.get("width_mm"):
                out["outline_err"] = err
            return routes.make_response(data={"status": "success", "sheet": out})
        except Exception as e:
            log_route_error("sheet_outline", e)
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/move_viewport/", methods=["POST"])
    def move_viewport(doc, request):
        """Mueve un viewport a una posicion (x_mm, y_mm del centro)."""
        try:
            if not doc:
                return routes.make_response(data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            vp_id = body.get("viewport_id")
            x_mm = body.get("x_mm")
            y_mm = body.get("y_mm")
            if not vp_id or x_mm is None or y_mm is None:
                return routes.make_response(data={"error": "viewport_id, x_mm, y_mm required"}, status=400)
            x_mm = float(x_mm)
            y_mm = float(y_mm)
            vp = doc.GetElement(DB.ElementId(long(vp_id)))
            if not vp or not isinstance(vp, DB.Viewport):
                return routes.make_response(data={"error": "invalid viewport_id"}, status=400)
            t = DB.Transaction(doc, "Mover viewport")
            t.Start()
            try:
                vp.SetBoxCenter(DB.XYZ(x_mm * FT_PER_MM, y_mm * FT_PER_MM, 0.0))
                t.Commit()
                return routes.make_response(data={"status": "success", "id": element_id_value(vp.Id)})
            except Exception:
                if t.HasStarted() and not t.HasEnded():
                    t.RollBack()
                raise
        except Exception as e:
            log_route_error("move_viewport", e)
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/debug_element/", methods=["POST"])
    def debug_element(doc, request):
        """Inspecciona un elemento por id: tipo, validez, owner view, category."""
        try:
            if not doc:
                return routes.make_response(data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            eid = body.get("element_id")
            if not eid:
                return routes.make_response(data={"error": "element_id required"}, status=400)
            el = doc.GetElement(DB.ElementId(long(eid)))
            if not el:
                return routes.make_response(data={"error": "element not found"}, status=404)
            info = {
                "id": element_id_value(el.Id),
                "is_valid": bool(el.IsValidObject),
                "class": el.GetType().FullName,
                "category": normalize_string(getattr(el, "Category", None) and getattr(el.Category, "Name", "")) or None,
            }
            try:
                info["owner_view"] = element_id_value(el.OwnerViewId) if el.OwnerViewId and el.OwnerViewId != DB.ElementId.InvalidElementId else None
            except Exception:
                pass
            try:
                info["name"] = normalize_string(getattr(el, "Name", None) or "") or None
            except Exception:
                pass
            try:
                if isinstance(el, DB.Viewport):
                    info["view_id"] = element_id_value(el.ViewId)
            except Exception:
                pass
            return routes.make_response(data={"status": "success", "element": info})
        except Exception as e:
            log_route_error("debug_element", e)
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/find_by_ifcguid/", methods=["POST"])
    def find_by_ifcguid(doc, request):
        """Busca un elemento por su parametro IfcGUID y devuelve su id y geometria."""
        try:
            if not doc:
                return routes.make_response(data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            guid = (body.get("ifcguid") or "").strip()
            if not guid:
                return routes.make_response(data={"error": "ifcguid required"}, status=400)
            cat = DB.BuiltInCategory.OST_StructuralFraming
            matches = []
            for el in DB.FilteredElementCollector(doc)\
                        .OfCategory(cat).WhereElementIsNotElementType().ToElements():
                try:
                    p = el.get_Parameter(DB.BuiltInParameter.IFC_GUID)
                    if not p:
                        p = el.get_Parameter("IfcGUID")
                    if p:
                        val = p.AsString() or p.AsValueString() or ""
                        if val and val.lower() == guid.lower():
                            eid = element_id_value(el.Id)
                            rec = {"id": eid, "guid": val, "type": normalize_string(get_element_name(el.Symbol))}
                            lc = el.Location
                            c = lc.Curve if hasattr(lc, "Curve") else None
                            if c:
                                p0 = c.GetEndPoint(0)
                                p1 = c.GetEndPoint(1)
                                rec["p1_m"] = [round(p0.X / FT_PER_M, 4), round(p0.Y / FT_PER_M, 4), round(p0.Z / FT_PER_M, 4)]
                                rec["p2_m"] = [round(p1.X / FT_PER_M, 4), round(p1.Y / FT_PER_M, 4), round(p1.Z / FT_PER_M, 4)]
                                rec["len_m"] = round(c.Length / FT_PER_M, 4)
                            matches.append(rec)
                except Exception:
                    continue
            return routes.make_response(data={"status": "success", "matches": matches, "count": len(matches)})
        except Exception as e:
            log_route_error("find_by_ifcguid", e)
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/delete_viewport/", methods=["POST"])
    def delete_viewport(doc, request):
        """Elimina un viewport de una hoja."""
        try:
            if not doc:
                return routes.make_response(data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            vp_id = body.get("viewport_id")
            if not vp_id:
                return routes.make_response(data={"error": "viewport_id required"}, status=400)
            vp = doc.GetElement(DB.ElementId(long(vp_id)))
            if not vp or not isinstance(vp, DB.Viewport):
                return routes.make_response(data={"error": "invalid viewport_id"}, status=400)
            t = DB.Transaction(doc, "Eliminar viewport")
            t.Start()
            try:
                doc.Delete(vp.Id)
                t.Commit()
                return routes.make_response(data={"status": "success", "id": element_id_value(vp.Id)})
            except Exception:
                if t.HasStarted() and not t.HasEnded():
                    t.RollBack()
                raise
        except Exception as e:
            log_route_error("delete_viewport", e)
            return routes.make_response(data={"error": str(e)}, status=500)

    @api.route("/place_viewport/", methods=["POST"])
    def place_viewport(doc, request):
        """Coloca una vista (drafting) en una hoja como viewport en x_mm,y_mm."""
        try:
            if not doc:
                return routes.make_response(data={"error": "No active Revit document"}, status=503)
            body = {}
            if request and request.data:
                try:
                    body = json.loads(request.data) if isinstance(request.data, str) else request.data
                except Exception:
                    body = {}
            sheet_id = body.get("sheet_id")
            view_id = body.get("view_id")
            x_mm = body.get("x_mm")
            y_mm = body.get("y_mm")
            if not sheet_id or not view_id or x_mm is None or y_mm is None:
                return routes.make_response(data={"error": "sheet_id, view_id, x_mm, y_mm required"}, status=400)
            sheet = doc.GetElement(DB.ElementId(long(sheet_id)))
            if not sheet or not isinstance(sheet, DB.ViewSheet):
                return routes.make_response(data={"error": "invalid sheet_id"}, status=400)
            view = doc.GetElement(DB.ElementId(long(view_id)))
            if not view or not isinstance(view, DB.View):
                return routes.make_response(data={"error": "invalid view_id"}, status=400)
            x_mm = float(x_mm)
            y_mm = float(y_mm)
            t = DB.Transaction(doc, "Colocar viewport")
            t.Start()
            try:
                vp = DB.Viewport.Create(doc, sheet.Id, view.Id, DB.XYZ(x_mm * FT_PER_MM, y_mm * FT_PER_MM, 0.0))
                t.Commit()
                return routes.make_response(data={"status": "success", "id": element_id_value(vp.Id)})
            except Exception:
                if t.HasStarted() and not t.HasEnded():
                    t.RollBack()
                raise
        except Exception as e:
            log_route_error("place_viewport", e)
            return routes.make_response(data={"error": str(e)}, status=500)

    logger.info("Status routes registered successfully")


# Register all routes
from pyrevit import routes
api = routes.API("revit_mcp")
register_status_routes(api)