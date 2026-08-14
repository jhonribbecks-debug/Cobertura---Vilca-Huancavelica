# Metodología de la Memoria de Cálculo Estructural
## COBERTURA METÁLICA EN ARCO - TIJERAL · HUANCALPI

> Documento de soporte para la integración de la metodología en la
> `Memoria_de_Calculo_Estructural_Cobertura_Huancalpi.docx`. Reúne la
> base metodológica, los datos reales del modelo SAP2000
> (`MN\HUANCALPI - MODELO FINAL v4.s2k`) y los respaldos de los informes
> complementarios (drenaje pluvial e informe de conexión metálica).

---

## 1. Procedimiento general de generación de la memoria

La memoria de cálculo estructural se genera de forma **automatizada** a partir del
modelo `.s2k` mediante `cli.py`:

```bat
python cli.py memoria --model "MN\HUANCALPI - MODELO FINAL v4.s2k" ^
        -o "Memoria_de_Calculo_Estructural_Cobertura_Huancalpi.docx" ^
        --formato pronied --proyecto "..." --ubicacion "Vilca, Huancavelica"
```

**Flujo**: `.s2k` (modelo + resultados) → `sap2000gen/memoria/`
(`model_data.extract_model` extrae modelo; `results.py` lee resultados) →
`proned.py` / `docx.py` componen el `.docx` con tablas, fórmulas y figuras.

- **Modelo**: 414 nudos, 863 barras, 96 áreas, 14 apoyos.
- **Peso total de acero**: 13.688 tf.
- **Unidades del modelo**: `Tonf, m, C`.

---

## 2. Metodología estructural (memoria principal)

### 2.1 Normativa de referencia
- **NTP E.020** "Cargas" (2020)
- **NTP E.030** "Diseño Sismorresistente" (2018/2026)
- **NTP E.050** "Suelos y Cimentaciones" (2018)
- **NTP E.060** "Concreto Armado" (2020)
- **NTP E.090** "Estructuras Metálicas" (2020)
- **AISC 360-16/22** (LRFD) · **AISC 341-16** (Sísmico) · **AWS D1.1** (Soldadura)
- **ASTM A500/A572** (perfiles) · **ASTM F1554 / A325** (anclajes)

### 2.2 Hipótesis de modelado (Cap. 2.1)
- Modelo 3D de pórticos de acero con elementos barra (frame).
- Apoyos en la base de las columnas: empotrados o articulados según placa base.
- Tensores (Ø5/8″) modelados con liberación de momentos y capacidad solo de tracción (tension-only).
- La cobertura (planchas) se modela como carga distribuida sobre las correas; no aporta rigidez lateral.

### 2.3 Modelo estructural
- Viga-arcos-tijerales en perfiles tubulares HSS; correas HSS; tensores en tracción; columnas HSS.
- Geometría: largo 22.65 m, ancho 30.30 m, alto 11.66 m (z: 0.20 → 11.86 m).

### 2.4 Cargas y combinaciones (Cap. 2.3/2.4)
Patrones de carga: **PP** (Dead), **CV/S/C** (Live), **NIEVE**, viento
`VX±/B`, `VX±/S`, `VY±/B`, `VY±/S`, sísmico `SX`, `SY`, `SEX`, `SEY`, **MODAL**.

Casos de carga: 16 (LinStatic / LinRespSpec / LinModal). Combinaciones LRFD:
22 (ej. `1.40CM`, `1.2CM+1.6CV+0.5NIEVE`, `1.2CM+1.3W+0.5CV+0.5S`,
`1.2CM+1.6S+(0.5CV ó 0.80W)`, envolventes `1.3W ó +SX`).

### 2.5 Materiales y secciones (Cap. 2.2/5.2)
Acero: `A500GrB46` (Fy ≈ 317 MPa), `ASTM A500 GrA` (Fy ≈ 269 MPa),
`A572` (Fy ≈ 343 MPa); E ≈ 204 GPa; γ ≈ 7850 kg/m³.
Hormigón: `C30` (f’c = 3000 psi). Electrodos E60/A5718; pernos F1554 Gr.36 /
A325; tensores Ø5/8″; tornillos autoperforantes.

Secciones (HSS y Ø5/8 tubo circular): BRIDA SUP/INF HSS100×50×3-4.5 mm,
DIAGONALES HSS50×50×2 mm, CORREA HSS150×50×3 mm, COLUMNA HSS200×200×8 mm.

---

## 3. Diseño de elementos estructurales (Cap. 5.1/5.2)
Verificación AISC 360-16 (LRFD) vía módulo automático de SAP2000. Un elemento es
válido cuando **D/C ≤ 1.00**.

Factores de resistencia: φc = 0.90 (compresión) · φb = 0.90 (flexión) ·
φt = 0.90 (tracción) · φv = 0.90 (corte).

