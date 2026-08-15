# -*- coding: UTF-8 -*-
"""Genera payloads JSON para las rutas de Revit desde el .s2k."""

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from s2k_to_json import parse_s2k_geometry  # noqa: E402


def _default_s2k():
    env = os.environ.get("TENORIOUS_S2K", "")
    if env and os.path.exists(env):
        return env
    # si TENORIOUS_PROJECT/TENORIOUS_DIR apuntan a la carpeta del proyecto,
    # buscar el .s2k dentro de su subcarpeta MN (o en la raiz).
    proj = os.environ.get("TENORIOUS_PROJECT", "")
    proj_dir = os.environ.get("TENORIOUS_DIR", "")
    base = ""
    if proj_dir and os.path.isdir(proj_dir):
        base = proj_dir
    elif proj and os.path.isfile(proj):
        base = os.path.dirname(proj)
    if base:
        for sub in ("MN", ""):
            cand = os.path.join(base, sub)
            matches = sorted(glob.glob(os.path.join(cand, "*.s2k")))
            if matches:
                return matches[0]
    return ""


def main():
    ap = argparse.ArgumentParser(description="Genera payloads JSON para Revit")
    ap.add_argument("--s2k", default=_default_s2k(),
                    help="Ruta del .s2k (default: TENORIOUS_S2K o busca en la "
                         "carpeta del proyecto/MN)")
    ap.add_argument("--out", default=os.environ.get(
        "TENORIOUS_OUT",
        os.path.join(os.environ.get("TEMP", os.environ.get("TMP", ".")), "opencode")),
        help="Carpeta de salida de los payloads")
    args = ap.parse_args()

    if not args.s2k or not os.path.exists(args.s2k):
        print("ERROR: no se encontro el .s2k. Pasa --s2k <ruta> o define "
              "TENORIOUS_S2K.")
        return 1

    d = parse_s2k_geometry(args.s2k)
    os.makedirs(args.out, exist_ok=True)

    with open(os.path.join(args.out, "ensure_sections.json"), "w", encoding="utf-8") as fh:
        json.dump({"sections": d["sections"], "use_project": True}, fh, ensure_ascii=False)

    F = "HSS-Sección estructural hueca"
    C = "HSS-Sección estructural hueca-Pilar"
    fm = {}
    for name in d["sections"]:
        if "HSS100x50x4.5" in name:
            fm[name] = {"framing": {"family": F, "type": "HSS100x50x4.5"}}
        elif "HSS100x100x2.5" in name:
            fm[name] = {"framing": {"family": F, "type": "HSS100x100x2.5"}}
        elif "HSS240x80x2" in name:
            fm[name] = {"framing": {"family": F, "type": "HSS240x80x2"}}
        elif "HSS500x200x4.5" in name:
            fm[name] = {
                "framing": {"family": F, "type": "HSS500x200x4.5"},
                "column": {"family": C, "type": "HSS500x200x4.5"},
            }
        elif "5/8" in name:
            fm[name] = {"framing": {"family": "Round Bar", "type": "O 5/8"}}

    with open(os.path.join(args.out, "import_s2k.json"), "w", encoding="utf-8") as fh:
        json.dump({
            "unit": "m",
            "joints": d["joints"],
            "frames": d["frames"],
            "sections": d["sections"],
            "family_map": fm,
            "make_columns": True,
            "clear_existing": True,
        }, fh, ensure_ascii=False)

    print("s2k:", args.s2k)
    print("joints:", len(d["joints"]), "frames:", len(d["frames"]),
          "sections:", len(d["sections"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
