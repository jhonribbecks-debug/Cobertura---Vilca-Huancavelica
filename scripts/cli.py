"""Interfaz de linea de comandos para Sap2kGen.

Ejemplos:
    python cli.py template "Modelo_Arco_Huancalpi_1.s2k"
    python cli.py dwg "4. ESTRUCTURA METALICA ff.dwg" "Modelo_Arco_Huancalpi_1.s2k" -o salida.s2k --map capa:seccion
    python cli.py plan "1.ARQUITECTURAF-Modelo.pdf" "Modelo_Arco_Huancalpi_1.s2k" -o salida.s2k
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sap2000gen.s2kreader import parse_s2k  # noqa: E402
from sap2000gen.pipeline import dwg_to_s2k, plan_to_s2k  # noqa: E402
from sap2000gen.memoria.model_data import extract_model  # noqa: E402
from sap2000gen.memoria import results as res  # noqa: E402
from sap2000gen.memoria.docx import build_memoria  # noqa: E402
from sap2000gen.memoria.proned import build_memoria_proned  # noqa: E402


def cmd_template(args: argparse.Namespace) -> None:
    model = parse_s2k(args.file)
    print(f"Tablas en {args.file}:")
    for name, rows in model.passthrough:
        print(f"  - {name}  ({len(rows)} lineas)")
    print("\nSecciones definidas en la plantilla:")
    for name in model.sections:
        print(f"  - {name}")


def cmd_dwg(args: argparse.Namespace) -> None:
    layer_map = {}
    for item in args.map or []:
        layer, _, section = item.partition(":")
        layer_map[layer.strip()] = section.strip()
    print(f"Extrayendo geometria de {args.input} ...")
    res = dwg_to_s2k(args.input, args.template, args.output,
                     layer_sections=layer_map or None,
                     include_layers=args.only,
                     skip_layers=args.skip)
    print(f"OK: {res['joints']} nudos, {res['frames']} barras")
    print(f"Archivo generado: {res['output']}")


def cmd_plan(args: argparse.Namespace) -> None:
    print(f"Interpretando {args.input} con IA de vision ...")
    res = plan_to_s2k(args.input, args.template, args.output)
    print(f"OK: {res['joints']} nudos, {res['frames']} barras")
    print(f"Archivo generado: {res['output']}")


def cmd_text(args: argparse.Namespace) -> None:
    from sap2000gen import text_readers as tr
    ext = os.path.splitext(args.input)[1].lower()
    if ext == ".docx":
        out = tr.docx_dump(args.input)
        print(f"Texto extraido -> {out}")
    elif ext in (".xlsx", ".xls"):
        outs = tr.excel_to_csv(args.input)
        print("CSVs extraidos ->")
        for o in outs:
            print(f"  {o}")
    elif ext == ".s2k":
        info = tr.s2k_summary(args.input)
        print("Sumario .s2k:")
        print("  ", info)
    else:
        print(f"Extension no soportada: {ext}")


def cmd_pdf(args: argparse.Namespace) -> None:
    from sap2000gen import pdf
    info = pdf.pdf_inspect(args.input, dpi=args.dpi, out_dir=args.outdir,
                           save_images=args.images)
    total = sum(len(t) for _, t in info["pages"])
    print(f"{len(info['pages'])} paginas, {total} caracteres de texto extraido")
    if info["blank"]:
        print(f"  Paginas SIN texto (escaneadas): {', '.join(map(str, info['blank']))}")
    if info["images"]:
        print("  Imagenes generadas:")
        for im in info["images"]:
            print(f"    {im}")
    for num, t in info["pages"]:
        if t.strip():
            print(f"\n=== Pagina {num} ===")
            print(t)


def cmd_memoria(args: argparse.Namespace) -> None:
    print(f"Leyendo modelo .s2k: {args.model}")
    if args.resultados:
        md = extract_model(args.model)
    else:
        md = extract_model(args.model, extra_tables=res.RESULTS_S2K_TABLES)
    if md.errors:
        print("  ERROR:", "; ".join(md.errors))
        sys.exit(1)
    print(f"  -> {md.n_joints} nudos, {md.n_frames} barras, "
          f"{len(md.sections)} secciones, {len(md.combos)} combinaciones")
    print(f"  -> Peso total de acero estimado: {md.total_weight / 1000:.2f} tf")

    r = None
    if args.resultados:
        print(f"Leyendo resultados de SAP2000: {args.resultados}")
        r = res.ResultsData()
        r.load(args.resultados)
        if r.found:
            print("  -> Tablas encontradas:", ", ".join(r.found))
        else:
            print("  -> ADVERTENCIA: no se reconocio ninguna tabla de "
                  "resultados en el archivo.")
    else:
        r = res.load_results_from_s2k(md)
        if r.found:
            print("  -> Resultados detectados dentro del .s2k:",
                  ", ".join(r.found))
        else:
            print("  -> El .s2k no incluye tablas de resultados; las "
                  "secciones 5 y 6 quedaran con aviso PENDIENTE.")

    extra = {
        "proyecto": args.proyecto,
        "ubicacion": args.ubicacion,
        "cui": args.cui,
        "propietario": args.propietario,
        "solicita": args.solicita,
        "elaborado": args.elaborado,
        "revisado": args.revisado,
        "fecha": args.fecha,
    }
    print(f"Generando memoria: {args.output}")
    if getattr(args, "formato", "pronied") == "pronied":
        sismo = {
            "zona": getattr(args, "zona", 3),
            "u": getattr(args, "uso", 1.0),
            "s": getattr(args, "suelo", 1.05),
            "tp": getattr(args, "tp", 0.6),
            "tl": getattr(args, "tl", 2.0),
            "r": getattr(args, "r", 8.0),
            "viento": getattr(args, "viento", 100.0),
        }
        out = build_memoria_proned(md, r, output=args.output, extra=extra,
                                   sismo=sismo, planos=args.planos)
    else:
        out = build_memoria(md, r, output=args.output, extra=extra,
                            planos=args.planos)
    print(f"OK: memoria creada en {out}")


def main() -> None:
    p = argparse.ArgumentParser(prog="sap2kgen",
                                description="Genera archivos .s2k de SAP2000 desde planos")
    sub = p.add_subparsers(dest="command", required=True)

    t = sub.add_parser("template", help="Inspecciona una plantilla .s2k")
    t.add_argument("file")
    t.set_defaults(func=cmd_template)

    d = sub.add_parser("dwg", help="Genera .s2k desde un DWG/DXF (geometria exacta)")
    d.add_argument("input", help="Ruta del plano .dwg o .dxf")
    d.add_argument("template", help="Ruta de la plantilla .s2k")
    d.add_argument("-o", "--output", default="modelo_generado.s2k")
    d.add_argument("--map", action="append", metavar="CAPA:SECCION",
                   help="Mapeo capa->seccion, ej: --map CORDON:ARCO")
    d.add_argument("--only", action="append", metavar="CAPA",
                   help="Solo usar estas capas (whitelist)")
    d.add_argument("--skip", action="append", metavar="CAPA",
                   help="Ignorar estas capas (adicional al filtro automatico)")
    d.set_defaults(func=cmd_dwg)

    im = sub.add_parser("plan", help="Genera .s2k desde imagen/PDF con IA de vision")
    im.add_argument("input", help="Ruta del plano (.png/.jpg/.pdf)")
    im.add_argument("template", help="Ruta de la plantilla .s2k")
    im.add_argument("-o", "--output", default="modelo_generado.s2k")
    im.set_defaults(func=cmd_plan)

    m = sub.add_parser("memoria", help="Genera memoria de calculo .docx desde un .s2k")
    m.add_argument("--model", required=True, help="Ruta del modelo .s2k finalizado")
    m.add_argument("--resultados", default=None,
                   help="Ruta de resultados exportados de SAP2000 (.xlsx/.csv)")
    m.add_argument("-o", "--output", default="Memoria_de_calculo_cobertura.docx")
    m.add_argument("--formato", choices=["simple", "pronied"], default="pronied",
                   help="Formato de la memoria (default: pronied/PRONIED)")
    m.add_argument("--proyecto", default=None)
    m.add_argument("--ubicacion", default=None)
    m.add_argument("--cui", default=None)
    m.add_argument("--propietario", default=None)
    m.add_argument("--solicita", default=None)
    m.add_argument("--elaborado", default=None)
    m.add_argument("--revisado", default=None)
    m.add_argument("--fecha", default=None)
    m.add_argument("--planos", action="append", metavar="PNG",
                   help="Imagen de plano a anexar (repetible, formato simple)")
    m.add_argument("--zona", type=float, default=3.0,
                   help="Zona sismica E.030 (1-4)")
    m.add_argument("--uso", type=float, default=1.0, help="Factor de uso U")
    m.add_argument("--suelo", type=float, default=1.05, help="Factor de suelo S")
    m.add_argument("--tp", type=float, default=0.6, help="Periodo Tp (s)")
    m.add_argument("--tl", type=float, default=2.0, help="Periodo Tl (s)")
    m.add_argument("--r", type=float, default=8.0,
                   help="Coeficiente de reduccion sismica R")
    m.add_argument("--viento", type=float, default=100.0,
                   help="Velocidad de viento (km/h)")
    m.set_defaults(func=cmd_memoria)

    pd = sub.add_parser("pdf", help="Lee un PDF: extrae texto o lo convierte a imagenes")
    pd.add_argument("input", help="Ruta del archivo .pdf")
    pd.add_argument("--images", action="store_true",
                    help="Generar PNG de todas las paginas (no solo las escaneadas)")
    pd.add_argument("--dpi", type=int, default=200, help="Resolucion de las imagenes")
    pd.add_argument("--outdir", default=None,
                    help="Carpeta de salida de las imagenes (defecto: _planos_png)")
    pd.set_defaults(func=cmd_pdf)

    tx = sub.add_parser("text",
                        help="Extrae texto de docx/xlsx/.s2k a archivos UTF-8")
    tx.add_argument("input", help="Ruta .docx / .xlsx / .xls / .csv / .s2k")
    tx.set_defaults(func=cmd_text)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
