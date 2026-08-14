"""Calculo de propiedades geométricas de secciones estructurales.

Genera los campos que SAP2000 espera en la tabla
"FRAME SECTION PROPERTIES 01 - GENERAL" con Shape=General:
    Area, TorsConst, I33, I22, AS2, AS3, S33, S22, Z33, Z22, R33, R22

Unidades de entrada: milimetros (dibujo) -> salida en metros (SI).
"""

from __future__ import annotations

import math
import uuid
from typing import Dict, Optional

MM = 1e-3


def _fmt(x: float) -> str:
    return f"{x:.6g}"


def rect_tube(h: float, b: float, t: float) -> Dict[str, float]:
    """Tubo rectangular hueco (TR). h=alto, b=ancho, t=espesor [mm]."""
    h, b, t = h * MM, b * MM, t * MM
    A = h * b - (h - 2 * t) * (b - 2 * t)
    # momentos de inercia de la seccion hueca (rectangulo ext - rectangulo int)
    Ix = (b * h ** 3 - (b - 2 * t) * (h - 2 * t) ** 3) / 12
    Iy = (h * b ** 3 - (h - 2 * t) * (b - 2 * t) ** 3) / 12
    # torsion (aproximacion thin-wall cerrada)
    Am = (h - t) * (b - t)  # area media encerrada
    P = 2 * ((h - t) + (b - t))
    Tors = 4 * Am ** 2 * t / P
    Sx = 2 * Ix / h
    Sy = 2 * Iy / b
    return {
        "Area": A, "TorsConst": Tors, "I33": Ix, "I22": Iy,
        "AS2": 0.8 * A, "AS3": 0.8 * A, "S33": Sx, "S22": Sy,
        "Z33": 1.18 * Sx, "Z22": 1.18 * Sy, "R33": math.sqrt(Ix / A), "R22": math.sqrt(Iy / A),
    }


def round_bar(d: float) -> Dict[str, float]:
    """Barra/cable redondo macizo. d = diametro [mm]."""
    d = d * MM
    A = math.pi * d ** 2 / 4
    I = math.pi * d ** 4 / 64
    Tors = math.pi * d ** 4 / 32
    S = math.pi * d ** 3 / 32
    R = d / 4
    return {
        "Area": A, "TorsConst": Tors, "I33": I, "I22": I,
        "AS2": A, "AS3": A, "S33": S, "S22": S, "Z33": S, "Z22": S, "R33": R, "R22": R,
    }


def z_purlin(h: float, b: float, d: float, t: float) -> Dict[str, float]:
    """Correa Z plegada en frio. h=altura, b=ala, d=labio, t=espesor [mm].

    Aproximacion con placas rectas (desprecia radios de plegado).
    """
    h, b, d, t = h * MM, b * MM, d * MM, t * MM

    # placas (linea media): web vertical, 2 alas, 2 labios
    # web: centro x=0, y de 0 a h
    # ala superior: y=h, x de 0 a b   (ala derecha)
    # ala inferior: y=0, x de 0 a -b  (ala izquierda)
    # labio sup: x=b, y de h a h+d
    # labio inf: x=-b, y de 0 a -d
    plates = [
        ("web", 0.0, h / 2, 0.0, h, t),            # xcent, ycent, dx, dy
        ("ala sup", b / 2, h, b, 0.0, t),
        ("ala inf", -b / 2, 0.0, b, 0.0, t),
        ("labio sup", b, h + d / 2, 0.0, d, t),
        ("labio inf", -b, -d / 2, 0.0, d, t),
    ]

    A_total = 0.0
    area_cx = 0.0
    area_cy = 0.0
    parts = []
    for name, cx, cy, Lx, Ly, tt in plates:
        a = tt * math.hypot(Lx, Ly)
        A_total += a
        area_cx += a * cx
        area_cy += a * cy
        parts.append((name, a, cx, cy, Lx, Ly, tt))

    cx0 = area_cx / A_total if A_total else 0.0
    cy0 = area_cy / A_total if A_total else 0.0

    Ix = 0.0
    Iy = 0.0
    for name, a, cx, cy, Lx, Ly, tt in parts:
        # momento local de la placa
        L = math.hypot(Lx, Ly)
        if L == 0:
            continue
        angle = math.atan2(Ly, Lx)
        ux = Lx / L
        uy = Ly / L
        # I_local sobre ejes principales de la placa: L*t^3/12 (flojo) y t*L^3/12 (fuerte)
        I_weak = L * tt ** 3 / 12
        I_strong = tt * L ** 3 / 12
        # transformar al sistema global
        c, s = ux, uy
        Ixx_local = I_strong * c ** 2 + I_weak * s ** 2
        Iyy_local = I_strong * s ** 2 + I_weak * c ** 2
        dy = cy - cy0
        dx = cx - cx0
        Ix += Ixx_local + a * dy ** 2
        Iy += Iyy_local + a * dx ** 2

    Ix, Iy = max(Ix, Iy), min(Ix, Iy)
    # modulos de seccion elasticos
    Sx = Ix / (h / 2 + t) if h else 0.0
    Sy = Iy / (b + t) if b else 0.0
    Tors = (t ** 3 / 3) * (2 * (b + h) + 2 * d)  # thin-wall abierta
    return {
        "Area": A_total, "TorsConst": Tors, "I33": Ix, "I22": Iy,
        "AS2": 0.6 * A_total, "AS3": 0.6 * A_total, "S33": Sx, "S22": Sy,
        "Z33": 1.15 * Sx, "Z22": 1.15 * Sy, "R33": math.sqrt(Ix / A_total), "R22": math.sqrt(Iy / A_total),
    }


