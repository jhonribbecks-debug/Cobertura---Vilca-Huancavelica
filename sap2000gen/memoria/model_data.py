"""Extraccion de datos estructurales a partir de un modelo .s2k de SAP2000.

Un archivo .s2k es texto plano organizado en tablas delimitadas por
"TABLE: <nombre>" ... "END TABLE DATA". Este modulo las lee de forma
generica (filas de pares clave=valor) y devuelve una estructura limpia
para alimentar la memoria de calculo.
"""

from __future__ import annotations

import math
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

_KV_KEY = re.compile(r'(?<![\w.])(\w+)=')
_QUOTED = re.compile(r'^"(.*)"$')

# Conversiones de unidades (el modelo suele estar en kgf y metros).
G = 9.80665

# Tablas necesarias para armar la memoria. Las tablas de resultados de
# analisis se ignoran salvo que se pidan como `extra_tables`.
MODEL_TABLES = {
    "PROJECT INFORMATION",
    "PROGRAM CONTROL",
    "MATERIAL PROPERTIES 02 - BASIC MECHANICAL PROPERTIES",
    "MATERIAL PROPERTIES 03A - STEEL DATA",
    "FRAME SECTION PROPERTIES 01 - GENERAL",
    "LOAD PATTERN DEFINITIONS",
    "LOAD CASE DEFINITIONS",
    "COMBINATION DEFINITIONS",
    "JOINT COORDINATES",
    "CONNECTIVITY - FRAME",
    "FRAME SECTION ASSIGNMENTS",
    "CONNECTIVITY - AREA",
    "JOINT RESTRAINT ASSIGNMENTS",
    "JOINT LOADS - FORCE",
    "PREFERENCES - STEEL DESIGN - AISC 360-16",
}


def stream_tables(path: str,
                  wanted: Optional[set] = None) -> "OrderedDict[str, List[str]]":
    """Lee el .s2k por lineas (streaming) y devuelve solo las tablas pedidas.

    Los archivos exportados con resultados pueden pesar varios GB (decenas de
    millones de filas); este iterador evita cargarlos completos en memoria.
    Si `wanted` es None, captura todas las tablas (solo para archivos chicos).
    """
    wanted = {w.lower() for w in wanted} if wanted else None
    tables: "OrderedDict[str, List[str]]" = OrderedDict()
    current: Optional[str] = None
    keep = False
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            s = ln.strip()
            if s.startswith("TABLE:"):
                current = s[len("TABLE:"):].strip().strip('"').strip()
                keep = wanted is None or any(
                    w in current.lower() for w in wanted)
                if keep:
                    tables.setdefault(current, [])
            elif s == "END TABLE DATA":
                current = None
                keep = False
            elif s and current is not None and keep:
                tables[current].append(ln)
    return tables


def parse_tables(path: str) -> "OrderedDict[str, List[str]]":
    """Divide el .s2k en tablas -> lista de filas crudas (archivos chicos)."""
    return stream_tables(path)


def join_continuations(lines: List[str]) -> List[str]:
    """Une filas de tablas partidas en varias lineas.

    SAP2000 continua una fila larga cuando la linea termina en '_' y sigue
    en la siguiente (con espacios). Devuelve filas logicas completas.
    """
    out: List[str] = []
    buf: Optional[str] = None
    for ln in lines:
        s = ln.rstrip()
        if buf is None:
            buf = s
        else:
            buf = buf.rstrip()
            buf = buf[:-1] + " " + s.lstrip() if buf.endswith("_") else buf + " " + s.lstrip()
        if s.endswith("_"):
            continue
        out.append(buf)
        buf = None
    if buf is not None:
        out.append(buf)
    return out


def kv(row: str) -> Dict[str, str]:
    """Convierte una fila 'A=1 B="dos palabras" C=x' en un dict.

    Los valores sin comillas pueden contener espacios; el valor termina
    cuando comienza el siguiente par 'clave='.
    """
    keys = list(_KV_KEY.finditer(row))
    result: Dict[str, str] = {}
    for i, m in enumerate(keys):
        key = m.group(1)
        start = m.end()
        end = keys[i + 1].start() if i + 1 < len(keys) else len(row)
        value = row[start:end].strip()
        q = _QUOTED.match(value)
        if q:
            value = q.group(1)
        result[key] = value
    return result


def _f(v: Optional[str], default: float = 0.0) -> float:
    try:
        return float(v) if v not in (None, "") else default
    except ValueError:
        return default


