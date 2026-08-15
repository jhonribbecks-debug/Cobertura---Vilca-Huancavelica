# -*- coding: UTF-8 -*-
"""Rutas de proyecto parametrizadas para los scripts de memoria/IOM.

Las rutas se resuelven en este orden:

1. Variable de entorno especifica (TENORIOUS_*_PATH) si esta definida.
2. ``TENORIOUS_PROJECT`` (ruta a un .rvt) -> se usa su directorio.
3. ``TENORIOUS_DIR`` (directorio del proyecto) si esta definido.
4. Fallback: busca una carpeta con *.rvt o subcarpeta MN dentro del Escritorio.

Uso en cada script:

    from project_paths import project_dir, out_dir

    iom_path = project_file("col109_complete_iom.xml")
"""

import glob
import os
import sys

_TOOLBOX = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _TOOLBOX)

_DEFAULT_OUT = os.path.join(
    os.environ.get("TEMP", os.environ.get("TMP", ".")), "opencode")


def _find_project_dir():
    env = os.environ.get("TENORIOUS_DIR", "")
    if env and os.path.isdir(env):
        return env

    proj = os.environ.get("TENORIOUS_PROJECT", "")
    if proj and os.path.isfile(proj):
        return os.path.dirname(proj)

    desk = os.path.join(os.path.expanduser("~"), "OneDrive", "Escritorio")
    if os.path.isdir(desk):
        for entry in sorted(os.listdir(desk)):
            full = os.path.join(desk, entry)
            if os.path.isdir(full) and (glob.glob(os.path.join(full, "*.rvt"))
                                        or os.path.isdir(os.path.join(full, "MN"))):
                return full
    return ""


PROJECT_DIR = _find_project_dir()


def project_file(name):
    """Ruta de un archivo dentro de la carpeta del proyecto."""
    if PROJECT_DIR:
        return os.path.join(PROJECT_DIR, name)
    return os.path.join(_DEFAULT_OUT, name)


def project_dir():
    return PROJECT_DIR


def out_dir():
    return os.environ.get("TENORIOUS_OUT", _DEFAULT_OUT)