def material_rows(material: str) -> Dict[str, str]:
    """Filas de las 3 tablas de material para A36 o A572 (unidades Kgf,m,C)."""
    E = 2.039e10
    G = 7.8423e09
    if material.upper() == "A572":
        fy, fu = 3.5e7, 4.57e7
    else:  # A36
        fy, fu = 2.531e7, 4.078e7
    eff_fy = 1.5 * fy
    eff_fu = 1.2 * fu
    return {
        "MATERIAL PROPERTIES 01 - GENERAL":
            f"   Material={material}   Type=Steel   SymType=Isotropic   TempDepend=No   Color=Yellow   GUID=",
        "MATERIAL PROPERTIES 02 - BASIC MECHANICAL PROPERTIES":
            f"   Material={material}   UnitWeight=7850.0   UnitMass=800.4772   E1={E:.6g}   G12={G:.6g}   U12=0.30   A1=1.170E-05",
        "MATERIAL PROPERTIES 03A - STEEL DATA":
            f"   Material={material}   Fy={fy:.6g}   Fu={fu:.6g}   EffFy={eff_fy:.6g}   EffFu={eff_fu:.6g}   SSCurveOpt=Simple   SHard=0.015   SMax=0.11   SRup=0.17   FinalSlope=-0.1",
    }


def profile_properties(profile: str) -> Optional[Dict[str, float]]:
    """Devuelve propiedades reales para una designacion de perfil leida del plano."""
    p = profile.strip().upper().replace(" ", "")
    # Z 240x80x20x2.0 / Z240x80x20x2.0mm
    import re
    m = re.search(r"Z\s*([\d.]+)X([\d.]+)X([\d.]+)X([\d.]+)", p)
    if m:
        return z_purlin(float(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4)))
    # TR 500x200x4.5 / 500x200x4.5
    m = re.search(r"(?:TR)?\s*([\d.]+)X([\d.]+)X([\d.]+)", p)
    if m:
        return rect_tube(float(m.group(1)), float(m.group(2)), float(m.group(3)))
    # fracciones de pulgada: 5/8" -> diametro
    m = re.search(r"([\d.]+)/([\d.]+)\"", p)
    if m:
        d_in = float(m.group(1)) / float(m.group(2))
        return round_bar(d_in * 25.4)
    # pulgadas: 5/8 -> ...
    m = re.search(r"([\d.]+)\"", p)
    if m:
        return round_bar(float(m.group(1)) * 25.4)
    return None


def build_section_row(name: str, props: Dict[str, float], material: str = "A36") -> str:
    """Genera la linea de tabla FRAME SECTION PROPERTIES para una seccion General."""
    f = lambda v: f"{v:.6g}"  # noqa: E731
    return (
        f"   SectionName={name}   Material={material}   Shape=General"
        f"   Area={f(props['Area'])}   TorsConst={f(props['TorsConst'])}"
        f"   I33={f(props['I33'])}   I22={f(props['I22'])}"
        f"   AS2={f(props['AS2'])}   AS3={f(props['AS3'])}"
        f"   S33={f(props['S33'])}   S22={f(props['S22'])}"
        f"   Z33={f(props['Z33'])}   Z22={f(props['Z22'])}"
        f"   R33={f(props['R33'])}   R22={f(props['R22'])}   Color=Green"
    )


