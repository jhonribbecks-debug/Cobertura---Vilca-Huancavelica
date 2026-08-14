"""Actualiza el indice (TOC) y exporta a PDF con Microsoft Word (COM).

Abre el .docx canónico generado por incorporar_metodologia.py
('Memoria_de_Calculo_Estructural_Cobertura_Huancalpi.docx'),
actualiza los campos (el TOC field -> un unico indice que incluye los nuevos
capitulos y anexos), repagina y guarda:
  - Memoria_de_Calculo_Estructural_Cobertura_Huancalpi.docx   (canonical, limpio)
  - Memoria_de_Calculo_Estructural_Cobertura_Huancalpi.pdf    (exportado)

Uso:
    python actualizar_indice_y_pdf.py
"""

from __future__ import annotations

import os
import sys

import win32com.client

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(
    ROOT, "Memoria_de_Calculo_Estructural_Cobertura_Huancalpi.docx")
FINAL_DOCX = os.path.join(
    ROOT, "Memoria_de_Calculo_Estructural_Cobertura_Huancalpi.docx")
FINAL_PDF = os.path.join(
    ROOT, "Memoria_de_Calculo_Estructural_Cobertura_Huancalpi.pdf")

wdFormatPDF = 17


def main() -> str:
    if not os.path.exists(SRC):
        print(f"ERROR: {SRC} no existe. Ejecuta incorporar_metodologia.py")
        sys.exit(1)

    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    doc = word.Documents.Open(os.path.abspath(SRC))
    try:
        doc.Repaginate()
        # Actualizar el TOC (y solo campos) -> un indice unico y ordenado
        try:
            if doc.TablesOfContents.Count >= 1:
                doc.TablesOfContents(1).Update()
        except Exception:
            pass
        try:
            doc.Fields.Update()
        except Exception as e:
            print(f"WARN al actualizar campos: {e}")
        doc.Repaginate()

        # Guardar canonical .docx
        doc.SaveAs(os.path.abspath(FINAL_DOCX), FileFormat=12)
        # Exportar PDF (SaveAs wdFormatPDF es el metodo mas fiable)
        doc.SaveAs(os.path.abspath(FINAL_PDF), FileFormat=wdFormatPDF)
        print(f"DOCX canonical -> {FINAL_DOCX}")
        print(f"PDF -> {FINAL_PDF}")
    finally:
        doc.Close(False)
        word.Quit()
        try:
            import pythoncom
            pythoncom.CoUninitialize()
        except Exception:
            pass
    return FINAL_PDF


if __name__ == "__main__":
    main()
