import clr, os, sys
idea_dir = r"C:\Program Files\IDEA StatiCa\StatiCa 20.1"
sys.path.append(idea_dir)
clr.AddReference(os.path.join(idea_dir, "IdeaStatiCa.Plugin"))
import IdeaStatiCa.Plugin as plug
clr.AddReference(os.path.join(idea_dir, "IdeaRS.OpenModel.dll"))
import IdeaRS.OpenModel as om

# ============================================================
# Build a complete IOM with concrete block (with all required
# properties) + 8 anchors M20 + loads from SAP2000 frame 109
# ============================================================

import System
import IdeaRS.OpenModel.Connection as iom_conn
import IdeaRS.OpenModel.CrossSection as cs
import IdeaRS.OpenModel.Material as mat
import IdeaRS.OpenModel.Geometry3D as geo
import IdeaRS.OpenModel.Loading as loading
import IdeaRS.OpenModel.Model as model

# --- Forces from SAP2000 frame 109 (Amplified Envelope Total CONCRETO) ---
# SAP2000: N=-96.73, Fy=-37.11, Fz=-4.79, Mx=-0.43 kNm
# IDEA convention: Vy=shear in local Y, Vz=shear in local Z
# For a vertical column with local Y pointing sideways:
#   IDEA Vy corresponds to SAP Fy  (strong axis shear)
#   IDEA Vz corresponds to SAP Fz  (weak axis shear)
#   IDEA Mx corresponds to -SAP Mx (moment about strong axis flips sign in base connection)
N_kN = -96.73      # Compression
Vy_kN = -37.11      # Shear
Vz_kN = -4.79       # Torsional shear component
Mx_kNm = 0.43       # Moment (sign flipped from SAP2000)
My_kNm = 0.0
Mz_kNm = 0.0

print(f"Forces (SAP2000 -> IDEA): N={N_kN} kN, Vy={Vy_kN}, Vz={Vz_kN}, Mx={Mx_kNm}, My={My_kNm}, Mz={Mz_kNm}")

# --- Create OpenModel ---
m = om.OpenModel()

# --- Settings ---
m.OriginSettings = om.OriginSettings()
m.OriginSettings.CountryCode = om.CountryCode.ECEN
m.OriginSettings.ProjectName = "HUANCALPI Col 109"
m.OriginSettings.CheckEquilibrium = True

# --- Materials ---
steel = mat.MatSteelEc2()
steel.Id = 1
steel.Name = "S355"
steel.E = 210000000000
steel.G = 80769230769.23
steel.Poisson = 0.3
steel.UnitMass = 7850
steel.fy = 355000000
steel.fu = 510000000
steel.DiagramType = mat.SteelDiagramType.Bilinear
m.MatSteel.Add(steel)

concrete = mat.MatConcreteEc2()
concrete.Id = 2
concrete.Name = "C25/30"
concrete.LoadFromLibrary = True
concrete.Fck = 25000000
m.MatConcrete.Add(concrete)

rebar = mat.MatReinforcementEc2()
rebar.Id = 3
rebar.Name = "B500B"
rebar.LoadFromLibrary = True
m.MatReinforcement.Add(rebar)

# Bolt grade
bolt_grade = mat.MaterialBoltGrade()
bolt_grade.Id = 1
bolt_grade.Name = "8.8"
bolt_grade.LoadFromLibrary = True
m.MatBoltGrade.Add(bolt_grade)

# --- Cross Sections ---
# HSS 200x200x6 (RolledRHS)
css_hss = cs.CrossSectionParameter()
css_hss.Id = 1
css_hss.Name = "HSS200x200x6"
css_hss.CrossSectionType = cs.CrossSectionType.RolledRHS
# RolledRHS parameters: Depth, Width, Thickness, RoundingRadius
css_hss.Parameters.Add(cs.CrossSectionParameter.Param("D", 0.200))
css_hss.Parameters.Add(cs.CrossSectionParameter.Param("B", 0.200))
css_hss.Parameters.Add(cs.CrossSectionParameter.Param("t", 0.006))
css_hss.Parameters.Add(cs.CrossSectionParameter.Param("r", 0.0))
css_hss.Material = om.ReferenceElement(steel)
m.CrossSection.Add(css_hss)

