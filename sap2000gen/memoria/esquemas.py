"""Generacion de figuras esquematicas (PNG) para la memoria de calculo.

Estas imagenes se dibujan a partir de los datos del modelo .s2k (geometria,
secciones, resultados) sin depender de capturas de SAP2000:

    * vista 3D extruida del modelo estructural (barras como solidos con la
      seccion real de cada perfil, renders de alta resolucion)
    * modos de vibracion (deformadas modales del analisis modal)
    * deformada para el caso de carga mas desfavorable
    * perfiles transversales realistas, uno por seccion, con cotas

Para el modelo 3D y la deformada/modos se usa trimesh + pyrender (render
Offscreen de alta calidad); los perfiles se dibujan con matplotlib.
"""

from __future__ import annotations

import math
import os
from typing import Dict, List, Optional, Tuple

import numpy as np

from .model_data import ModelData, Section
from . import results as res

# ---------------------------------------------------------------- helpers

_AZUL = "#1F497D"
_AZUL2 = "#2E75B6"
_ROJO = "#C00000"
_VERDE = "#007030"
_GRIS = "#595959"
_FONDO = "#FFFFFF"

_CINTA = None  # cache del colormap


def _paleta(n: int) -> List[Tuple[float, float, float]]:
    """n colores RGB (0-1) contrastados para las secciones."""
    global _CINTA
    import matplotlib.pyplot as plt
    if _CINTA is None:
        _CINTA = plt.get_cmap("tab20")
    return [_CINTA(i / max(n, 1))[:3] for i in range(n)]


def _guardar(fig, path: str, dpi: int = 150) -> None:
    fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor=_FONDO)
    import matplotlib.pyplot as plt
    plt.close(fig)


def _cota(ax, x1, y1, x2, y2, texto: str, offset: float = 0.0,
          color: str = _GRIS, lw: float = 0.9, fs: float = 9.0) -> None:
    """Dibuja una linea de cota entre dos puntos con su texto."""
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="<->", color=color, lw=lw,
                                mutation_scale=10))
    ax.text((x1 + x2) / 2 + offset, (y1 + y2) / 2 + offset, texto,
            ha="center", va="center", fontsize=fs, color=color)


# ------------------------------------------------------------ modelo 3D

def _radio_visual(sec: Section, ext_mm: float) -> float:
    """Radio visual (mm) del tubo de una barra para el modelo 3D.

    Las secciones reales (16-500 mm) son imperceptibles sobre luces de
    ~30 m, asi que se usa un radio visual modesto y uniforme, con una
    variacion suave segun la seccion (ley de potencia) para no convertir
    las barras en cajas gigantes que se superponen. Referencia ~0.4% de
    la mayor dimension del modelo, rango [0.5x, 2.0x].
    """
    base = 0.004 * ext_mm
    dmin = _dim_menor(sec)
    if not dmin or dmin <= 0:
        return base
    f = (dmin / 100.0) ** 0.4
    return max(base * 0.5, min(base * 2.0, base * f))


def _dim_menor(sec: Section) -> float:
    """Menor dimension transversal de la seccion, en mm."""
    t2 = (sec.t2 or 0) * 1000
    t3 = (sec.t3 or 0) * 1000
    if t2 <= 0 or t3 <= 0:
        return t3 or t2
    return min(t2, t3)


def _sombra_barra(sec: Section, radio_mm: float = 100.0) -> Optional["trimesh.Trimesh"]:
    """Malla cilindrica (tubo) de la barra, longitud 1 m.

    `radio_mm` es el radio visual en mm. Se usa un cilindro limpio con
    suaves normales (smooth shading) para el aspecto profesional de
    modelo de pórticos (SAP2000/ETABS).
    """
    import trimesh
    if not radio_mm or radio_mm <= 0:
        return None
    try:
        return trimesh.creation.cylinder(radius=float(radio_mm), height=1000,
                                         sections=24)
    except Exception:
        return None


def _transformar_barra(mesh, p1, p2) -> "trimesh.Trimesh":
    """Orienta la barra (eje z local) desde p1 hacia p2, unidades en mm."""
    import trimesh
    import numpy as _np
    p1 = _np.array(p1, dtype=float)
    p2 = _np.array(p2, dtype=float)
    v = p2 - p1
    L = float(_np.linalg.norm(v))
    if L <= 1e-9:
        return None
    unit = v / L
    z = _np.array([0.0, 0.0, 1.0])
    if abs(float(_np.dot(unit, z))) > 0.9999:
        rot = _np.eye(3)
    else:
        axis = _np.cross(z, unit)
        ang = math.acos(max(-1.0, min(1.0, float(_np.dot(unit, z)))))
        K = _np.array([[0, -axis[2], axis[1]],
                       [axis[2], 0, -axis[0]],
                       [-axis[1], axis[0], 0]])
        rot = _np.eye(3) + math.sin(ang) * K + (1 - math.cos(ang)) * (K @ K)
    m = mesh.copy()
    m.apply_scale(L)
    m.apply_transform(_np.eye(4))
    # reconstruir: rotar + trasladar
    verts = m.vertices
    verts = verts @ rot.T
    verts = verts + (p1 * 1000)
    m.vertices = verts
    return m