- **Correas**: flexión y deflexión (L/200).
- **Bridas y diagonales**: tracción/compresión y flexocompresión (AISC H1).
- **Columnas**: compresión con pandeo (AISC E3) y flexo-compresión.
- **Tensores Ø5/8″**: tracción pura (AISC D2).
- **Conexiones soldadas**: AWS D1.1; **pernos anclaje**: ASTM F1554.

Ejemplo (HSS100×50×4.5, A500GrB46, 7 unidades, L=1.58 m):
Pu=17.02 tf, Mu=0.23 tf·m, Vu=0.02 tf → D/C compresión 0.695, tracción 0.461,
flexión 0.193, interacción H1.1 = 0.867 ≤ 1.00 → CUMPLE.

---

## 4. Conexiones, placa base y anclaje (Cap. 5.4)
Diseño soldado (AWS D1.1) / empernado (A325). Las columnas se anclan a zapatas
mediante **placas base** (A572 Gr.50) con pernos ASTM F1554 Gr.36. La placa base
se verificó con el modelo de elementos finitos **"Coneccion plancha base.ideaCon"
(IDEA StatiCa CBFEM)**, que acompaña como respaldo.

### 4.1 Metodología del informe de conexión (conversión PDF→texto, leído con `cli.py pdf`)
- Normativa: **AISC 360-16 (LRFD)**; **ACI 318-14 §17.4.x** para anclajes.
- Material: A36 (Fy=36 ksi); HSS(Imp)8×8×5/8; pernos `3/4"` A325 (fu=119.7 ksi).
- Cargas de equilibrio en LE1 (Joint COL): N=−66,539 kN, Vy=4.901, Vz=−29.184 kN,
  Mx=0, My=−14.03, Mz=−85.66 kN·m.
- Verificaciones (todos OK): Placas 0.7%<5%, Anclajes 99.3%<100%,
  Soldaduras 88.4%<100%, Hormigón 12.9%<100%, Corte 36.7%<100%, Pandeo —.
- Anclaje: resistencia a tracción ϕNsa=124,440 kN ≥ 84,262 kN (ϕ=0.70, ACI 17.4.1).

---

## 5. Drenaje pluvial (informe complementario)
Metodología del documento `informe_drenaje_pluvial.docx`.

- **Normativa**: Norma Técnica **CE.040** Drenaje Pluvial (RNE, RM N° 126-2021-VIVIENDA).
- **Hipótesis**: área de techo en proyección horizontal (no superficie curva del arco).
- **Método racional** (CE.040 Art. 11.2/11.3, Anexo I 1.2.1):
  `Q = 0.95·C·I·A/3600` (L/s), con C=0.95 (techos impermeables).
- **Intensidad** (IILA-SENAMHI-UNI modificada, CE.040 Anexo I 1.3):
  i = 11.20 × 1.7731 × 1.5276 → **I ≈ 30.33 mm/h** (T=25 años, tc=10 min).
- **Datos**: A = 80,295 m² → **Q ≈ 0.643 L/s** (total); 4 bajantes → 0.161 L/s c/bajante.
- **Canaleta**: caja 0,25×0,14 m (1% pendiente), verif. Manning (CE.040 Anexo II).
- **Bajantes**: Ø≥0,05 m (2″), PVC (n=0.010), 2 por canalón por criterio constructivo.

---

## 6. Cimentación (Cap. 5.5)
EMS: suelo CL (arcilla baja plasticidad + arena), EV-178/HIOMKAR GTV149-26
(Lab. GEO TEST V S.A.C.).
- qult = 1.49 kg/cm² ; qadm = 0.50 kg/cm² (FS=3.0); asentamiento admisible 2.50 cm.
- Zapatas aisladas 1.50×1.50 m a 1.50 m de desplante (F1554) + contrazapata.
- Asentamiento calculado: 0.802 cm < 2.50 cm → admisible.

---

## 7. Control de desplazamientos (Cap. 3.5/4.2)
Derivas según NTP E.030; flecha cobertura L/200 (gravedad), L/250 (viento,
ASCE 7/AISC DG3). Periodo fundamental T₁=0.625 s (modo 1); masa participante ≥90%
(Art. 29.2 NTP E.030).

---

## 8. Anexos
- **ANEXO A. PLANOS**: vistas 3D y planos (figuras N°1-6 de la memoria).
- **Conexión metálica**: `Coneccion plancha base.ideaCon` + informe `.pdf`.
- **Drenaje pluvial**: `informe_drenaje_pluvial.docx`.
- **Modelo matemático actualizado**: `MN\HUANCALPI - MODELLO FINAL v4.s2k`
  (unidad origen: `Tonf, m, C`).
