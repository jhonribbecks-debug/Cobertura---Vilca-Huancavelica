# -*- coding: UTF-8 -*-
"""Genera payloads JSON para las rutas de Revit desde el .s2k."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from s2k_to_json import parse_s2k_geometry  # noqa: E402

S2K = r"C:\Users\aintc\OneDrive\Escritorio\Tenorious\MN\HUANCALPI - MODELO FINAL v3.s2k"
OUT = r"C:\Users\aintc\AppData\Local\Temp\opencode"


def main():
    d = parse_s2k_geometry(S2K)
    os.makedirs(OUT, exist_ok=True)

    with open(os.path.join(OUT, "ensure_sections.json"), "w", encoding="utf-8") as fh:
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

    with open(os.path.join(OUT, "import_s2k.json"), "w", encoding="utf-8") as fh:
        json.dump({
            "unit": "m",
            "joints": d["joints"],
            "frames": d["frames"],
            "sections": d["sections"],
            "family_map": fm,
            "make_columns": True,
            "clear_existing": True,
        }, fh, ensure_ascii=False)

    print("joints:", len(d["joints"]), "frames:", len(d["frames"]),
          "sections:", len(d["sections"]))


if __name__ == "__main__":
    main()