def _escena_render(mallas_originales, mallas_deformadas, dpi=600,
                   elev=22.0, azim=-62.0, proj="ortho"):
    """Renderiza una lista de mallas trimesh como figura 3D (PyVista/VTK).

    Devuelve una imagen PIL RGB. `mallas_originales` y `mallas_deformadas`
    son listas de (mesh_trimesh, color_rgb_float) en unidades mm. La escena
    se centra en el centroide del modelo y se encuadra con la camara de VTK
    (z-buffer real, iluminacion PBR, antialiasing). Usa PyVista offscreen.
    """
    import trimesh
    import pyvista as pv
    from PIL import Image as PILImage

    if not (mallas_originales or mallas_deformadas):
        return None

    total = trimesh.util.concatenate(
        [m for m, _ in mallas_originales] +
        [m for m, _ in mallas_deformadas])
    centro = total.vertices.mean(axis=0)
    dim = (total.vertices.max(axis=0) - total.vertices.min(axis=0)).max()
    if dim <= 0:
        return None

    lado = int(5 * dpi)
    pl = pv.Plotter(off_screen=True, window_size=(lado, lado))
    pl.set_background("white")

    def _pv(mesh):
        faces = np.column_stack(
            [np.full(len(mesh.faces), 3, dtype=np.int64), mesh.faces]).ravel()
        return pv.PolyData(mesh.vertices.astype(float), faces)

    for m, c in mallas_originales + mallas_deformadas:
        pm = _pv(m)
        if pm.n_points == 0:
            continue
        pl.add_mesh(pm, color=tuple(c[:3]), smooth_shading=True, pbr=True,
                    metallic=0.05, roughness=0.55, specular=0.2,
                    show_edges=False)

    az = math.radians(azim)
    el = math.radians(elev)
    r = 1.8 * dim
    eye = (centro[0] + r * math.cos(el) * math.cos(az),
           centro[1] + r * math.cos(el) * math.sin(az),
           centro[2] + r * math.sin(el))
    pl.camera_position = [eye, tuple(centro), (0, 0, 1)]
    if proj == "ortho":
        pl.enable_parallel_projection()
    pl.reset_camera()
    img = pl.screenshot(return_img=True)
    pl.close()
    return _recortar_contenido(PILImage.fromarray(img), margen=30)


def _recortar_contenido(img, margen: int = 30):
    """Recorta el borde blanco sobrante de una imagen renderizada."""
    from PIL import Image as PILImage
    if img is None:
        return None
    a = np.asarray(img.convert("RGB"))
    fondo = np.all(a > 245, axis=2)
    if fondo.all():
        return img
    ys, xs = np.where(~fondo)
    x0, x1 = max(0, int(xs.min()) - margen), min(a.shape[1], int(xs.max()) + margen)
    y0, y1 = max(0, int(ys.min()) - margen), min(a.shape[0], int(ys.max()) + margen)
    return img.crop((x0, y0, x1, y1))


def _dibujar_escena(ax, mallas_originales, mallas_deformadas,
                    elev=22.0, azim=-62.0, proj="ortho") -> None:
    """Dibuja la escena 3D (Poly3DCollection) sobre un axes ya creado."""
    import trimesh
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    total = trimesh.util.concatenate(
        [m for m, _ in mallas_originales] +
        [m for m, _ in mallas_deformadas]) if (
            mallas_originales or mallas_deformadas) else None
    if total is None:
        return

    centro = total.vertices.mean(axis=0)
    dim = (total.vertices.max(axis=0) - total.vertices.min(axis=0)).max()
    escala = 2.0 / dim if dim > 0 else 1.0

    def _normal(m):
        m = m.copy()
        m.vertices = (m.vertices - centro) * escala
        return m

    # luz direccional desde arriba-izquierda (para sombreado lambert)
    L = np.array([0.45, -0.35, 0.82])
    L = L / np.linalg.norm(L)

    def _sombra(cara, color):
        """Devuelve (vertices, color_sombreado_rgb_0_255)."""
        p = np.asarray(cara)
        v = p[1] - p[0]
        w = p[2] - p[0]
        n = np.cross(v, w)
        n = n / (np.linalg.norm(n) + 1e-12)
        dif = max(0.0, float(np.dot(n, L)))
        amb = 0.38
        fac = amb + (1.0 - amb) * dif
        rgb = tuple(int(max(0.0, min(255.0, x * 255.0 * fac)))
                    for x in color[:3])
        return [tuple(x) for x in p], rgb

    todos_faces: List[List[Tuple[float, float, float]]] = []
    todos_colores: List[Tuple[int, int, int]] = []
    for m, c in mallas_originales + mallas_deformadas:
        m = _normal(m)
        if not len(m.faces):
            continue
        for f in m.faces:
            cara, col = _sombra(m.vertices[f], c)
            todos_faces.append(cara)
            todos_colores.append(col)

    pc = Poly3DCollection(todos_faces, facecolors=todos_colores,
                          edgecolors=todos_colores, linewidths=0.1,
                          zsort="average")
    ax.add_collection3d(pc)

    # encuadre ajustado a la caja real del modelo
    v = (total.vertices - centro) * escala
    mn = v.min(axis=0)
    mx = v.max(axis=0)
    rangos = (mx - mn)
    rango = rangos.max()
    pad = rango * 0.10
    ax.set_xlim(mn[0] - pad, mx[0] + pad)
    ax.set_ylim(mn[1] - pad, mx[1] + pad)
    ax.set_zlim(mn[2] - pad, mx[2] + pad)
    ax.set_box_aspect((rangos + 2 * pad) / rango)
    ax.set_axis_off()
    ax.set_proj_type(proj)
    ax.view_init(elev=elev, azim=azim)


