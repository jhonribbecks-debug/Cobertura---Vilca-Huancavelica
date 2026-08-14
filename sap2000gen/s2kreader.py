"""Lector de plantillas .s2k de SAP2000.

Convierte un archivo .s2k en un objeto S2kModel manteniendo las tablas
de definicion (materiales, secciones, cargas, combinaciones) como texto
literal, listas para "pasar por alto" cuando se regenera la geometria.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from .model import S2kModel

# Tablas que dependen de la geometria y que el generador reemplaza.
GEOM_TABLES = {
    "JOINT COORDINATES",
    "CONNECTIVITY - FRAME",
    "JOINT RESTRAINT ASSIGNMENTS",
    "FRAME SECTION ASSIGNMENTS",
    "FRAME RELEASE ASSIGNMENTS 1 - GENERAL",
    "FRAME TENSION AND COMPRESSION LIMITS",
    "JOINT LOADS - FORCE",
    "FRAME LOADS - DISTRIBUTED",
}


def parse_s2k(path: str) -> S2kModel:
    """Lee un .s2k y devuelve un S2kModel con las tablas no geometricas."""
    model = S2kModel()
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()

    current: str | None = None
    rows: List[str] = []

    def flush() -> None:
        if current is not None and rows:
            model.passthrough.append((current, list(rows)))

    for ln in lines:
        stripped = ln.strip()
        if stripped == "END TABLE DATA":
            flush()
            current = None
        elif stripped.startswith("TABLE:"):
            flush()
            current = stripped[len("TABLE:"):].strip().strip('"').strip()
            rows = []
        elif stripped:
            if current is not None:
                rows.append(ln)
    flush()

    # Recoger secciones definidas en la plantilla (para reusar nombres).
    for name, row_lines in model.passthrough:
        if name == "FRAME SECTION PROPERTIES 01 - GENERAL":
            for row in row_lines:
                fields: Dict[str, str] = {}
                for field in row.split():
                    if "=" in field:
                        k, v = field.split("=", 1)
                        fields[k] = v
                if "SectionName" in fields:
                    model.sections[fields["SectionName"]] = {
                        "Material": fields.get("Material", "A36"),
                        "Shape": fields.get("Shape", "General"),
                    }

    return model