def _fmt_m(v: float, unit: str = "mm", nd: int = 0) -> str:
    """Formatea un valor en metros a milimetros o centimetros."""
    if unit == "mm":
        return f"{v * 1000:.{nd}f} mm"
    if unit == "cm":
        return f"{v * 100:.{nd}f} cm"
    return f"{v:.{nd}f} m"


def fy_mpa(fy_kgf_m2: float) -> float:
    """Convierte esfuerzo de kgf/m2 a MPa."""
    return fy_kgf_m2 * G / 1e6


def force_scale_for_units(units: str) -> float:
    """Factor para pasar las fuerzas del modelo a kgf.

    Toma el primer token (fuerza) de la cadena de unidades de SAP2000:
    'kgf, m, C' -> 1 ; 'Tonf, m, C' / 'tf, m' -> 1000 ; 'N, mm' -> 0.10197...
    """
    token = units.split(",")[0].strip().lower().split()[0] if units else "kgf"
    if token in ("tonf", "ton", "tonne", "tf", "kip", "kips"):
        return 1000.0
    if token in ("kn", "kilonewton"):
        return 101.9716
    if token in ("n", "newton"):
        return 0.1019716
    return 1.0  # kgf / kg


@dataclass
class Material:
    name: str
    fy: float = 0.0        # kgf/m2
    fu: float = 0.0        # kgf/m2
    e: float = 0.0         # kgf/m2
    unit_weight: float = 0.0  # kgf/m3
    poisson: float = 0.3

    @property
    def fy_mpa(self) -> float:
        return fy_mpa(self.fy)

    @property
    def fu_mpa(self) -> float:
        return fy_mpa(self.fu)

    @property
    def fy_kgf_cm2(self) -> float:
        return self.fy * G / 1e4


@dataclass
class Section:
    name: str
    material: str = "A36"
    shape: str = "General"
    t3: float = 0.0
    t2: float = 0.0
    tf: float = 0.0
    tw: float = 0.0
    notes: str = ""
    area_sap: float = 0.0   # Area que calcula SAP2000 (m2), si viene en el .s2k

    @property
    def label(self) -> str:
        return f"{self.t3 * 1000:.0f}x{self.t2 * 1000:.0f}"

    def area(self) -> float:
        """Area (m2). Prefiere el valor que calcula SAP2000 si existe."""
        if self.area_sap:
            return self.area_sap
        if self.shape.lower() in ("circle",):
            d = self.t3
            return math.pi / 4 * d * d
        a, b, tf, tw = self.t3, self.t2, self.tf, self.tw
        return a * b - (a - 2 * tw) * (b - 2 * tf)

    def i33(self) -> float:
        """Inercia fuerte (m4) de tubo rectangular hueco."""
        a, b, tf, tw = self.t3, self.t2, self.tf, self.tw
        return (b * a ** 3 - (b - 2 * tf) * (a - 2 * tw) ** 3) / 12

    def i22(self) -> float:
        a, b, tf, tw = self.t3, self.t2, self.tf, self.tw
        return (a * b ** 3 - (a - 2 * tw) * (b - 2 * tf) ** 3) / 12

    def z33(self) -> float:
        """Modulo plastico (m3) respecto al eje fuerte (3-3)."""
        a, b, tf, tw = self.t3, self.t2, self.tf, self.tw
        return (b * a * a - (b - 2 * tf) * (a - 2 * tw) ** 2) / 4

    def z22(self) -> float:
        a, b, tf, tw = self.t3, self.t2, self.tf, self.tw
        return (a * b * b - (a - 2 * tw) * (b - 2 * tf) ** 2) / 4

    def r33(self) -> float:
        """Radio de giro (m) respecto al eje fuerte."""
        a = self.area()
        return math.sqrt(self.i33() / a) if a else 0.0

    def r22(self) -> float:
        a = self.area()
        return math.sqrt(self.i22() / a) if a else 0.0

    def weight_per_m(self, unit_weight: float) -> float:
        """Peso lineal (kgf/m) = A * gamma."""
        return self.area() * unit_weight


@dataclass
class Combo:
    name: str
    type: str = "Linear Add"
    terms: List[Tuple[str, float]] = field(default_factory=list)

    def __str__(self) -> str:
        parts = []
        for case, sf in self.terms:
            if sf == 1.0:
                parts.append(case)
            elif sf == -1.0:
                parts.append(f"- {case}")
            elif sf > 0:
                parts.append(f"{sf:g} {case}")
            else:
                parts.append(f"- {abs(sf):g} {case}")
        return " + ".join(parts)


