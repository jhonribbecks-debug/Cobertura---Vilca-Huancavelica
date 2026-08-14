"""Sap2kGen: genera archivos .s2k de SAP2000 a partir de planos (DWG/PDF) usando IA.

Flujo principal:
    dwg  ->  geometria (nudos/barras)  ->  plantilla .s2k  ->  .s2k nuevo
    plan ->  IA de vision (JSON)       ->  plantilla .s2k  ->  .s2k nuevo
"""

__version__ = "0.1.0"
