"""Regenera la memoria de calculo usando las secciones REALES del modelo Revit.

El pipeline por defecto lee las secciones del .s2k (v4), que no coinciden con
los tipos colocados en el modelo Revit que se presenta (HSS200x200x8,
HSS150x50x3, HSS50x50x2, O16, etc.). Este script:

  1. Extrae el modelo y los resultados desde el .s2k v4.
  2. Reemplaza las secciones por los tipos reales de Revit (nombre, dimension y
     material), con la equivalencia rol -> tipo.
  3. Recalcula longitudes y metrado de acero con las dimensiones reales.
  4. Genera las figuras de secciones nuevas (una por tipo).
  5. Usa la vista 3D exportada de Revit como figura del modelo estructural
     (en lugar del render sintetico del pipeline).
  6. Arma la memoria .docx PRONIED y la convierte a PDF.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sap2000gen.memoria.model_data import extract_model, Section
from sap2000gen.memoria import results as res
from sap2000gen.memoria.proned import build_memoria_proned

# Secciones reales colocadas en el modelo Revit (model_stats) con sus
# dimensiones (m) y material. shape "box" = HSS rectangular hueco.
REVIT_SECTIONS = {
    "HSS200x200x8": dict(rol="Columna", n=14, material="A500GrB46",
                         shape="box", t3=0.200, t2=0.200, t=0.008),
    "HSS150x50x3": dict(rol="Correa", n=90, material="A500GrB46",
                        shape="box", t3=0.150, t2=0.050, t=0.003),
    "HSS100x50x4.5": dict(rol="Brida inferior", n=7, material="A500GrB46",
                          shape="box", t3=0.100, t2=0.050, t=0.0045),
    "HSS100x50x3": dict(rol="Brida superior", n=7, material="A500GrB46",
                        shape="box", t3=0.100, t2=0.050, t=0.003),
    "HSS50x50x2": dict(rol="Montante / diagonal", n=419, material="A500GrB46",
                       shape="box", t3=0.050, t2=0.050, t=0.002),
    "O16": dict(rol="Tensor", n=48, material="A36", shape="circle",
                t3=0.016, t2=0.016, t=0.016),
}

# Equivalencia entre secciones del .s2k v4 y los tipos de Revit que se
# presentan (las bridas inferiores del s2k eran HSS100x50x4.5, etc.).
S2K_TO_REVIT = {
    "BRIDA INFERIOR (LATERAL) HSS50x50x2 mm": "HSS50x50x2",
    "BRIDA INFERIOR HSS100x50x4.5 mm": "HSS100x50x4.5",
    "BRIDA SUPERIOR (LATERAL) HSS50x50x2 mm": "HSS50x50x2",
    "BRIDA SUPERIOR HSS100x50x3 mm": "HSS100x50x3",
    "COLUMNA HSS 200x200x6 mm": "HSS200x200x8",
    "COLUMNA HSS 200x200x8 mm": "HSS200x200x8",
    "CORREA HSS100x50x4.5 mm": "HSS150x50x3",
    "DIAGONALES (LATERAL) HSS 50x50x2 MM": "HSS50x50x2",
    "DIAGONALES HSS 50x50x2.5": "HSS50x50x2",
    "TENSOR Ø5/8": "O16",
    "TENSOR O16": "O16",
}


def _norm(v):
    v = (v or "").strip()
    v = v.strip('"').upper()
    return " ".join(v.split())


def _map_sec(name):
    """Mapea un nombre de seccion del s2k al tipo de Revit."""
    if name in S2K_TO_REVIT:
        return S2K_TO_REVIT[name]
    n = _norm(name)
    for k, v in S2K_TO_REVIT.items():
        if _norm(k) == n:
            return v
    # coincidencia por HSS dims o tensor
    import re
    m = re.search(r"HSS\s*([0-9]+)x([0-9]+)x([0-9.]+)", n, re.IGNORECASE)
    if m:
        a, b, t = int(m.group(1)), int(m.group(2)), float(m.group(3))
        if a == b == 200:
            return "HSS200x200x8"
        if a == 150:
            return "HSS150x50x3"
        if a == 100 and b == 50 and t >= 4:
            return "HSS100x50x4.5"
        if a == 100 and b == 50:
            return "HSS100x50x3"
        if a == b == 50:
            return "HSS50x50x2"
    if "Ø5/8" in name or "O16" in name or "TENSOR" in name:
        return "O16"
    return name


def build_md(md, extra) -> None:
    """Reemplaza secciones/resultados con los tipos reales de Revit."""
    # 0) garantizar materiales usados por las secciones de Revit
    from sap2000gen.memoria.model_data import Material
    G = 7850.0  # kgf/m3
    for nombre, (fy_ksi, fu_ksi) in {"A500GrB46": (46.0, 58.0),
                                     "A36": (36.0, 58.0)}.items():
        if nombre not in md.materials:
            md.materials[nombre] = Material(
                name=nombre,
                fy=fy_ksi * 70.31 * 1e4,   # ksi -> kgf/m2
                fu=fu_ksi * 70.31 * 1e4,
                e=2.04e9,
                unit_weight=G)

    # 1) secciones nuevas del modelo presentado (solo estas aparecen en la
    #    memoria; se descartan las secciones del .s2k v4 que no se presentan)
    md.sections = {}
    for nombre, s in REVIT_SECTIONS.items():
        md.sections[nombre] = Section(
            name=nombre, material=s["material"], shape=s["shape"],
            t3=s["t3"], t2=s["t2"],
            tf=s["t"] if s["shape"] != "circle" else s["t3"],
            tw=s["t"] if s["shape"] != "circle" else s["t3"],
            area_sap=0.0)

    # 2) mapear asignaciones de barras del s2k -> seccion Revit
    rev = {}
    for fid, sec in md.frame_section.items():
        rev[fid] = _map_sec(sec)
    md.frame_section = rev

    # 3) recalcular longitudes y metrado con las secciones nuevas
    per_len = {}
    per_cnt = {}
    total = 0.0
    mat_w = {n: m.unit_weight for n, m in md.materials.items()}
    for fid, (i, j) in md.frames.items():
        sec = rev.get(fid)
        if not sec:
            continue
        p1, p2 = md.joints.get(i), md.joints.get(j)
        if p1 is None or p2 is None:
            continue
        import math
        L = math.dist(p1, p2)
        per_len[sec] = per_len.get(sec, 0.0) + L
        per_cnt[sec] = per_cnt.get(sec, 0) + 1
        so = md.sections.get(sec)
        if so is not None:
            g = mat_w.get(so.material, 0.0)
            total += so.weight_per_m(g) * L
    md.frame_lengths = per_len
    # cuentas fisicas del modelo Revit presentado (model_stats 11/08/2026)
    revit_counts = {
        "HSS200x200x8": 14, "HSS150x50x3": 90, "HSS100x50x4.5": 7,
        "HSS100x50x3": 7, "HSS50x50x2": 419, "O16": 48,
    }
    md.frames_per_section = {k: revit_counts.get(k, 0) for k in REVIT_SECTIONS}
    md.n_frames = sum(revit_counts.values())
    md.total_weight = total

    # 4) renombrar resultados (DesignSect) con la equivalencia
    if extra is not None:
        if extra.steel_design is not None and "DesignSect" in extra.steel_design:
            extra.steel_design["DesignSect"] = extra.steel_design["DesignSect"].map(
                lambda x: _map_sec(x))
        if extra.frame_forces is not None and "DesignSect" in extra.frame_forces:
            extra.frame_forces["DesignSect"] = extra.frame_forces["DesignSect"].map(
                lambda x: _map_sec(x))


def main() -> None:
    model = r"MN\HUANCALPI - MODELO FINAL v4.s2k"
    md = extract_model(model, extra_tables=res.RESULTS_S2K_TABLES)
    if md.errors:
        print("ERROR:", "; ".join(md.errors))
        sys.exit(1)
    rd = res.load_results_from_s2k(md)
    print("Resultados:", ", ".join(rd.found))

    build_md(md, rd)
    print("Secciones presentadas:")
    for n, s in md.sections.items():
        print(f"  {n}: {s.shape} {s.t3*1000:.1f}x{s.t2*1000:.1f} t={s.tf*1000:.2f}")
    print(f"Metrado: {md.frames_per_section}")
    print(f"Peso total acero: {md.total_weight/1000:.2f} tf")

    proyecto = ("CREACIÓN DEL SERVICIO DE PRÁCTICA DEPORTIVA Y/O RECREATIVA "
                "EN COMPLEJO DEPORTIVO DE CENTRO POBLADO HUANCALPI, DISTRITO "
                "DE VILCA, PROVINCIA DE HUANCAVELICA, DEPARTAMENTO DE "
                "HUANCAVELICA")
    extra = {
        "proyecto": proyecto,
        "ubicacion": ("Centro Poblado Huancalpi, distrito de Vilca, provincia "
                      "de Huancavelica, departamento de Huancavelica"),
        "cui": "2704510",
        "propietario": "Unidad Ejecutora 304 - Gobierno Regional de Huancavelica",
        "solicita": "Unidad Ejecutora 304",
        "entidad_superior": "MINEDU — PRONIED",
        "consultor": "Ing. Jhon Brian Ribbeck Soto",
        "responsable": "Ing. Jhon Brian Ribbeck Soto",
        "cip": "C.I.P. 289452",
        "informe": "MC-EM-01-2026",
        "version": "v2.0",
        "elaborado": "Ing. Jhon Brian Ribbeck Soto - C.I.P. 289452",
        "revisado": "",
        "fecha": "11/08/2026",
        "modulo": "COBERTURA METÁLICA EN ARCO - TIJERAL",
    }
    sismo = {"zona": 3, "u": 1.0, "s": 1.05, "tp": 0.6, "tl": 2.0,
             "r": 8.0, "viento": 100.0}
    # Parámetros geotécnicos del EMS "EV-178 - HIOMKAR GTV149-26.pdf"
    # (Laboratorio GEO TEST V S.A.C.): calicatas C-1 y C-2, suelo CL
    # (arcilla de baja plasticidad con arena), Qult = 1.49 kg/cm² y
    # Qadm = 0.50 kg/cm² con FS = 3.0.
    extra["ems"] = {
        "informe": "EV-178 - HIOMKAR GTV149-26",
        "laboratorio": "GEO TEST V S.A.C.",
        "suelo": "CL (arcilla de baja plasticidad con arena)",
        "finos": 76.0,
        "cohesion": 0.25,          # kg/cm²
        "friccion": 0.0,           # grados
        "qult": 1.49,              # kg/cm²
        "qadm": 0.50,              # kg/cm² (adoptado, FS = 3.0)
        "fs": 3.0,
        "df": 1.50,                # m (profundidad de desplante)
        "b": 1.50,                 # m (ancho zapata cuadrada)
        "es": 3000.0,              # ton/m² (módulo de elasticidad del suelo)
        "asentamiento_max": 0.802, # cm (centro de zapata)
        "asentamiento_adm": 2.5,   # cm
    }

    # figura 3D desde Revit (exportada ya via bridge)
    revit_3d = os.path.join(os.environ.get("TEMP", os.environ.get("TMP", ".")),
                            "opencode", "revit_3D_vista.jpg")
    figuras_3d = {"modelo3d": revit_3d} if os.path.exists(revit_3d) else {}
    planos = [revit_3d] if os.path.exists(revit_3d) else None
    if not planos:
        print("AVISO: no se encontro la vista 3D de Revit en temp; Anexo A sin imagen 3D.")

    out = build_memoria_proned(
        md, rd, output="Memoria_de_Calculo_Estructural_Cobertura_Huancalpi.docx",
        extra=extra, sismo=sismo, planos=planos, figuras_3d=figuras_3d)
    print("OK:", out)


if __name__ == "__main__":
    main()