@dataclass
class ModelData:
    path: str = ""
    project: Dict[str, str] = field(default_factory=dict)
    units: str = "kgf, m"
    materials: Dict[str, Material] = field(default_factory=dict)
    sections: Dict[str, Section] = field(default_factory=dict)
    load_patterns: List[Tuple[str, str]] = field(default_factory=list)
    load_cases: List[Tuple[str, str]] = field(default_factory=list)
    combos: List[Combo] = field(default_factory=list)
    frames_per_section: Dict[str, int] = field(default_factory=dict)
    steel_code: str = "AISC 360-16"
    n_joints: int = 0
    n_frames: int = 0
    n_areas: int = 0
    n_restraints: int = 0
    n_joint_loads: int = 0
    min_xyz: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    max_xyz: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    joints: Dict[int, Tuple[float, float, float]] = field(default_factory=dict)
    frames: Dict[int, Tuple[int, int]] = field(default_factory=dict)
    frame_section: Dict[int, str] = field(default_factory=dict)
    restrained_joints: List[int] = field(default_factory=list)
    total_weight: float = 0.0   # kgf (peso total de acero del modelo)
    frame_lengths: Dict[str, float] = field(default_factory=dict)
    raw_tables: "OrderedDict[str, List[str]]" = field(default_factory=OrderedDict)
    errors: List[str] = field(default_factory=list)

    @property
    def dims(self) -> Dict[str, float]:
        x0, y0, z0 = self.min_xyz
        x1, y1, z1 = self.max_xyz
        return {"largo": x1 - x0, "ancho": y1 - y0, "alto": z1 - z0,
                "zmin": z0, "zmax": z1}