def _figura_modelo_3d(md: ModelData, path: str,
                      dpi: int = 600) -> Optional[str]:
    """Vista 3D del modelo en estilo pórtico (tubos limpios).

    Cada barra se representa como un tubo cilindrico con radio visual
    modesto y uniforme, coloreado por sección (estilo SAP2000). Los
    apoyos se marcan con conos rojos.
    """
    import trimesh
    from PIL import Image as PILImage

    if not md.frames or not md.joints:
        return None

    ext_mm = max((m - n) for n, m in zip(md.min_xyz, md.max_xyz)) * 1000 or 1.0
    secs = sorted(md.frames_per_section, key=lambda s: -md.frames_per_section[s])
    colores = _paleta(len(secs))
    color_sec = {s: colores[i] for i, s in enumerate(secs)}

    mallas: Dict[str, Optional[trimesh.Trimesh]] = {}
    for s in secs:
        sec = md.sections.get(s)
        if sec is not None:
            mallas[s] = _sombra_barra(sec, _radio_visual(sec, ext_mm))

    originales: List[Tuple[trimesh.Trimesh, Tuple[float, float, float]]] = []
    for fid, (i, j) in md.frames.items():
        p1, p2 = md.joints.get(i), md.joints.get(j)
        if p1 is None or p2 is None:
            continue
        sec = md.frame_section.get(fid)
        mesh = mallas.get(sec)
        if mesh is None:
            continue
        tr = _transformar_barra(mesh, p1, p2)
        if tr is None:
            continue
        originales.append((tr, color_sec.get(sec, (0.5, 0.5, 0.5))))

    if md.restrained_joints:
        cono = trimesh.creation.cone(radius=150, height=450, sections=24)
        for j in md.restrained_joints:
            p = md.joints.get(j)
            if p is None:
                continue
            tr = cono.copy()
            tr.vertices = tr.vertices + np.array(p) * 1000
            originales.append((tr, (0.80, 0.10, 0.10)))

    img = _escena_render(originales, [], dpi=dpi)
    if img is None:
        return None
    img.save(path, dpi=(dpi, dpi))
    return path


# ------------------------------------------------------------ modos y deformada

def _deformada_malla(md: ModelData, d: Dict[int, Tuple[float, float, float]],
                     escala: float, color: Tuple[float, float, float],
                     lw_mm: float = 30.0) -> List["trimesh.Trimesh"]:
    """Crea las barras deformadas como cilindros delgados entre puntos."""
    import trimesh
    out = []
    cil = trimesh.creation.cylinder(radius=lw_mm / 2, height=1, sections=12)
    for fid, (i, j) in md.frames.items():
        p1, p2 = md.joints.get(i), md.joints.get(j)
        if p1 is None or p2 is None:
            continue
        q1 = tuple(p1[k] + (d.get(i, (0, 0, 0))[k] or 0) * escala
                   for k in range(3)) if d.get(i) else p1
        q2 = tuple(p2[k] + (d.get(j, (0, 0, 0))[k] or 0) * escala
                   for k in range(3)) if d.get(j) else p2
        tr = _transformar_barra(cil, q1, q2)
        if tr is None:
            continue
        tr.visual.vertex_colors = np.full((len(tr.vertices), 4), 255, dtype=np.uint8)
        out.append(tr)
    return out