# Concrete 500x500 (Rect)
css_concrete = cs.CrossSectionParameter()
css_concrete.Id = 2
css_concrete.Name = "Rect 500/500"
css_concrete.CrossSectionType = cs.CrossSectionType.Rect
css_concrete.Parameters.Add(cs.CrossSectionParameter.Param("Width", 0.500))
css_concrete.Parameters.Add(cs.CrossSectionParameter.Param("Height", 0.500))
css_concrete.Material = om.ReferenceElement(concrete)
m.CrossSection.Add(css_concrete)

# --- Bolt Assembly (M20) ---
bolt_assembly = om.BoltAssembly()
bolt_assembly.Id = 1
bolt_assembly.Name = "M20"
bolt_assembly.Diameter = 0.02
bolt_assembly.HeadDiameter = 0.034
bolt_assembly.HeadHeight = 0.012
bolt_assembly.Borehole = 0.022
bolt_assembly.TensileStressArea = 245
bolt_assembly.NutThickness = 0.018
bolt_assembly.BoltGrade = om.ReferenceElement(bolt_grade)
m.BoltAssembly.Add(bolt_assembly)

# --- Nodes ---
# Coordinate system: Z up, X and Y in plan
# Connection at (0,0,0)
# Column top at (0,0,4)
# Pedestal bottom at (0,0,-0.85)
nodes = []
for i, (x, y, z) in enumerate([(0, 0, 0), (0, 0, 4), (0, 0, -0.85)], 1):
    p = geo.Point3D()
    p.Id = i
    p.Name = f"N{i}"
    p.X = x
    p.Y = y
    p.Z = z
    m.Point3D.Add(p)
    nodes.append(p)

# --- Members ---
# Column: HSS 200x200x6 from N3 (pedestal bottom) through N1 (connection) to N2 (top)
col = model.ConnectedMember()
col.Id = 1
col.Name = "Column"
col.MemberType = model.Member1DType.Column
col.CrossSection = css_hss
col.NodeBegin = nodes[0]      # N1 at connection
col.NodeEnd = nodes[1]        # N2 at top
col.EccentricityBeginX = 0
col.EccentricityBeginY = 0
col.EccentricityEndX = 0
col.EccentricityEndY = 0
m.Member1D.Add(col)

# Pedestal: concrete 500x500 from N1 (connection) to N3 (bottom)
ped = model.ConnectedMember()
ped.Id = 2
ped.Name = "Pedestal"
ped.MemberType = model.Member1DType.Other
ped.CrossSection = css_concrete
ped.NodeBegin = nodes[0]      # N1 at connection
ped.NodeEnd = nodes[2]        # N3 at bottom
ped.EccentricityBeginX = 0
ped.EccentricityBeginY = 0
ped.EccentricityEndX = 0
ped.EccentricityEndY = 0
m.Member1D.Add(ped)

# --- Connection Point ---
cp = iom_conn.ConnectionPoint()
cp.Id = 1
cp.Name = "CON1"
cp.Node = nodes[0]  # At connection point (0,0,0)
cp.ConnectedMembers.Add(col)
cp.ConnectedMembers.Add(ped)
m.ConnectionPoint.Add(cp)

# --- Connection Data ---
conn_data = iom_conn.ConnectionData()
conn_data.Id = 1
conn_data.Name = "CON1"
conn_data.ConnectionPoint = cp

# Beams (column and pedestal) - these define what's in the connection model
beam1 = iom_conn.BeamData()
beam1.Id = 1
beam1.Name = "Column"
beam1.OriginalModelId = "1"
beam1.IsAdded = False
beam1.MirrorY = False
beam1.RefLineInCenterOfGravity = False
beam1.ConnectedMember = col
conn_data.Beams.Add(beam1)

beam2 = iom_conn.BeamData()
beam2.Id = 2
beam2.Name = "Pedestal"
beam2.OriginalModelId = "2"
beam2.IsAdded = False
beam2.MirrorY = False
beam2.RefLineInCenterOfGravity = False
beam2.ConnectedMember = ped
conn_data.Beams.Add(beam2)

