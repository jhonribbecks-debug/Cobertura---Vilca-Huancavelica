"""Utilidades de lectura de texto para documentos del proyecto.

Extrae contenido textual de archivos que la memoria no puede leer directamente
(docx, xlsx, csv, s2k) y lo volca a texto UTF-8 plano para su inspeccion.
"""

from __future__ import annotations

import os
import re
from typing import List, Tuple

try:
    from docx import Document
    DOCX_OK = True
except Exception:  # pragma: no cover
    DOCX_OK = False

try:
    import pandas as pd
    PANDAS_OK = True
except Exception:  # pragma: no cover
    PANDAS_OK = False


def docx_to_text(path: str) -> List[Tuple[int, str]]:
    """Extrae texto por parrafo. Devuelve [(numero_de_parrafo, texto)]."""
    if not DOCX_OK:
        raise RuntimeError("Falta python-docx: pip install python-docx")
    doc = Document(path)
    out: List[Tuple[int, str]] = []
    for i, p in enumerate(doc.paragraphs, 1):
        out.append((i, p.text))
    return out


def docx_dump(path: str, txt_path: str | None = None) -> str:
    """Voltea todo el texto del docx a un .txt UTF-8 y devuelve el path."""
    pages = docx_to_text(path)
    txt_path = txt_path or (os.path.splitext(path)[0] + ".txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"## {path} ({len(pages)} parrafos)\n\n")
        for n, t in pages:
            if t.strip():
                f.write(f"[{n}] {t}\n")
    return txt_path


def excel_to_csv(path: str, out_dir: str | None = None) -> List[str]:
    """Convierte cada hoja de un Excel a CSV UTF-8."""
    if not PANDAS_OK:
        raise RuntimeError("Falta pandas/openpyxl: pip install pandas openpyxl")
    out_dir = out_dir or os.path.dirname(path)
    os.makedirs(out_dir, exist_ok=True)
    xls = pd.ExcelFile(path)
    out: List[str] = []
    for sh in xls.sheet_names:
        df = xls.parse(sh)
        safe = re.sub(r"\W+", "_", sh)
        dst = os.path.join(out_dir, f"{os.path.splitext(os.path.basename(path))[0]}_{safe}.csv")
        df.to_csv(dst, index=False, encoding="utf-8")
        out.append(dst)
    return out


def s2k_summary(path: str) -> dict:
    """Lectura ligera de un .s2k: cuenta bloques de datos clave."""
    counters = {
        "JOINT": 0, "FRAME": 0, "AREA": 0, "RESTRAINT": 0,
        "LOAD_PATTERN": 0, "LOAD_CASE": 0, "COMBO": 0,
        "SECTION": 0, "MATERIAL": 0, "MAT_PROP": 0,
        "FRAME_SECTION": 0, "TABLE": 0,
    }
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            s = line.strip()
            if s.startswith("TABLE"):
                counters["TABLE"] += 1
            for key in counters:
                if key != "TABLE" and s.startswith(key + " "):
                    counters[key] += 1
    dim = {"X": None, "Y": None, "Z": None}
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        txt = f.read()
    for axis in dim:
        m = re.search(rf"{axis}\s*=\s*(-?\d+\.?\d*)", txt)
        if m:
            dim[axis] = float(m.group(1))
    return {"counters": counters, "dims": dim}