def _figura_deformada(md: ModelData, r: res.ResultsData,
                      path: str, dpi: int = 600) -> Optional[str]:
    """Superpone la deformada (amplificada) de un caso sobre el modelo 3D."""
    import trimesh

    if r is None or r.displacements is None or not md.frames:
        return None
    df = r.displacements
    cx = res._pick(df, "UX", "U1")
    cy = res._pick(df, "UY", "U2")
    cz = res._pick(df, "UZ", "U3")
    cc = res._pick(df, "OutputCase", "Case")
    if not (cx and cy and cz and cc):
        return None
    mejor = res.max_displacements(r, top=1)
    if not mejor:
        return None
    caso = mejor[0]["caso"]
    sub = df[df[cc].astype(str) == caso].copy()
    if sub.empty:
        return None
    d: Dict[int, Tuple[float, float, float]] = {}
    for row in sub.itertuples(index=False):
        try:
            j = int(float(row.__getattribute__("Joint")))
        except (ValueError, TypeError, AttributeError):
            continue
        u1 = row.__getattribute__(cx)
        u2 = row.__getattribute__(cy)
        u3 = row.__getattribute__(cz)
        if u1 is None or u2 is None or u3 is None:
            continue
        try:
            vals = (float(u1), float(u2), float(u3))
        except (ValueError, TypeError):
            continue
        if all(math.isfinite(v) for v in vals):
            d[j] = vals
    if not d:
        return None

    desp_max = max(math.hypot(u1, u2, u3) for u1, u2, u3 in d.values()) or 1e-9
    dim = max((m - n) for n, m in zip(md.min_xyz, md.max_xyz)) or 1.0
    escala = dim * 0.06 / desp_max
    ext_mm = dim * 1000 or 1.0

    secs = sorted(md.frames_per_section, key=lambda s: -md.frames_per_section[s])
    colores = _paleta(len(secs))
    color_sec = {s: colores[i] for i, s in enumerate(secs)}

    mallas: Dict[str, Optional[trimesh.Trimesh]] = {}
    for s in secs:
        sec = md.sections.get(s)
        if sec is not None:
            mallas[s] = _sombra_barra(sec, _radio_visual(sec, ext_mm))

    originales: List[Tuple[trimesh.Trimesh, Tuple[float, float, float]]] = []
    for fid, (i, j) in md.frames.items():
        p1, p2 = md.joints.get(i), md.joints.get(j)
        if p1 is None or p2 is None:
            continue
        mesh = mallas.get(md.frame_section.get(fid))
        if mesh is None:
            continue
        tr = _transformar_barra(mesh, p1, p2)
        if tr is None:
            continue
        originales.append((tr, (0.75, 0.78, 0.83)))

    deformadas: List[Tuple[trimesh.Trimesh, Tuple[float, float, float]]] = []
    for tr in _deformada_malla(md, d, escala, (1.0, 0.0, 0.0),
                               lw_mm=2 * _radio_visual(
                                   next(iter(md.sections.values())), ext_mm)):
        deformadas.append((tr, (0.88, 0.13, 0.13)))

    img = _escena_render(originales, deformadas, dpi=dpi)
    if img is None:
        return None
    img.save(path, dpi=(dpi, dpi))
    return path


def _clasificar_modo(mp) -> str:
    """Clasifica un modo segun la masa participante (UX/UY/UZ)."""
    ux = float(mp.get("UX") or 0)
    uy = float(mp.get("UY") or 0)
    uz = float(mp.get("UZ") or 0)
    m = max(ux, uy, uz)
    if m < 0.01:
        return "Rotación / Torsión"
    if m == ux:
        return "Traslación X (U1)"
    if m == uy:
        return "Traslación Y (U2)"
    return "Vertical (U3)"


