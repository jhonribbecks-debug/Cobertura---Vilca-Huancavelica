"""Construccion de modelo 3D de porticos metalicos a partir de la lectura
de la elevacion (IA de vision) + la geometria del plano.

Estructura (municipalidad de Vilca, E-06):
    - 6 porticos en ejes A-F, separados frame_spacing (6.06 m)
    - cada portico: 2 columnas (COL) de column_height (6.00 m) con una cercha
      de profundidad truss_depth (0.50 m) y luz truss_span
    - cercha: cuerda superior/inferior + diagonales (panel 1.47 m)
    - correas (COST) a nivel de cuerda superior entre porticos
    - arriostramiento en cruz (CSA5_8) entre porticos
"""

from __future__ import annotations

from typing import List

from .model import S2kModel, Joint, Frame


def build_truss_3d(template_path: str, output_path: str,
                   frame_spacing: float = 6.06,
                   n_frames: int = 6,
                   truss_span: float = 24.0,
                   column_height: float = 6.00,
                   truss_depth: float = 0.50,
                   panel: float = 1.47,
                   real_sections: dict | None = None) -> dict:
    """Genera un .s2k 3D de porticos con cercha.

    real_sections: opcional, mapa {nombre_seccion: designacion_de_perfil}
        p.ej. {"COL": "TR 500x200x4.5", "COST": "Z 240x80x20x2.0", "CSA5_8": "5/8\""}
        Se calculan las propiedades reales y se reemplazan las secciones de la plantilla.
    """
    from .s2kreader import parse_s2k
    from .s2kwriter import write_s2k

    model = parse_s2k(template_path)

    if real_sections:
        from .sections import profile_properties, build_section_row
        rows = {}
        for sname, profile in real_sections.items():
            props = profile_properties(profile)
            if props:
                rows[sname] = build_section_row(sname, props)
        if rows:
            model.set_real_sections(rows)

    frames_x = [0.0, truss_span]
    frame_ys = [i * frame_spacing for i in range(n_frames)]
    n_panels = max(1, int(round(truss_span / panel)))
    node_x = [truss_span * i / n_panels for i in range(n_panels + 1)]

    next_joint = 1
    joints_map = {}  # (frame_idx, x_idx, level) -> joint_id
    frames: List[Frame] = []

    # 1) nudos
    for fi, fy in enumerate(frame_ys):
        for xi, x in enumerate(node_x):
            for level, z in enumerate([0.0, column_height, column_height + truss_depth]):
                joints_map[(fi, xi, level)] = next_joint
                model.add_joint(Joint(next_joint, x, fy, z))
                next_joint += 1

    # 2) columnas (z 0 -> columna height)
    for fi in range(n_frames):
        for xi in [0, n_panels]:
            i = joints_map[(fi, xi, 0)]
            j = joints_map[(fi, xi, 1)]
            f = Frame(len(frames) + 1, i, j, "COL")
            f.releases = [False] * 6 + [False] * 6
            frames.append(f)

    # 3) cuerda inferior y superior de cada portico
    for fi in range(n_frames):
        for xi in range(n_panels):
            # cuerda inferior
            frames.append(Frame(len(frames) + 1,
                                joints_map[(fi, xi, 1)], joints_map[(fi, xi + 1, 1)], "CORD150"))
            # cuerda superior
            frames.append(Frame(len(frames) + 1,
                                joints_map[(fi, xi, 2)], joints_map[(fi, xi + 1, 2)], "ARCO"))

    # 4) diagonales de la cercha (zig-zag)
    for fi in range(n_frames):
        for xi in range(n_panels):
            if xi % 2 == 0:
                frames.append(Frame(len(frames) + 1,
                                    joints_map[(fi, xi, 1)], joints_map[(fi, xi + 1, 2)], "DIAG100"))
            else:
                frames.append(Frame(len(frames) + 1,
                                    joints_map[(fi, xi, 2)], joints_map[(fi, xi + 1, 1)], "DIAG100"))

    # 5) montantes verticales entre cuerdas
    for fi in range(n_frames):
        for xi in range(n_panels + 1):
            frames.append(Frame(len(frames) + 1,
                                joints_map[(fi, xi, 1)], joints_map[(fi, xi, 2)], "DIAG100"))

    # 6) correas a nivel de cuerda superior (entre porticos)
    for xi in range(n_panels + 1):
        for fi in range(n_frames - 1):
            frames.append(Frame(len(frames) + 1,
                                joints_map[(fi, xi, 2)], joints_map[(fi + 1, xi, 2)], "COST"))

    # 7) arriostramiento en cruz (cables) entre porticos, en 2 vanos centrales
    for xi in [n_panels // 4, n_panels // 2, 3 * n_panels // 4]:
        for fi in range(n_frames - 1):
            frames.append(Frame(len(frames) + 1,
                                joints_map[(fi, xi, 1)], joints_map[(fi + 1, xi + 1 if xi + 1 <= n_panels else n_panels, 1)], "CSA5_8"))
            frames.append(Frame(len(frames) + 1,
                                joints_map[(fi, xi + 1 if xi + 1 <= n_panels else n_panels, 1)], joints_map[(fi + 1, xi, 1)], "CSA5_8"))

    for f in frames:
        model.add_frame(f)

    # 8) apoyos empotrados en las bases
    for j in model.joints:
        if abs(j.z) < 1e-6:
            j.restraints = [True] * 6

    write_s2k(model, output_path)
    return {"output": output_path, "joints": len(model.joints),
            "frames": len(model.frames),
            "desc": f"{n_frames} porticos x {truss_span:.1f}m luz, col {column_height:.2f}m, cercha {truss_depth:.2f}m"}
