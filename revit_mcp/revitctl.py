# -*- coding: UTF-8 -*-
"""Controlador del ciclo Revit + pyRevit Routes para automatizacion.

Uso:
  python revitctl.py stop
  python revitctl.py start [--timeout 240]
  python revitctl.py call /ensure_sections/ --payload data.json [--timeout 600]
  python revitctl.py call /save_doc/ [--timeout 120]
  python revitctl.py status
"""

import argparse
import json
import os
import subprocess
import sys
import time

import httpx

REVIT_EXE = os.environ.get(
    "TENORIOUS_REVIT_EXE",
    r"C:\Program Files\Autodesk\Revit 2027\Revit.exe")
PROJECT = os.environ.get("TENORIOUS_PROJECT", "")
BASE = "http://127.0.0.1:48884/revit_mcp"


def _revit_running():
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Revit.exe"],
                             capture_output=True, text=True, timeout=30).stdout
        return "Revit.exe" in out
    except Exception:
        return False


def stop():
    if not _revit_running():
        return {"stopped": True, "was_running": False}
    subprocess.run(["taskkill", "/IM", "Revit.exe", "/F"],
                   capture_output=True, text=True, timeout=30)
    deadline = time.time() + 30
    while time.time() < deadline and _revit_running():
        time.sleep(1)
    return {"stopped": True, "was_running": True}


def start(timeout=240, project=None):
    project = project or PROJECT
    if not project:
        print("ERROR: no hay proyecto. Pasa --project <ruta.rvt> o "
              "definelo en TENORIOUS_PROJECT.")
        return {"healthy": False, "reason": "missing project path"}
    subprocess.Popen([REVIT_EXE, project])
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(BASE + "/status/", timeout=5)
            j = r.json()
            if j.get("health") == "healthy":
                return {"healthy": True, "doc": j.get("document_title")}
        except Exception:
            pass
        time.sleep(4)
    return {"healthy": False, "reason": "timeout waiting for healthy"}


def status():
    try:
        r = httpx.get(BASE + "/status/", timeout=8)
        return r.status_code, r.text
    except Exception as e:
        return 0, json.dumps({"error": str(e)})


def call(route, payload=None, timeout=600):
    r = httpx.post(BASE + route, json=payload or {}, timeout=timeout)
    return r.status_code, r.text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["stop", "start", "call", "status"])
    ap.add_argument("route", nargs="?")
    ap.add_argument("--payload", nargs="?")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--start-timeout", type=int, default=240)
    ap.add_argument("--project", nargs="?", default=None,
                    help="Ruta del .rvt a abrir (default: TENORIOUS_PROJECT)")
    args = ap.parse_args()

    if args.cmd == "stop":
        print(json.dumps(stop()))
    elif args.cmd == "start":
        print(json.dumps(start(args.start_timeout, project=args.project)))
    elif args.cmd == "status":
        code, text = status()
        print("HTTP", code)
        print(text)
    elif args.cmd == "call":
        payload = None
        if args.payload:
            with open(args.payload, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
        code, text = call(args.route, payload, args.timeout)
        print("HTTP", code)
        print(text)


if __name__ == "__main__":
    main()