def _figura_modo(md: ModelData, r: res.ResultsData, modo: int,
                 path: str, dpi: int = 400) -> Optional[str]:
    """Vista 3D grande de un solo modo de vibración.

    Dibuja el modelo original en gris junto con la deformada (amplificada)
    en color. La figura incluye el número de modo, su periodo y el tipo de
    movimiento (traslación X/Y o rotación) según las masas participativas.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image

    if r is None or r.displacements is None or not md.frames:
        return None
    formas = res.modal_mode_shapes(r)
    if not formas or modo not in formas:
        return None

    g = formas[modo]
    d: Dict[int, Tuple[float, float, float]] = {}
    for row in g.itertuples(index=False):
        try:
            j = int(float(row.__getattribute__("Joint")))
        except (ValueError, TypeError, AttributeError):
            continue
        u1 = row.__getattribute__("U1")
        u2 = row.__getattribute__("U2")
        u3 = row.__getattribute__("U3")
        if u1 is None or u2 is None or u3 is None:
            continue
        try:
            vals = (float(u1), float(u2), float(u3))
        except (ValueError, TypeError):
            continue
        if all(math.isfinite(v) for v in vals):
            d[j] = vals
    if not d:
        return None
    desp = max((math.hypot(*d[j]) for j in d), default=1e-9)
    dim = max((m - n) for n, m in zip(md.min_xyz, md.max_xyz)) or 1.0
    escala = dim * 0.12 / desp if desp > 1e-12 else 0.0
    ext_mm = dim * 1000 or 1.0

    secs = sorted(md.frames_per_section, key=lambda s: -md.frames_per_section[s])
    mallas: Dict[str, Optional[trimesh.Trimesh]] = {}
    for s in secs:
        sec = md.sections.get(s)
        if sec is not None:
            mallas[s] = _sombra_barra(sec, _radio_visual(sec, ext_mm) * 0.55)

    originales: List[Tuple[trimesh.Trimesh, Tuple[float, float, float]]] = []
    for fid, (i, j) in md.frames.items():
        p1, p2 = md.joints.get(i), md.joints.get(j)
        if p1 is None or p2 is None:
            continue
        mesh = mallas.get(md.frame_section.get(fid))
        if mesh is None:
            continue
        tr = _transformar_barra(mesh, p1, p2)
        if tr is None:
            continue
        originales.append((tr, (0.72, 0.74, 0.78)))
    deformadas = [(tr, (0.10, 0.40, 0.85))
                  for tr in _deformada_malla(md, d, escala,
                                             (0.0, 0.4, 0.8), lw_mm=70)]

    per = None
    clas = ""
    if r.modal is not None and "StepNum" in r.modal.columns:
        mp = r.modal[r.modal["StepNum"].astype(float).round() == modo]
        if len(mp):
            fila = mp.iloc[0]
            per = float(fila.get("Period", 0) or 0)
            clas = _clasificar_modo(fila)

    img = _escena_render(originales, deformadas, dpi=dpi, proj="ortho")
    if img is None:
        return None

    fig = plt.figure(figsize=(7.5, 7.0), dpi=dpi)
    fig.patch.set_facecolor("white")
    ax = fig.add_subplot(111)
    ax.imshow(img)
    ax.axis("off")

    tit = f"Modo {modo}"
    if per:
        tit += f"  —  T = {per:.3f} s"
    fig.suptitle(tit, fontsize=17, color=_AZUL, y=0.96)
    if clas:
        fig.text(0.5, 0.92, clas, ha="center", fontsize=12, color=_GRIS)

    fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor=_FONDO)
    plt.close(fig)
    img = _recortar_contenido(Image.open(path).convert("RGB"), margen=40)
    if img is not None:
        img.save(path, dpi=(dpi, dpi))
    return path


def _figura_modos(md: ModelData, r: res.ResultsData,
                  path: str, n_modos: int = 3,
                  dpi: int = 400) -> Optional[str]:
    """Tira horizontal con las deformadas de los modos principales.

    Por defecto los primeros 3 modos: dos traslaciones (X e Y) y un modo
    rotacional, identificados por su masa participativa. Cada panel se
    dibuja en un axes 3D propio con el sombreado compartido.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if r is None or r.displacements is None or not md.frames:
        return None
    formas = res.modal_mode_shapes(r)
    if not formas:
        return None

    modos = sorted(formas.keys())[:n_modos]
    ext_mm = max((m - n) for n, m in zip(md.min_xyz, md.max_xyz)) * 1000 or 1.0
    secs = sorted(md.frames_per_section, key=lambda s: -md.frames_per_section[s])
    colores = _paleta(len(secs))
    color_sec = {s: colores[i] for i, s in enumerate(secs)}
    mallas: Dict[str, Optional[trimesh.Trimesh]] = {}
    for s in secs:
        sec = md.sections.get(s)
        if sec is not None:
            mallas[s] = _sombra_barra(sec, _radio_visual(sec, ext_mm) * 0.55)

    def _modo_escena(ax, modo: int):
        g = formas[modo]
        d: Dict[int, Tuple[float, float, float]] = {}
        for row in g.itertuples(index=False):
            try:
                j = int(float(row.__getattribute__("Joint")))
            except (ValueError, TypeError, AttributeError):
                continue
            u1 = row.__getattribute__("U1")
            u2 = row.__getattribute__("U2")
            u3 = row.__getattribute__("U3")
            if u1 is None or u2 is None or u3 is None:
                continue
            try:
                vals = (float(u1), float(u2), float(u3))
            except (ValueError, TypeError):
                continue
            if all(math.isfinite(v) for v in vals):
                d[j] = vals
        desp = max((math.hypot(*d[j]) for j in d), default=1e-9)
        dim = max((m - n) for n, m in zip(md.min_xyz, md.max_xyz)) or 1.0
        escala = dim * 0.12 / desp if desp > 1e-12 else 0.0

        originales: List[Tuple[trimesh.Trimesh, Tuple[float, float, float]]] = []
        for fid, (i, j) in md.frames.items():
            p1, p2 = md.joints.get(i), md.joints.get(j)
            if p1 is None or p2 is None:
                continue
            mesh = mallas.get(md.frame_section.get(fid))
            if mesh is None:
                continue
            tr = _transformar_barra(mesh, p1, p2)
            if tr is None:
                continue
            originales.append((tr, (0.72, 0.74, 0.78)))
        deformadas = [(tr, (0.10, 0.40, 0.85))
                      for tr in _deformada_malla(md, d, escala,
                                                 (0.0, 0.4, 0.8), lw_mm=70)]
        _dibujar_escena(ax, originales, deformadas, proj="ortho")

    fig, axes = plt.subplots(1, len(modos),
                             figsize=(5.4 * len(modos), 5.4), dpi=dpi)
    if len(modos) == 1:
        axes = [axes]
    fig.patch.set_facecolor("white")
    fig.suptitle("Modos de vibración de la cobertura", fontsize=16,
                 color=_AZUL, y=0.97)

    for k, modo in enumerate(modos):
        ax = axes[k]
        ax.set_facecolor("white")
        try:
            _modo_escena(ax, modo)
        except Exception:
            ax.text(0.5, 0.5, "sin datos", ha="center", va="center",
                    transform=ax.transAxes)
        per = None
        clas = ""
        if r.modal is not None and "StepNum" in r.modal.columns:
            mp = r.modal[r.modal["StepNum"].astype(float).round() == modo]
            if len(mp):
                fila = mp.iloc[0]
                per = float(fila.get("Period", 0) or 0)
                clas = _clasificar_modo(fila)
        tit = f"Modo {modo}"
        if per:
            tit += f"  ·  T = {per:.3f} s"
        ax.set_title(tit, fontsize=15, color=_AZUL2, pad=8)
        if clas:
            ax.set_xlabel(clas, fontsize=11, color=_GRIS, labelpad=-18)

    fig.tight_layout(rect=[0, 0, 1, 0.93])
    _guardar(fig, path, dpi=dpi)
    return path