# Base plate
plate = iom_conn.PlateData()
plate.Id = 10
plate.Name = "BP1"
plate.OriginalModelId = "10"
plate.Material = "S355"
plate.Thickness = 0.02
plate.Origin = geo.Point3D()
plate.Origin.Id = 0
plate.Origin.X = 0
plate.Origin.Y = 0
plate.Origin.Z = 0
plate.AxisX = geo.Vector3D()
plate.AxisX.X = 1
plate.AxisY = geo.Vector3D()
plate.AxisY.Y = 1
plate.AxisZ = geo.Vector3D()
plate.AxisZ.Z = 1
plate.Region = "M 0 0 L 0.25 0 L 0.25 0.25 L 0 0.25 L 0 0"
conn_data.Plates.Add(plate)

# Concrete block with ALL properties
block = iom_conn.ConcreteBlockData()
block.Id = 20
block.Name = "PedestalBlock"
block.Material = "C25/30"
block.Depth = 0.85  # total depth of the block

# Origin at center of the block (top surface at connection level, Z=0)
block.Origin = geo.Point3D()
block.Origin.Id = 0
block.Origin.X = 0
block.Origin.Y = 0
block.Origin.Z = -0.425  # center of the 0.85m deep block

# Outline points in X-Y plane (local coordinates relative to Origin)
# For 500x500 square
outline = System.Collections.Generic.List[geo.Point3D]()
outline.Add(geo.Point3D(X=0.25, Y=0.25))
outline.Add(geo.Point3D(X=-0.25, Y=0.25))
outline.Add(geo.Point3D(X=-0.25, Y=-0.25))
outline.Add(geo.Point3D(X=0.25, Y=-0.25))
block.OutlinePoints = outline

# Axes
block.AxisX = geo.Vector3D()
block.AxisX.X = 1
block.AxisY = geo.Vector3D()
block.AxisY.Y = 1
block.AxisZ = geo.Vector3D()
block.AxisZ.Z = 1

# Center
block.Center = geo.Point3D()
block.Center.Id = 0
block.Center.X = 0
block.Center.Y = 0
block.Center.Z = -0.425

block.OriginalModelId = "20"
conn_data.ConcreteBlocks.Add(block)

# Bolt grid with 8 anchors M20 in 2x4 pattern
bolt_grid = iom_conn.BoltGrid()
bolt_grid.Id = 30
bolt_grid.Name = "Anchors"
bolt_grid.OriginalModelId = "30"
bolt_grid.BoltAssembly = om.ReferenceElement(bolt_assembly)
bolt_grid.Length = 0.4  # 400mm anchor length

bolt_grid.Origin = geo.Point3D()
bolt_grid.Origin.Id = 0
bolt_grid.Origin.X = 0
bolt_grid.Origin.Y = 0
bolt_grid.Origin.Z = 0
bolt_grid.AxisX = geo.Vector3D()
bolt_grid.AxisX.X = 1
bolt_grid.AxisY = geo.Vector3D()
bolt_grid.AxisY.Y = 1
bolt_grid.AxisZ = geo.Vector3D()
bolt_grid.AxisZ.Z = 1

# 8 anchors in 2 rows x 4 columns pattern
# Spacing: 100mm in Z direction (columns), 150mm in Y direction (rows)
positions = System.Collections.Generic.List[geo.Point3D]()
ys = [-0.075, 0.075]        # 2 rows, 150mm apart (Y direction)
zs = [-0.15, -0.05, 0.05, 0.15]  # 4 columns, 100mm apart (Z direction)
for y in ys:
    for z in zs:
        p = geo.Point3D()
        p.X = 0
        p.Y = y
        p.Z = z
        positions.Add(p)
bolt_grid.Positions = positions
bolt_grid.ConnectedParts = System.Collections.Generic.List[om.ReferenceElement]()
bolt_grid.ConnectedParts.Add(om.ReferenceElement(plate))
bolt_grid.ConnectedParts.Add(om.ReferenceElement(beam1))
conn_data.BoltGrids.Add(bolt_grid)