def extract_model(path: str,
                  extra_tables: Optional[Iterable[str]] = None) -> ModelData:
    """Lee el .s2k (streaming) y devuelve el ModelData con todo lo extraido.

    `extra_tables` permite capturar tablas adicionales (p.ej. de resultados)
    que quedan disponibles en `md.raw_tables` sin re-leer el archivo.
    """
    md = ModelData(path=path)
    wanted = set(MODEL_TABLES)
    if extra_tables:
        wanted |= {t for t in extra_tables}
    tables = stream_tables(path, wanted)
    if not tables:
        md.errors.append("No se pudieron leer tablas del archivo .s2k")
        return md
    if extra_tables:
        md.raw_tables = tables

    # ---- Informacion del proyecto ----
    for row in tables.get("PROJECT INFORMATION", []):
        k = kv(row)
        if "Item" in k and "Data" in k:
            md.project[k["Item"]] = k["Data"]

    units_str = ""
    for row in tables.get("PROGRAM CONTROL", [])[:2]:
        k = kv(row)
        if "CurrUnits" in k:
            units_str = k["CurrUnits"]
        elif "Units" in k:
            units_str = k["Units"]
    md.units = units_str or "kgf, m"
    fs = force_scale_for_units(md.units)   # 1000 si el modelo esta en tf

    # ---- Materiales (normalizados a kgf) ----
    mech = {kv(r)["Material"]: kv(r) for r in tables.get(
        "MATERIAL PROPERTIES 02 - BASIC MECHANICAL PROPERTIES", []) if "Material" in kv(r)}
    steel = {kv(r)["Material"]: kv(r) for r in tables.get(
        "MATERIAL PROPERTIES 03A - STEEL DATA", []) if "Material" in kv(r)}
    names = set(mech) | set(steel)
    for n in names:
        m = Material(name=n)
        b = mech.get(n, {})
        s = steel.get(n, {})
        m.e = _f(b.get("E1")) * fs
        m.poisson = _f(b.get("U12"), 0.3)
        m.unit_weight = _f(b.get("UnitWeight")) * fs
        m.fy = _f(s.get("Fy")) * fs
        m.fu = _f(s.get("Fu")) * fs
        md.materials[n] = m

    # ---- Secciones ----
    for row in tables.get("FRAME SECTION PROPERTIES 01 - GENERAL", []):
        k = kv(row)
        if "SectionName" not in k:
            continue
        md.sections[k["SectionName"]] = Section(
            name=k["SectionName"],
            material=k.get("Material", "A36"),
            shape=k.get("Shape", "General"),
            t3=_f(k.get("t3")),
            t2=_f(k.get("t2")),
            tf=_f(k.get("tf"), _f(k.get("t3")) if k.get("Shape", "").lower() == "circle" else 0.0),
            tw=_f(k.get("tw")),
            notes=k.get("Notes", ""),
            area_sap=_f(k.get("Area")),
        )

    # ---- Patrones de carga ----
    for row in tables.get("LOAD PATTERN DEFINITIONS", []):
        k = kv(row)
        if "LoadPat" in k:
            md.load_patterns.append((k["LoadPat"], k.get("DesignType", "")))

    # ---- Casos de carga ----
    for row in tables.get("LOAD CASE DEFINITIONS", []):
        k = kv(row)
        if "Case" in k:
            md.load_cases.append((k["Case"], k.get("Type", "")))

    # ---- Combinaciones ----
    cur: Optional[Combo] = None
    for row in tables.get("COMBINATION DEFINITIONS", []):
        k = kv(row)
        if "ComboName" in k:
            name = k["ComboName"]
            if cur is None or cur.name != name:
                cur = Combo(name=name, type=k.get("ComboType", "Linear Add"))
                md.combos.append(cur)
            if "CaseName" in k:
                cur.terms.append((k["CaseName"], _f(k.get("ScaleFactor"), 1.0)))

    # ---- Geometria ----
    joints: Dict[int, Tuple[float, float, float]] = {}
    for row in tables.get("JOINT COORDINATES", []):
        k = kv(row)
        if "Joint" in k:
            x = _f(k.get("XorR"), _f(k.get("X")))
            joints[int(float(k["Joint"]))] = (x, _f(k.get("Y")), _f(k.get("Z")))
    md.n_joints = len(joints)
    md.joints = joints
    if joints:
        xs = [p[0] for p in joints.values()]
        ys = [p[1] for p in joints.values()]
        zs = [p[2] for p in joints.values()]
        md.min_xyz = (min(xs), min(ys), min(zs))
        md.max_xyz = (max(xs), max(ys), max(zs))

    frames: Dict[int, Tuple[int, int]] = {}
    frame_len: Dict[int, Optional[float]] = {}
    for row in tables.get("CONNECTIVITY - FRAME", []):
        k = kv(row)
        if "Frame" in k:
            fid = int(float(k["Frame"]))
            frames[fid] = (int(float(k.get("JointI", 0))),
                           int(float(k.get("JointJ", 0))))
            if k.get("Length"):
                frame_len[fid] = _f(k.get("Length"))
    md.n_frames = len(frames)
    md.frames = frames

    frame_section: Dict[int, str] = {}
    for row in tables.get("FRAME SECTION ASSIGNMENTS", []):
        k = kv(row)
        if "Frame" in k:
            frame_section[int(float(k["Frame"]))] = (
                k.get("AnalSect") or k.get("SectionName") or "")
    md.frame_section = frame_section

    # Peso y longitudes por seccion (todo normalizado a kgf)
    per_sec_len: Dict[str, float] = {}
    per_sec_cnt: Dict[str, int] = {}
    mat_w = {n: m.unit_weight for n, m in md.materials.items()}
    for fid, (i, j) in frames.items():
        sec = frame_section.get(fid, "")
        if not sec:
            continue
        p1, p2 = joints.get(i), joints.get(j)
        length = frame_len.get(fid)
        if length is None and p1 is not None and p2 is not None:
            length = math.dist(p1, p2)
        if not length:
            continue
        per_sec_len[sec] = per_sec_len.get(sec, 0.0) + length
        per_sec_cnt[sec] = per_sec_cnt.get(sec, 0) + 1
        sec_obj = md.sections.get(sec)
        if sec_obj is not None:
            gamma = mat_w.get(sec_obj.material, 0.0)
            md.total_weight += sec_obj.weight_per_m(gamma) * length
    md.frames_per_section = dict(sorted(per_sec_cnt.items(), key=lambda t: -t[1]))
    md.frame_lengths = per_sec_len

    md.n_areas = len(tables.get("CONNECTIVITY - AREA", []))
    md.n_restraints = len(tables.get("JOINT RESTRAINT ASSIGNMENTS", []))
    md.restrained_joints = []
    for row in tables.get("JOINT RESTRAINT ASSIGNMENTS", []):
        k = kv(row)
        if "Joint" in k:
            try:
                md.restrained_joints.append(int(float(k["Joint"])))
            except ValueError:
                pass
    md.n_joint_loads = len(tables.get("JOINT LOADS - FORCE", []))

    # ---- Norma de diseno ----
    for row in tables.get("PREFERENCES - STEEL DESIGN - AISC 360-16", [])[:1]:
        k = kv(row)
        if "Code" in k:
            md.steel_code = k["Code"]

    return md
