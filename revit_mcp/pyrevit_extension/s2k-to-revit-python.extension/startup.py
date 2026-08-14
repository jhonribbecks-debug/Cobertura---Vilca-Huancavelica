# -*- coding: UTF-8 -*-
# BUILD-VERSION: 2
"""
S2K to Revit - pyRevit Extension Startup
Registra las rutas MCP (Routes API) al cargar la extension y
abre automaticamente el modelo objetivo cuando Revit arranca.
"""

import os
import sys
import time
import json
import threading
import traceback

_DEBUG_LOG = os.path.join(os.environ.get("TEMP", r"C:\Users\aintc\AppData\Local\Temp"),
                          "opencode", "startup_debug.log")

def _dbg(msg):
    try:
        with open(_DEBUG_LOG, "a") as f:
            f.write(str(msg) + "\n")
    except Exception:
        pass

_dbg("=== startup.py begin ===")

from pyrevit import routes
import logging
import importlib

logger = logging.getLogger(__name__)

api = routes.API("revit_mcp")
_dbg("api created")


# ---------------------------------------------------------------------------
# AUTO-OPEN: abre automaticamente el modelo objetivo al arrancar Revit.
# Se ejecuta en un hilo interno de la extension (dentro de Revit), de modo
# que no hace falta abrir el archivo manualmente tras cada reinicio.
# La ruta es configurable por variable de entorno TENORIOUS_PROJECT.
# ---------------------------------------------------------------------------
AUTO_OPEN_PATH = os.environ.get(
    "TENORIOUS_PROJECT",
    r"C:\Users\aintc\OneDrive\Escritorio\Tenorious\COBERTURA HUANCALPI.rvt")
AUTO_OPEN_BRIDGE = "http://127.0.0.1:48884/revit_mcp"
_auto_started = [False]

def _http_get(route, timeout=20):
    try:
        import urllib2
        req = urllib2.Request(AUTO_OPEN_BRIDGE + route)
        return json.loads(urllib2.urlopen(req, timeout=timeout).read().decode("utf-8"))
    except Exception:
        raise

def _http_post(route, payload, timeout=120):
    try:
        import urllib2
        body = json.dumps(payload).encode("utf-8")
        req = urllib2.Request(AUTO_OPEN_BRIDGE + route, data=body,
                              headers={"Content-Type": "application/json"})
        return json.loads(urllib2.urlopen(req, timeout=timeout).read().decode("utf-8"))
    except Exception:
        raise

def _auto_open_worker():
    if _auto_started[0]:
        return
    _auto_started[0] = True
    expected = os.path.basename(AUTO_OPEN_PATH).lower()
    _dbg("auto-open worker started")
    time.sleep(8)
    for _ in range(60):
        try:
            st = _http_get("/status/", timeout=10)
            if st.get("status") == "active":
                cur = (st.get("document_title") or "").lower()
                if cur and cur == expected:
                    _dbg("auto-open: target already open (%s)" % cur)
                    return
                _dbg("auto-open: opening %s (current=%s)" % (AUTO_OPEN_PATH, cur))
                res = _http_post("/open_document/", {"path": AUTO_OPEN_PATH}, timeout=150)
                _dbg("auto-open result: %s" % json.dumps(res))
                if res.get("status") == "success":
                    for _ in range(40):
                        time.sleep(2)
                        try:
                            st2 = _http_get("/status/", timeout=10)
                            if (st2.get("document_title") or "").lower() == expected:
                                _dbg("auto-open: document ready")
                                return
                        except Exception:
                            pass
                return
        except Exception as e:
            _dbg("auto-open waiting... %s" % str(e))
        time.sleep(5)
    _dbg("auto-open: timeout waiting for bridge")


def _reload_module(mod_name):
    """Fuerza recarga de un modulo propio (evita cache de Python en reloads)."""
    try:
        if mod_name in sys.modules:
            importlib.reload(sys.modules[mod_name])
        else:
            importlib.import_module(mod_name)
    except Exception as e:
        _dbg("reload %s FAILED: %s" % (mod_name, str(e)))
        logger.warning("No se pudo recargar %s: %s", mod_name, str(e))


def register_routes():
    """Registra todos los modulos de rutas MCP, forzando recarga de codigo."""
    try:
        _dbg("importing routes_status")
        _reload_module("revit_mcp.routes_status")
        from revit_mcp.routes_status import register_status_routes
        register_status_routes(api)
        _dbg("routes_status ok")

        _dbg("importing routes_s2k")
        _reload_module("revit_mcp.routes_s2k")
        from revit_mcp.routes_s2k import register_s2k_routes
        register_s2k_routes(api)
        _dbg("routes_s2k ok")

        _dbg("importing routes_sections")
        _reload_module("revit_mcp.routes_sections")
        from revit_mcp.routes_sections import register_sections_routes
        register_sections_routes(api)
        _dbg("routes_sections ok")

        _dbg("importing routes_arc")
        _reload_module("revit_mcp.routes_arc")
        from revit_mcp.routes_arc import register_arc_routes
        register_arc_routes(api)
        _dbg("routes_arc ok")

        logger.info("Todas las rutas S2K-MCP registradas correctamente")
        _dbg("ALL ROUTES REGISTERED OK")
    except Exception as e:
        _dbg("REGISTER FAILED: %s" % str(e))
        _dbg(traceback.format_exc())
        logger.error("Fallo al registrar rutas MCP: %s", str(e))
        raise


_dbg("calling register_routes")
register_routes()

_dbg("starting auto-open worker")
t_auto = threading.Thread(target=_auto_open_worker)
t_auto.daemon = True
t_auto.start()

_dbg("=== startup.py end ===")