# ---------------------------------------------------------------- secciones

def _perfil_box(ax, sec: Section) -> None:
    """Perfil tubular HSS / Box a escala con cotas en mm (relleno claro)."""
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    ancho = sec.t2 * 1000
    alto = sec.t3 * 1000
    tw = sec.tw * 1000 if sec.tw else 0.0
    tf = sec.tf * 1000 if sec.tf else tw
    if ancho <= 0 or alto <= 0:
        return

    ax.add_patch(Rectangle((0, 0), ancho, alto, fill=False, lw=2.2,
                           edgecolor=_AZUL))
    if tw > 0 and tf > 0 and ancho - 2 * tw > 0 and alto - 2 * tf > 0:
        ax.add_patch(Rectangle((tw, tf), ancho - 2 * tw, alto - 2 * tf,
                               fill=True, facecolor="white", lw=1,
                               edgecolor=_GRIS))
        ax.add_patch(Rectangle((0, 0), ancho, alto, fill=False, lw=2.2,
                               edgecolor=_AZUL, zorder=5))
    # ejes de simetria
    ax.plot([0, ancho], [alto / 2, alto / 2], color=_GRIS, lw=0.6,
            linestyle=":")
    ax.plot([ancho / 2, ancho / 2], [0, alto], color=_GRIS, lw=0.6,
            linestyle=":")
    # cotas
    ax.text(ancho / 2, alto * 1.03, f"{alto:.0f}", ha="center",
            fontsize=10, color=_AZUL)
    ax.text(ancho * 1.03, alto / 2, f"{ancho:.0f}", va="center",
            fontsize=10, color=_AZUL, rotation=90)
    if tw > 0:
        ax.text(ancho / 2, alto * 1.10, f"e = {tw:.1f}", ha="center",
                fontsize=9, color=_GRIS)


def _perfil_circulo(ax, sec: Section) -> None:
    """Seccion circular (tensor) con diametro a escala."""
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle

    d = sec.t3 * 1000
    if d <= 0:
        return
    ax.add_patch(Circle((0, 0), d / 2, fill=False, lw=2.2, edgecolor=_AZUL))
    ax.add_patch(Circle((0, 0), d / 4, fill=False, lw=1, edgecolor=_GRIS,
                        linestyle="--"))
    ax.plot([-d / 2, d / 2], [0, 0], color=_GRIS, lw=0.6, linestyle=":")
    ax.plot([0, 0], [-d / 2, d / 2], color=_GRIS, lw=0.6, linestyle=":")
    ax.text(0, d * 0.42, f"Ø {d:.0f}", ha="center", fontsize=10, color=_AZUL)
    ax.set_xlim(-d * 0.75, d * 0.75)
    ax.set_ylim(-d * 0.75, d * 0.75)
    ax.set_aspect("equal")


def _perfil_generico(ax, sec: Section) -> None:
    from matplotlib.patches import Rectangle
    ancho = (sec.t2 or sec.t3) * 1000
    alto = (sec.t3 or sec.t2) * 1000
    ax.add_patch(Rectangle((0, 0), ancho, alto, fill=False, lw=2,
                           edgecolor=_AZUL))
    ax.text(ancho / 2, alto * 1.03, f"{alto:.0f}", ha="center",
            fontsize=10, color=_AZUL)
    ax.set_xlim(-ancho * 0.2, ancho * 1.2)
    ax.set_ylim(-alto * 0.2, alto * 1.25)


def _figura_perfiles(md: ModelData, path: str,
                     secciones: Optional[List[str]] = None,
                     dpi: int = 300) -> Optional[str]:
    """Perfil de UNA seccion por imagen (se llama una vez por seccion).

    Devuelve la ruta; cada perfil se genera individual para insertarlo
    uno por uno en la memoria.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if not md.sections:
        return None
    nombres = secciones or list(md.sections.keys())
    out = []
    for nombre in nombres:
        sec = md.sections.get(nombre)
        if sec is None:
            continue
        fig, ax = plt.subplots(figsize=(4.4, 3.4))
        if sec.shape.lower() in ("circle",):
            _perfil_circulo(ax, sec)
        elif sec.shape.lower() in ("box", "tube", "rectangular", "hss"):
            _perfil_box(ax, sec)
        else:
            _perfil_generico(ax, sec)
        ax.set_title(nombre, fontsize=11, color=_AZUL)
        ax.set_aspect("equal")
        ax.set_xticks([]); ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
        p = os.path.join(os.path.dirname(path), f"perfil_{os.path.basename(path)}")
        base, ext = os.path.splitext(path)
        p = f"{base}_{nombre.strip().replace(' ', '_')}{ext}"
        _guardar(fig, p, dpi=dpi)
        out.append(p)
    return out[0] if out else None


def figura_perfil(md: ModelData, nombre: str, path: str,
                  dpi: int = 300) -> Optional[str]:
    """Perfil de una sola seccion (para detalle)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    sec = md.sections.get(nombre)
    if sec is None:
        return None
    fig, ax = plt.subplots(figsize=(4.4, 3.4))
    if sec.shape.lower() in ("circle",):
        _perfil_circulo(ax, sec)
    elif sec.shape.lower() in ("box", "tube", "rectangular", "hss"):
        _perfil_box(ax, sec)
    else:
        _perfil_generico(ax, sec)
    ax.set_title(nombre, fontsize=11, color=_AZUL)
    ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    _guardar(fig, path, dpi=dpi)
    return path


