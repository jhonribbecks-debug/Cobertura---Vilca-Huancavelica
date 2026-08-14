"""Generador de memoria de calculo de cobertura metalica en Word (.docx).

Flujo:
    1. model_data.extract_model() lee el modelo .s2k finalizado de SAP2000
       (materiales, secciones, cargas, combinaciones, geometria).
    2. results.load_results() lee las tablas exportadas por SAP2000
       (desplazamientos, fuerzas, ratios de diseno, reacciones).
    3. esquemas.generar_figuras() dibuja las figuras esquematicas (PNG)
       a partir del modelo y sus resultados (vista 3D, perfiles, deformada,
       placa base, viga de concreto).
    4. docx.build_memoria() / proned.build_memoria_proned() componen la
       memoria .docx con python-docx, incrustando las figuras.
"""

from . import model_data, results, esquemas, docx, proned  # noqa: F401
