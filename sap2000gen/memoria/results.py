"""Lectura de resultados de analisis exportados por SAP2000.

SAP2000 exporta tablas de resultados a Excel (.xlsx) o CSV. Cada tabla se
identifica por su nombre ("TABLE: Joint Displacements", "TABLE: Frame
Forces - Frames", "TABLE: Steel Design 1 - Summary Data - AISC 360-16",
"TABLE: Support Reactions", "TABLE: Modal Periods and Frequencies").

Este modulo localiza las hojas/columnas por nombre y devuelve resumenes
(listos para insertar en la memoria). Es tolerante: si una tabla no existe
devuelve DataFrames vacios y la memoria se genera con "pendiente".
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from .model_data import (_f, force_scale_for_units, join_continuations, kv)

TABLE_NAMES = {
    "displacements": ["joint displacement"],
    "frame_forces": ["frame forces"],
    "steel_design": ["steel design", "summary data"],
    "reactions": ["support reactions", "joint reactions"],
    "modal": ["modal period"],
}

_COLS = {
    "displacements": ["Text", "Joint", "OutputCase", "CaseType", "StepType",
                      "U1", "U2", "U3", "R1", "R2", "R3"],
    "frame_forces": ["Text", "Frame", "Station", "OutputCase", "CaseType",
                     "StepType", "P", "V2", "V3", "T", "M2", "M3"],
    "steel_design": ["Text", "Frame", "DesignSect", "DesignType", "Status",
                     "Ratio"],
    "reactions": ["Text", "Joint", "OutputCase", "CaseType", "StepType",
                  "F1", "F2", "F3", "M1", "M2", "M3"],
    "modal": ["OutputCase", "StepType", "StepNum", "Period", "Frequency",
              "CircFreq", "Eigenvalue", "UX", "UY", "UZ", "RX", "RY", "RZ"],
}


def _find_header_row(raw: pd.DataFrame, keywords: List[str]) -> int:
    """Devuelve el indice de la fila que contiene las columnas esperadas."""
    for i in range(min(len(raw), 25)):
        cells = [str(c).lower() for c in raw.iloc[i].tolist()]
        score = sum(1 for kw in keywords if any(kw in c for c in cells))
        if score >= 2:
            return i
    return -1


def _read_table(path: str, kind: str) -> Optional[pd.DataFrame]:
    keywords = _COLS[kind]
    lower_keys = [c.lower() for c in keywords[:6]]
    target = TABLE_NAMES[kind]

    if path.lower().endswith(".xlsx"):
        xl = pd.ExcelFile(path)
        best: Optional[pd.DataFrame] = None
        best_hits = 0
        for sheet in xl.sheet_names:
            sname = sheet.lower()
            if not any(t in sname for t in target):
                continue
            raw = pd.read_excel(xl, sheet_name=sheet, header=None)
            hr = _find_header_row(raw, lower_keys)
            if hr < 0:
                continue
            df = raw.iloc[hr + 1:].copy()
            df.columns = [str(c).strip() for c in raw.iloc[hr].tolist()]
            hits = sum(1 for c in df.columns if c in _COLS[kind])
            if hits > best_hits:
                best_hits, best = hits, df
        return best
    else:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(2000).lower()
        if not any(t in head for t in target):
            return None
        raw = pd.read_csv(path, header=None)
        hr = _find_header_row(raw, lower_keys)
        if hr < 0:
            return None
        df = raw.iloc[hr + 1:].copy()
        df.columns = [str(c).strip() for c in raw.iloc[hr].tolist()]
        return df


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    return pd.to_numeric(df[col], errors="coerce")


def _pick(df: pd.DataFrame, *cands: str) -> Optional[str]:
    """Devuelve el nombre real de la columna que coincide con un alias."""
    cols = {str(c).strip().lower(): c for c in df.columns}
    for c in cands:
        if c.lower() in cols:
            return cols[c.lower()]
    return None


@dataclass
class ResultsData:
    source: str = ""
    displacements: Optional[pd.DataFrame] = None
    frame_forces: Optional[pd.DataFrame] = None
    steel_design: Optional[pd.DataFrame] = None
    reactions: Optional[pd.DataFrame] = None
    modal: Optional[pd.DataFrame] = None
    found: List[str] = field(default_factory=list)

    def load(self, path: str) -> None:
        self.source = path
        for kind, attr in (("displacements", "displacements"),
                           ("frame_forces", "frame_forces"),
                           ("steel_design", "steel_design"),
                           ("reactions", "reactions"),
                           ("modal", "modal")):
            try:
                df = _read_table(path, kind)
            except Exception:
                df = None
            if df is not None and len(df):
                setattr(self, attr, df)
                self.found.append(kind)


# ------------------------------------------------------- resultados desde .s2k

# Tablas de resultados que SAP2000 puede incluir en la exportacion .s2k
RESULTS_S2K_TABLES = [
    "JOINT DISPLACEMENTS",
    "JOINT REACTIONS",
    "ELEMENT FORCES - FRAMES",
    "STEEL DESIGN 1 - SUMMARY DATA - AISC 360-16",
    "MODAL PERIODS AND FREQUENCIES",
    "MODAL PARTICIPATING MASS RATIOS",
]


def _find_table(tables: Dict[str, object], name: str) -> Optional[list]:
    """Busca la tabla cuyo nombre contiene `name`."""
    for key, rows in tables.items():
        if name.lower() in key.lower():
            return rows
    return None


def _s2k_to_df(lines: List[str], cols: List[str],
               force_scale: float = 1.0, scale_cols: set = ()) -> pd.DataFrame:
    """Convierte filas clave=valor del .s2k a un DataFrame con las columnas dadas.

    Las columnas numericas se convierten a float (multiplicando por
    `force_scale` las que esten en `scale_cols`); el resto se deja como texto.
    """
    rows: List[dict] = []
    for ln in join_continuations(lines):
        k = kv(ln)
        if not k:
            continue
        row: Dict[str, object] = {}
        for c in cols:
            v = k.get(c)
            if v in (None, ""):
                row[c] = None
                continue
            try:
                num = float(v)
            except ValueError:
                row[c] = v
                continue
            row[c] = num * force_scale if c in scale_cols else num
        rows.append(row)
    return pd.DataFrame(rows)


def load_results_from_s2k(md) -> ResultsData:
    """Extrae las tablas de resultados que ya vienen dentro del .s2k.

    `md` es un ModelData ya leido con extract_model(..., extra_tables=
    RESULTS_S2K_TABLES). Los valores de fuerza/momento se normalizan a kgf
    segun las unidades del modelo; los desplazamientos quedan en metros.
    """
    res = ResultsData()
    res.source = md.path
    fs = force_scale_for_units(md.units)
    tabs = md.raw_tables
    if not tabs:
        return res

    lines = _find_table(tabs, "JOINT DISPLACEMENTS")
    if lines:
        df = _s2k_to_df(lines, ["Joint", "OutputCase", "CaseType",
                                "StepType", "StepNum", "U1", "U2", "U3"])
        if len(df):
            res.displacements = df
            res.found.append("displacements")

    lines = _find_table(tabs, "JOINT REACTIONS")
    if lines:
        df = _s2k_to_df(lines, ["Joint", "OutputCase", "CaseType",
                                "F1", "F2", "F3"],
                        force_scale=fs, scale_cols={"F1", "F2", "F3"})
        if len(df):
            res.reactions = df
            res.found.append("reactions")

    lines = _find_table(tabs, "MODAL PERIODS AND FREQUENCIES")
    if lines:
        df = _s2k_to_df(lines, ["OutputCase", "StepType", "StepNum",
                                "Period", "Frequency"])
        if len(df):
            # Masas participativas (UX/UY/UZ) vienen en otra tabla
            mpr = _find_table(tabs, "MODAL PARTICIPATING MASS RATIOS")
            if mpr:
                mdf = _s2k_to_df(mpr, ["StepNum", "UX", "UY", "UZ"])
                if len(mdf):
                    df = df.merge(mdf, on="StepNum", how="left")
            res.modal = df
            res.found.append("modal")

    lines = _find_table(tabs, "STEEL DESIGN 1 - SUMMARY DATA")
    if lines:
        df = _s2k_to_df(lines, ["Frame", "DesignSect", "Status", "Ratio"])
        if len(df):
            res.steel_design = df
            res.found.append("steel_design")

    # Envolvente de fuerzas internas por seccion: se agrega en streaming
    # para no guardar en memoria las ~1M filas de ELEMENT FORCES - FRAMES.
    asg = _find_table(tabs, "FRAME SECTION ASSIGNMENTS")
    secmap: Dict[int, str] = {}
    if asg:
        for ln in join_continuations(asg):
            k = kv(ln)
            if "Frame" in k:
                try:
                    secmap[int(float(k["Frame"]))] = (
                        k.get("DesignSect") or k.get("AnalSect") or "")
                except ValueError:
                    pass
    ff_lines = _find_table(tabs, "ELEMENT FORCES - FRAMES")
    if ff_lines:
        agg: Dict[str, dict] = {}
        for ln in join_continuations(ff_lines):
            k = kv(ln)
            if "Frame" not in k:
                continue
            # excluir el caso MODAL (fuerzas normalizadas del modo, no reales)
            # y las filas sin caso (encabezados/espacios)
            ctype = (k.get("CaseType") or "").strip().lower()
            oc = (k.get("OutputCase") or "").strip()
            if ctype == "linmodal" or not oc or "modal" in oc.lower():
                continue
            try:
                fid = int(float(k["Frame"]))
            except ValueError:
                continue
            sec = secmap.get(fid)
            if not sec:
                continue
            d = agg.setdefault(sec, {"DesignSect": sec})
            for col in ("P", "V2", "V3", "T", "M2", "M3"):
                v = k.get(col)
                if not v:
                    continue
                try:
                    a = abs(float(v)) * fs
                except ValueError:
                    continue
                if col not in d or a > d[col]:
                    d[col] = a
        if agg:
            res.frame_forces = pd.DataFrame(list(agg.values()))
            res.found.append("frame_forces")

    return res


# ---------------------------------------------------------------- resumenes

def max_displacements(res: ResultsData, top: Optional[int] = None) -> List[dict]:
    """Maximo UX/UY/UZ (m) y total por caso; devuelve filas para tabla."""
    rows = []
    if res.displacements is None:
        return rows
    df = res.displacements.copy()
    # El caso MODAL reporta desplazamientos normalizados del modo, no fisicos
    ct = _pick(df, "CaseType")
    if ct:
        df = df[~df[ct].astype(str).str.lower().str.contains("modal",
                                                            na=False)]
    cx = _pick(df, "UX", "U1")
    cy = _pick(df, "UY", "U2")
    cz = _pick(df, "UZ", "U3")
    cc = _pick(df, "OutputCase", "Case")
    if not (cx and cy and cz and cc):
        return rows
    df = df[[cc, cx, cy, cz]].copy()
    df.columns = ["caso", "UX", "UY", "UZ"]
    df["UX"] = _num(df, "UX"); df["UY"] = _num(df, "UY"); df["UZ"] = _num(df, "UZ")
    for case, g in df.groupby("caso"):
        g = g.dropna(subset=["UX", "UY", "UZ"])
        if g.empty:
            continue
        du = g["UX"].abs().max(), g["UY"].abs().max(), g["UZ"].abs().max()
        rows.append({"caso": case,
                     "U1": du[0], "U2": du[1], "U3": du[2],
                     "UTOT": max(du)})
    rows.sort(key=lambda r: r["UTOT"], reverse=True)
    if top:
        rows = rows[:top]
    return rows


def envelope_frame_forces(res: ResultsData) -> Dict[str, dict]:
    """Maximos absolutos P, V2, V3, T, M2, M3 por seccion."""
    out: Dict[str, dict] = {}
    if res.frame_forces is None:
        return out
    ff = res.frame_forces.copy()
    if "DesignSect" not in ff.columns:
        if res.steel_design is None or "Frame" not in ff.columns:
            return out
        fr = res.steel_design[["Frame", "DesignSect"]].drop_duplicates()
        if "Frame" not in fr.columns:
            return out
        ff["Frame"] = pd.to_numeric(ff["Frame"], errors="coerce")
        fr["Frame"] = pd.to_numeric(fr["Frame"], errors="coerce")
        ff = ff.merge(fr, on="Frame", how="left")
        if "DesignSect" not in ff.columns:
            return out
    for col in ("P", "V2", "V3", "T", "M2", "M3"):
        if col in ff.columns:
            ff[col] = _num(ff, col)
    for sec, g in ff.groupby("DesignSect"):
        g = g.dropna(subset=["P"])
        if g.empty:
            continue
        row = {"seccion": sec}
        for col in ("P", "V2", "V3", "T", "M2", "M3"):
            if col in g.columns:
                row[col] = g[col].abs().max()
        out[sec] = row
    return out


def steel_ratios(res: ResultsData, top: int = 15) -> List[dict]:
    """Ratio D/C (Demand/Capacity) por barra y por seccion."""
    if res.steel_design is None:
        return [], []
    df = res.steel_design.copy()
    if "Ratio" not in df.columns:
        return [], []
    df["Ratio"] = _num(df, "Ratio")
    df = df.dropna(subset=["Ratio"])
    if df.empty:
        return [], []
    worst = df.sort_values("Ratio", ascending=False).head(top).to_dict("records")
    per_sec = (df.groupby("DesignSect")["Ratio"].max()
               .sort_values(ascending=False).to_dict())
    return worst, per_sec


def max_reactions(res: ResultsData, top: Optional[int] = None) -> List[dict]:
    if res.reactions is None:
        return []
    df = res.reactions.copy()
    cfx = _pick(df, "FX", "F1", "GlobalFX")
    cfy = _pick(df, "FY", "F2", "GlobalFY")
    cfz = _pick(df, "FZ", "F3", "GlobalFZ")
    cc = _pick(df, "OutputCase", "Case")
    cj = _pick(df, "Joint", "Text")
    if not (cfz and cc and cj):
        return []
    keep = [cc, cj, cfz] + [c for c in (cfx, cfy) if c]
    df = df[keep].copy()
    df.columns = ["caso", "nudo", "F3"] + (["F1", "F2"] if cfx and cfy else [])
    df["F3"] = _num(df, "F3")
    if "F1" in df.columns:
        df["F1"] = _num(df, "F1")
    if "F2" in df.columns:
        df["F2"] = _num(df, "F2")
    out = []
    for case, g in df.groupby("caso"):
        if "modal" in case.lower():
            continue
        g = g.dropna(subset=["F3"])
        if g.empty:
            continue
        fz = g["F3"].max()
        joint = g.loc[g["F3"].idxmax(), "nudo"]
        fx = g["F1"].abs().max() if "F1" in g.columns else 0.0
        fy = g["F2"].abs().max() if "F2" in g.columns else 0.0
        out.append({"caso": case, "nudo": joint, "F3": fz, "F1": fx, "F2": fy})
    out.sort(key=lambda r: r["F3"], reverse=True)
    if top:
        out = out[:top]
    return out


def modal_periods(res: ResultsData, n: int = 8) -> List[dict]:
    if res.modal is None:
        return []
    df = res.modal.copy()
    if "Period" in df.columns:
        df["Period"] = _num(df, "Period")
        df = df.dropna(subset=["Period"])
    return df.head(n).to_dict("records")


def modal_mode_shapes(res: ResultsData) -> Dict[int, pd.DataFrame]:
    """Desplazamientos de cada modo modal: {StepNum: DataFrame con U1/U2/U3}.

    Las filas MODAL normalizadas de SAP2000 son los vectores propios del
    modo; se usan para graficar la deformada modal (formas de modo).
    """
    out: Dict[int, pd.DataFrame] = {}
    if res.displacements is None:
        return out
    df = res.displacements.copy()
    st = _pick(df, "StepType")
    sn = _pick(df, "StepNum")
    cj = _pick(df, "Joint", "Text")
    if not (st and sn and cj):
        return out
    if "U1" in df.columns and "U2" in df.columns and "U3" in df.columns:
        keep = [cj, st, sn, "U1", "U2", "U3"]
    else:
        keep = [cj, st, sn]
    df = df[keep].copy()
    df = df[df[st].astype(str).str.lower() == "mode"]
    if df.empty:
        return out
    for snum, g in df.groupby(sn):
        try:
            k = int(float(snum))
        except (ValueError, TypeError):
            continue
        g = g.sort_values(cj)
        out[k] = g
    return out


def has_results(res: Optional[ResultsData]) -> bool:
    return bool(res) and bool(res.found)