# ---------------------------------------------------------------- orquestador

def generar_figuras(md: ModelData, r: Optional[res.ResultsData],
                    carpeta: str, solo_perfiles: bool = False) -> Dict[str, str]:
    """Genera las figuras en `carpeta` y devuelve {clave: ruta}.

    Cada figura se genera de forma independiente; si una falla, se omite
    (la memoria quedara con el placeholder de la figura).

    `solo_perfiles=True` evita generar cualquier render sintetico
    (modelo3d/deformada/modos y perfiles de seccion); las imagenes que se
    muestren en la memoria provienen del modelo Revit (vista 3D y planos).
    """
    os.makedirs(carpeta, exist_ok=True)
    out: Dict[str, str] = {}
    if solo_perfiles:
        return out
    jobs = {
        "modelo3d": lambda: _figura_modelo_3d(
            md, os.path.join(carpeta, "modelo3d.png")),
        "deformada": lambda: _figura_deformada(
            md, r, os.path.join(carpeta, "deformada.png")) if r else None,
        "modo1": lambda: _figura_modo(
            md, r, 1, os.path.join(carpeta, "modo1.png")) if r else None,
        "modo2": lambda: _figura_modo(
            md, r, 2, os.path.join(carpeta, "modo2.png")) if r else None,
        "modo3": lambda: _figura_modo(
            md, r, 3, os.path.join(carpeta, "modo3.png")) if r else None,
        "perfiles": lambda: _figura_perfiles(
            md, os.path.join(carpeta, "perfiles_master.png")),
    }
    for clave, fn in jobs.items():
        try:
            p = fn()
        except Exception:
            p = None
        if p and os.path.exists(p):
            out[clave] = p

    # perfiles individuales
    for nombre in md.sections:
        try:
            clave = f"perfil__{nombre.strip()}"
            _nombre_archivo = "".join(
                ch if ch not in '\\/:*?"<>|' else "_" for ch in nombre.strip())
            p = figura_perfil(md, nombre,
                              os.path.join(carpeta,
                                           f"perfil_{_nombre_archivo}.png"))
        except Exception:
            p = None
        if p and os.path.exists(p):
            out[clave] = p
    return out


# ------------------------------------------------------------ diagramas de resultados


def _nombre_figura(base: str, path: str) -> str:
    dirn, fn = os.path.split(path)
    stem, ext = os.path.splitext(fn)
    return os.path.join(dirn, f"{base}_{stem}{ext}")


def _figura_dc_ratios(md: ModelData, r: Optional[res.ResultsData],
                      path: str, dpi: int = 220) -> Optional[str]:
    """Barras horizontales D/C (Demand/Capacity) por seccion."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from .results import steel_ratios
    if r is None:
        return None
    _, per_sec = steel_ratios(r)
    if not per_sec:
        return None
    per_sec = {k: v for k, v in per_sec.items()}
    nombres = list(per_sec.keys())
    ratios = [per_sec[n] for n in nombres]
    idx = list(range(len(nombres)))
    idx.reverse()
    nombres = [nombres[i] for i in idx]
    ratios = [ratios[i] for i in idx]
    fig, ax = plt.subplots(figsize=(9.5, 4.8))
    colores = [_ROJO if v > 1.0 else (_VERDE if v <= 0.85 else "#ED7D31")
               for v in ratios]
    ax.barh(idx, ratios, color=colores, edgecolor="white", height=0.6)
    ax.axvline(1.0, color=_ROJO, lw=1.4, ls="--", label="Límite D/C = 1.0")
    ax.set_yticks(idx)
    ax.set_yticklabels(nombres, fontsize=8)
    ax.set_xlabel("Relación Demanda/Capacidad (D/C)", fontsize=10)
    ax.set_xlim(0, max(1.25, max(ratios) * 1.08))
    for i, v in zip(idx, ratios):
        ax.text(v + max(ratios) * 0.01, i, f"{v:.3f}", va="center", fontsize=8)
    ax.legend(fontsize=9, loc="lower right")
    ax.grid(axis="x", ls=":", alpha=0.5)
    ax.set_title("Relación Demanda/Capacidad (D/C) por sección",
                 fontsize=11, color=_AZUL)
    for spine in ax.spines.values():
        spine.set_color("#BFBFBF")
    _guardar(fig, path, dpi=dpi)
    return path


def _figura_envolvente_fuerzas(md: ModelData, r: Optional[res.ResultsData],
                               path: str, dpi: int = 220) -> Optional[str]:
    """Diagrama de barras de las fuerzas axiales P y momentos M3 por seccion."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from .results import envelope_frame_forces
    if r is None:
        return None
    env = envelope_frame_forces(r)
    if not env:
        return None
    nombres = list(env.keys())
    p = [env[n].get("P", 0) or 0 for n in nombres]
    m3 = [env[n].get("M3", 0) or 0 for n in nombres]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.5, 4.6))
    _pal = _paleta(len(nombres))
    for ax, vals, lab, unidad in ((a1, p, "P axial máxima", "kgf"),
                                  (a2, m3, "M3 flector máximo", "kgf·m")):
        ii = list(range(len(nombres)))
        ax.bar(ii, [v / 1000 for v in vals], color=_pal,
               edgecolor="white", width=0.6)
        ax.set_xticks(ii)
        ax.set_xticklabels(nombres, rotation=30, ha="right", fontsize=6.5)
        ax.set_ylabel(f"{lab} ({unidad}, miles)", fontsize=9)
        ax.set_title(lab, fontsize=10, color=_AZUL)
        ax.grid(axis="y", ls=":", alpha=0.5)
        for s, v in zip(ii, vals):
            ax.text(s, v / 1000, f"{v / 1000:.2f}", ha="center",
                    va="bottom", fontsize=6)
    fig.suptitle("Fuerzas internas envolventes por sección",
                 fontsize=11, color=_AZUL)
    for spine in (a1.spines.values() and a2.spines.values()):
        spine.set_color("#BFBFBF")
    _guardar(fig, path, dpi=dpi)
    return path


