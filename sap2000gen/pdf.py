"""Conversion de PDF a imagenes (para OCR / IA de vision)."""

from __future__ import annotations

import os
from typing import List, Tuple

try:
    import fitz  # PyMuPDF
    PYMUPDF_OK = True
except Exception:  # pragma: no cover
    PYMUPDF_OK = False


def pdf_to_images(pdf_path: str, dpi: int = 200, out_dir: str | None = None) -> List[str]:
    """Convierte cada pagina del PDF a PNG. Devuelve las rutas de las imagenes."""
    if not PYMUPDF_OK:
        raise RuntimeError("Falta PyMuPDF: pip install pymupdf")
    out_dir = out_dir or os.path.join(os.path.dirname(pdf_path), "_planos_png")
    os.makedirs(out_dir, exist_ok=True)

    doc = fitz.open(pdf_path)
    images: List[str] = []
    for i, page in enumerate(doc):
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        out = os.path.join(out_dir, f"{os.path.splitext(os.path.basename(pdf_path))[0]}_p{i+1}.png")
        pix.save(out)
        images.append(out)
    doc.close()
    return images


def pdf_to_text(pdf_path: str) -> List[Tuple[int, str]]:
    """Extrae el texto de cada pagina. Devuelve [(num_pagina, texto), ...].

    Si una pagina es una imagen escaneada, el texto saldra vacio y habra que
    usar pdf_to_images() para leerla como imagen.
    """
    if not PYMUPDF_OK:
        raise RuntimeError("Falta PyMuPDF: pip install pymupdf")
    doc = fitz.open(pdf_path)
    pages: List[Tuple[int, str]] = []
    for i, page in enumerate(doc):
        pages.append((i + 1, page.get_text().strip()))
    doc.close()
    return pages


def pdf_inspect(pdf_path: str, dpi: int = 200, out_dir: str | None = None,
                save_images: bool = False) -> dict:
    """Resumen completo de un PDF: paginas, texto por pagina y rutas de imagen.

    Para paginas sin texto (escaneadas) se generan PNG con pdf_to_images()
    (o si save_images=True se generan todas). El dict devuelto incluye
    'pages' [(num, texto)], 'blank' [num_pagina sin texto] y 'images' [rutas].
    """
    pages = pdf_to_text(pdf_path)
    blank = [n for n, t in pages if not t.strip()]
    images: List[str] = []
    if save_images or blank:
        imgs = pdf_to_images(pdf_path, dpi=dpi, out_dir=out_dir)
        images = [im for n, im in zip(range(1, len(pages) + 1), imgs)
                  if save_images or n in blank]
    return {"pages": pages, "blank": blank, "images": images}
