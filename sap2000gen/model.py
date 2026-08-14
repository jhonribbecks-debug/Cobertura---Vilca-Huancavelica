"""Modelo de datos estructural minimal para generar archivos .s2k.

Un .s2k de SAP2000 es texto plano con tablas. Este paquete lo trata como
un conjunto de tablas: la plantilla aporta las tablas "de definicion"
(materiales, secciones, cargas, combinaciones) y el generador sustituye
las tablas "de geometria" (nudos, barras, asignaciones, cargas en nudos).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Joint:
    """Un nudo. restraints = secuencia de 6 bool (UX UY UZ RX RY RZ)."""

    id: int
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    restraints: Optional[List[bool]] = None  # None -> libre


@dataclass
class Frame:
    """Una barra definida por nudos extremos."""

    id: int
    joint_i: int
    joint_j: int
    section: str = "ARCO"
    # releases (12 bool): PI V2I V3I TI M2I M3I PJ V2J V3J TJ M2J M3J
    releases: Optional[List[bool]] = None
    comp_only: bool = False  # "tension and compression limits" CompLimit=Yes


@dataclass
class JointLoad:
    """Carga puntual en un nudo, en un patron de carga."""

    joint: int
    pattern: str
    f1: float = 0.0
    f2: float = 0.0
    f3: float = 0.0
    m1: float = 0.0
    m2: float = 0.0
    m3: float = 0.0


@dataclass
class FrameDistLoad:
    """Carga distribuida sobre una barra (global o local)."""

    frame: int
    pattern: str
    direction: str = "GLOBAL"
    coord_sys: str = "GLOBAL"
    type_: str = "Force"
    dist1: float = 0.0
    dist2: float = 0.0
    val1: float = 0.0
    val2: float = 0.0


@dataclass
class Section:
    """Seccion de barra. Si shape != General, se emite tabla de tipo real."""

    name: str
    material: str = "A36"
    shape: str = "General"  # General | Rectangle | Pipe | I/WideFlange...
    area: float = 0.0
    tors: float = 0.0
    i33: float = 0.0
    i22: float = 0.0
    as2: float = 0.0
    as3: float = 0.0
    color: str = "Green"


class S2kModel:
    """Contenedor del modelo: tablas pasantes + geometria nueva."""

    def __init__(self) -> None:
        self.passthrough: List[tuple] = []  # (nombre_tabla, lista de lineas)
        self.joints: List[Joint] = []
        self.frames: List[Frame] = []
        self.joint_loads: List[JointLoad] = []
        self.frame_loads: List[FrameDistLoad] = []
        self.sections: Dict[str, Section] = {}
        # secciones reales (name -> fila de tabla completa), reemplazan a la plantilla
        self.section_rows: Dict[str, str] = {}
        # materiales extra: nombre_tabla -> lista de filas (se agregan a las de la plantilla)
        self.extra_material_rows: Dict[str, List[str]] = {}

    def set_real_sections(self, rows: Dict[str, str]) -> None:
        """Sustituye las secciones de la plantilla por perfiles reales calculados."""
        self.section_rows.update(rows)

    def add_material(self, material: str) -> None:
        """Agrega un material de acero (A36/A572) a las tablas de materiales."""
        from .sections import material_rows
        rows = material_rows(material)
        for table, row in rows.items():
            self.extra_material_rows.setdefault(table, []).append(row)

    def add_joint(self, j: Joint) -> None:
        self.joints.append(j)

    def add_frame(self, f: Frame) -> None:
        self.frames.append(f)