def _sap_num(v: float) -> str:
    """Formato numerico estilo exportacion de SAP2000 (repr, E mayuscula)."""
    s = repr(float(v))
    if "e" in s:
        mant, exp = s.split("e")
        s = f"{mant}E{int(exp)}"
    return s


def box_section_fields(h: float, b: float, t: float) -> Dict[str, float]:
    """Campos SAP para tubo rectangular hueco (Shape=Box/Tube). h=t3 alto, b=t2 ancho, t espesor [m]."""
    A = h * b - (h - 2 * t) * (b - 2 * t)
    Am = (h - t) * (b - t)
    P = 2 * ((h - t) + (b - t))
    I33 = (b * h ** 3 - (b - 2 * t) * (h - 2 * t) ** 3) / 12
    I22 = (h * b ** 3 - (h - 2 * t) * (b - 2 * t) ** 3) / 12
    S33 = 2 * I33 / h
    S22 = 2 * I22 / b
    Z33 = (b * h * h - (b - 2 * t) * (h - 2 * t) ** 2) / 4
    Z22 = (h * b * b - (h - 2 * t) * (b - 2 * t) ** 2) / 4
    return {
        "Shape": "Box/Tube", "t3": h, "t2": b, "tf": t, "tw": t, "FilletRadius": 0.0,
        "Area": A, "TorsConst": 4 * Am * Am * t / P,
        "I33": I33, "I22": I22, "I23": 0.0,
        "AS2": 2 * h * t, "AS3": 2 * b * t,
        "S33Top": S33, "S33Bot": S33, "S22Left": S22, "S22Right": S22,
        "Z33": Z33, "Z22": Z22, "R33": math.sqrt(I33 / A), "R22": math.sqrt(I22 / A),
        "CGOffset3": 0.0, "CGOffset2": 0.0, "EccV2": 0.0, "EccV3": 0.0, "Cw": 0.0,
    }


def circle_section_fields(d: float) -> Dict[str, float]:
    """Campos SAP para seccion circular maciza (Shape=Circle). d = diametro [m]."""
    A = math.pi * d * d / 4
    I = math.pi * d ** 4 / 64
    S = math.pi * d ** 3 / 32
    return {
        "Shape": "Circle", "t3": d,
        "Area": A, "TorsConst": math.pi * d ** 4 / 32,
        "I33": I, "I22": I, "I23": 0.0,
        "AS2": 0.9 * A, "AS3": 0.9 * A,
        "S33Top": S, "S33Bot": S, "S22Left": S, "S22Right": S,
        "Z33": d ** 3 / 6, "Z22": d ** 3 / 6,
        "R33": d / 4, "R22": d / 4,
        "CGOffset3": 0.0, "CGOffset2": 0.0, "EccV2": 0.0, "EccV3": 0.0, "Cw": 0.0,
    }


def build_param_section_row(name: str, fields: Dict[str, float], material: str,
                            color: str = "Green", total_length: float = 0.0,
                            notes: str = "") -> str:
    """Fila FRAME SECTION PROPERTIES para una seccion parametrica v27.1.

    Replica el formato de exportacion de SAP2000 v27.1 (ver COBERTURA_V8_A500.s2k).
    Unidades: Tonf, m. total_length -> TotalWt/TotalMass por unidad de peso/masa.
    """
    parts = [f"SectionName={name}", f"Material={material}", f"Shape={fields['Shape']}"]
    for key in ("t3", "t2", "tf", "tw", "FilletRadius"):
        if key in fields:
            parts.append(f"{key}={_sap_num(fields[key])}")
    for key in ("Area", "TorsConst", "I33", "I22", "I23", "AS2", "AS3",
                "S33Top", "S33Bot", "S22Left", "S22Right", "Z33", "Z22", "R33", "R22",
                "CGOffset3", "CGOffset2", "EccV2", "EccV3", "Cw"):
        parts.append(f"{key}={_sap_num(fields[key])}")
    A = fields["Area"]
    parts += [
        "ConcCol=No", "ConcBeam=No", f"Color={color}",
        f"TotalWt={_sap_num(7.85 * A * total_length)}",
        f"TotalMass={_sap_num(0.8004772 * A * total_length)}",
        "FromFile=No", "AMod=1", "A2Mod=1", "A3Mod=1", "JMod=1",
        "I2Mod=1", "I3Mod=1", "MMod=1", "WMod=1",
        f"GUID={uuid.uuid4()}",
    ]
    if notes:
        parts.append(f"Notes=\"{notes}\"")
    return "   " + "   ".join(parts)
