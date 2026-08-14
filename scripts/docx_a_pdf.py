"""Convierte un .docx a PDF usando Microsoft Word (COM, pywin32).

Uso:
    python docx_a_pdf.py [archivo.docx] [archivo.pdf]

Si no se pasan argumentos, convierte la memoria de calculo del proyecto.
"""

from __future__ import annotations

import os
import sys

import win32com.client


def docx_a_pdf(docx_path: str, pdf_path: str | None = None) -> str:
    """Convierte `docx_path` a PDF y devuelve la ruta del PDF."""
    docx_path = os.path.abspath(docx_path)
    if not os.path.exists(docx_path):
        raise FileNotFoundError(f"No existe el archivo: {docx_path}")
    pdf_path = pdf_path or os.path.splitext(docx_path)[0] + ".pdf"
    pdf_path = os.path.abspath(pdf_path)

    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    try:
        doc = word.Documents.Open(docx_path, ReadOnly=True)
        try:
            doc.SaveAs(pdf_path, FileFormat=17)  # 17 = wdFormatPDF
        finally:
            doc.Close(False)
    finally:
        word.Quit()
    return pdf_path


def main() -> None:
    args = [a for a in sys.argv[1:] if a and not a.startswith("-")]
    if args:
        docx, pdf = args[0], (args[1] if len(args) > 1 else None)
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        docx = os.path.join(here, "Memoria_de_Calculo_Estructural_Cobertura_Huancalpi.docx")
        pdf = None
    out = docx_a_pdf(docx, pdf)
    print("OK:", out)


if __name__ == "__main__":
    main()