# Cuts (beam cuts from plate)
# Column cut by base plate
cut1 = iom_conn.CutBeamByBeamData()
cut1.ModifiedObject = om.ReferenceElement(beam1)
cut1.CuttingObject = om.ReferenceElement(plate)
cut1.Orientation = iom_conn.CutOrientation.Parallel
cut1.IsWeld = True
conn_data.CutBeamByBeams = System.Collections.Generic.List[iom_conn.CutBeamByBeamData]()
conn_data.CutBeamByBeams.Add(cut1)

# Welds
weld = iom_conn.WeldData()
weld.Id = 40
weld.Name = "W1"
weld.ConnectedPartIds = System.Collections.Generic.List[str]()
weld.ConnectedPartIds.Add(plate.OriginalModelId)
weld.ConnectedPartIds.Add(beam1.OriginalModelId)
conn_data.Welds = System.Collections.Generic.List[iom_conn.WeldData]()
conn_data.Welds.Add(weld)

# --- Load Cases ---
lc = loading.LoadCase()
lc.Id = 1
lc.Name = "Frame109"
lc.LoadType = loading.LoadCaseType.Variable
lc.Type = loading.LoadCaseSubType.VariableNone
lc.Variable = loading.VariableType.Standard
m.LoadCase.Add(lc)

# Load Group
lg = loading.LoadGroupEC()
lg.Id = 1
lg.Name = "LOAD_GRP"
lg.GroupType = loading.LoadGroupType.Permanent
lg.Relation = loading.Relation.Standard
m.LoadGroup.Add(lg)
lc.LoadGroup = om.ReferenceElement(lg)

# Combination
combo = loading.CombiInputEC()
combo.Id = 1
combo.Name = "Frame 109"
combo.Description = "Envelope Total CONCRETO - Frame 109"
combo.TypeCombiEC = loading.TypeOfCombiEC.ULS
combo.TypeCalculationCombi = loading.TypeCalculationCombiEC.Linear
item = loading.CombiItem()
item.Id = 1
item.Coeff = 1
item.LoadCase = om.ReferenceElement(lc)
combo.Items.Add(item)
m.CombiInput.Add(combo)

# Apply forces to the loaded member (column) at the connection
# Forces are defined as ResultOfNode or similar
# Let's try applying them via the member
loaded_member = iom_conn.LoadedMember()
loaded_member.Id = 50
loaded_member.Name = "LoadedColumn"
loaded_member.ConnectedMember = om.ReferenceElement(col)
loaded_member.MemberType = iom_conn.LoadedMemberType.Column
# Forces at node
loaded_member.ForcesAtNode = System.Collections.Generic.List[iom_conn.Force3D]()
force = iom_conn.Force3D()
force.N = N_kN * 1000      # Convert kN to N
force.Qy = Vy_kN * 1000
force.Qz = Vz_kN * 1000
force.Mx = Mx_kNm * 1000  # kNm to Nmm
force.My = My_kNm * 1000
force.Mz = Mz_kNm * 1000
loaded_member.ForcesAtNode.Add(force)
m.Connections[0].LoadedMembers.Add(loaded_member)

m.Connections.Add(conn_data)

# Serialize
from System.Xml.Serialization import XmlSerializer
from System.IO import StringWriter

serializer = XmlSerializer(m.GetType())
writer = StringWriter()
serializer.Serialize(writer, m)
xml_str = writer.ToString()

with open("col109_iom_complete.xml", "w", encoding="utf-16") as f:
    f.write(xml_str)

print(f"\nIOM written to col109_iom_complete.xml ({len(xml_str)} chars)")

# Check if ConcreteBlockData section is there
if "<ConcreteBlockData" in xml_str:
    print("ConcreteBlockData IS in XML")
else:
    print("ConcreteBlockData is NOT in XML")

# Check for BoltGrid
if "<BoltGrid" in xml_str:
    print("BoltGrid IS in XML")
else:
    print("BoltGrid is NOT in XML")

# Check for LoadedMember
if "LoadedMember" in xml_str:
    print("LoadedMember IS in XML")
else:
    print("LoadedMember is NOT in XML")