def _figura_reacciones(md: ModelData, r: Optional[res.ResultsData],
                       path: str, dpi: int = 220) -> Optional[str]:
    """Reacciones verticales F3 maximas por caso de carga (kgf)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from .results import max_reactions
    if r is None:
        return None
    reac = max_reactions(r, top=12)
    if not reac:
        return None
    nombres = [x["caso"] for x in reac]
    f3 = [x["F3"] for x in reac]
    idx = list(range(len(nombres)))
    idx.reverse()
    nombres = [nombres[i] for i in idx]
    f3 = [f3[i] for i in idx]
    fig, ax = plt.subplots(figsize=(9.5, 5.2))
    ax.barh(idx, [v / 1000 for v in f3], color=_AZUL2, edgecolor="white",
            height=0.6)
    ax.set_yticks(idx)
    ax.set_yticklabels(nombres, fontsize=7.5)
    ax.set_xlabel("Reacción vertical F3 (tf)", fontsize=10)
    ax.grid(axis="x", ls=":", alpha=0.5)
    for i, v in zip(idx, f3):
        ax.text(v / 1000, i, f"{v / 1000:.2f}", va="center", fontsize=7)
    ax.set_title("Reacciones verticales máximas en apoyos por caso",
                 fontsize=11, color=_AZUL)
    for spine in ax.spines.values():
        spine.set_color("#BFBFBF")
    _guardar(fig, path, dpi=dpi)
    return path


def _figura_desplazamientos(md: ModelData, r: Optional[res.ResultsData],
                            path: str, dpi: int = 220) -> Optional[str]:
    """Desplazamientos maximos totales por caso (mm)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from .results import max_displacements
    if r is None:
        return None
    desp = max_displacements(r, top=12)
    if not desp:
        return None
    nombres = [x["caso"] for x in desp]
    utot = [x["UTOT"] * 1000 for x in desp]
    idx = list(range(len(nombres)))
    idx.reverse()
    nombres = [nombres[i] for i in idx]
    utot = [utot[i] for i in idx]
    fig, ax = plt.subplots(figsize=(9.5, 5.2))
    ax.barh(idx, utot, color=_VERDE, edgecolor="white", height=0.6)
    ax.set_yticks(idx)
    ax.set_yticklabels(nombres, fontsize=7.5)
    ax.set_xlabel("Desplazamiento máximo total (mm)", fontsize=10)
    ax.grid(axis="x", ls=":", alpha=0.5)
    for i, v in zip(idx, utot):
        ax.text(v, i, f"{v:.1f}", va="center", fontsize=7)
    ax.set_title("Desplazamientos máximos por caso de carga",
                 fontsize=11, color=_AZUL)
    for spine in ax.spines.values():
        spine.set_color("#BFBFBF")
    _guardar(fig, path, dpi=dpi)
    return path


def generar_diagramas(md: ModelData, r: Optional[res.ResultsData],
                      carpeta: str) -> Dict[str, str]:
    """Genera diagramas tecnicos de resultados (barras) en `carpeta`."""
    os.makedirs(carpeta, exist_ok=True)
    out: Dict[str, str] = {}
    jobs = {
        "diag_dc": _figura_dc_ratios,
        "diag_fuerzas": _figura_envolvente_fuerzas,
        "diag_reacciones": _figura_reacciones,
        "diag_desplazamientos": _figura_desplazamientos,
    }
    for clave, fn in jobs.items():
        try:
            p = fn(md, r, os.path.join(carpeta, f"{clave}.png"))
        except Exception:
            p = None
        if p and os.path.exists(p):
            out[clave] = p
    return out
