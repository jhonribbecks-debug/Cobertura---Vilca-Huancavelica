import clr, os, sys

idea_dir = r"C:\Program Files\IDEA StatiCa\StatiCa 20.1"
sys.path.append(idea_dir)

clr.AddReference(os.path.join(idea_dir, "IdeaRS.OpenModel.dll"))
import IdeaRS.OpenModel as om
import IdeaRS.OpenModel.Connection as iom_conn
import IdeaRS.OpenModel.CrossSection as cs
import IdeaRS.OpenModel.Material as mat
import IdeaRS.OpenModel.Geometry3D as geo
import IdeaRS.OpenModel.Loading as loading
import IdeaRS.OpenModel.Model as model
import System

# === Forces from SAP2000 frame 109 (Amplified Envelope Total CONCRETO) ===
# SAP2000: N=-96.73, Fy=-37.11, Fz=-4.79, Mx=-0.43 (kNm)
# IDEA axis convention: Vy = SAP Fy, Vz = SAP Fz, Mx = -SAP Mx (sign flip)
N_kN = -96.73
Vy_kN = -37.11
Vz_kN = -4.79
Mx_kNm = 0.43  # sign flipped from SAP2000
My_kNm = 0.0
Mz_kNm = 0.0

print(f"Forces (SAP2000 -> IDEA):")
print(f"  N:  {N_kN} kN")
print(f"  Vy: {Vy_kN} kN")
print(f"  Vz: {Vz_kN} kN")
print(f"  Mx: {Mx_kNm} kNm")
print(f"  My: {My_kNm} kNm")
print(f"  Mz: {Mz_kNm} kNm")

# === Create OpenModel ===
open_model = om.OpenModel()

# === Settings ===
open_model.OriginSettings = om.OriginSettings()
open_model.OriginSettings.CountryCode = om.CountryCode.ECEN
open_model.OriginSettings.ProjectName = "HUANCALPI Col 109"
open_model.OriginSettings.CheckEquilibrium = True

# === Materials ===
# Steel S355
steel = mat.MatSteelEc2()
steel.Id = 1
steel.Name = "S355"
steel.E = 210000000000
steel.G = steel.E / (2 * 1.3)
steel.Poisson = 0.3
steel.UnitMass = 7850
steel.fy = 355000000
steel.fu = 510000000
steel.DiagramType = mat.SteelDiagramType.Bilinear
open_model.MatSteel.Add(steel)

# Concrete C25/30
concrete = mat.MatConcreteEc2()
concrete.Id = 2
concrete.Name = "C25/30"
concrete.LoadFromLibrary = True
concrete.Fck = 25000000
open_model.MatConcrete.Add(concrete)

# Reinforcement B500B
rebar = mat.MatReinforcementEc2()
rebar.Id = 3
rebar.Name = "B500B"
rebar.LoadFromLibrary = True
open_model.MatReinforcement.Add(rebar)

# === Cross Sections ===
css_hss = cs.CrossSectionParameter()
css_hss.Id = 1
css_hss.Name = "HSS200x200x6"
css_hss.CrossSectionType = cs.CrossSectionType.Rhs
css_hss.Parameters.Add(cs.CrossSectionParameter.Param("B", 0.200))
css_hss.Parameters.Add(cs.CrossSectionParameter.Param("H", 0.200))
css_hss.Parameters.Add(cs.CrossSectionParameter.Param("t", 0.006))
open_model.CrossSection.Add(css_hss)

css_concrete = cs.CrossSectionParameter()
css_concrete.Id = 2
css_concrete.Name = "Rect 500/500"
css_concrete.CrossSectionType = cs.CrossSectionType.RectCS
css_concrete.Parameters.Add(cs.CrossSectionParameter.Param("Width", 0.500))
css_concrete.Parameters.Add(cs.CrossSectionParameter.Param("Height", 0.500))
open_model.CrossSection.Add(css_concrete)

# === MaterialBoltGrade ===
bolt_grade = mat.MaterialBoltGrade()
bolt_grade.Id = 1
bolt_grade.Name = "8.8"
bolt_grade.LoadFromLibrary = True
open_model.MatBoltGrade.Add(bolt_grade)

# === BoltAssembly (M20) ===
bolt_assembly = om.BoltAssembly()
bolt_assembly.Id = 1
bolt_assembly.Name = "M20"
bolt_assembly.Diameter = 0.02
bolt_assembly.HeadDiameter = 0.034
bolt_assembly.HeadHeight = 0.012
bolt_assembly.Borehole = 0.022
bolt_assembly.TensileStressArea = 245
bolt_assembly.NutThickness = 0.018
bolt_assembly.BoltGrade = bolt_grade
open_model.BoltAssembly.Add(bolt_assembly)

# === Nodes ===
# N1: connection point at base of column (0,0,0)
# N2: top of column (0,0,4) 
# N3: bottom of pedestal (0,0,-0.85)
nodes = []
for i, (x, y, z) in enumerate([(0, 0, 0), (0, 0, 4), (0, 0, -0.85)], 1):
    p = geo.Point3D()
    p.Id = i
    p.Name = f"N{i}"
    p.X = x
    p.Y = y
    p.Z = z
    open_model.Point3D.Add(p)
    nodes.append(p)

# === Members ===
# Column HSS 200x200x6
col = model.ConnectedMember()
col.Id = 1
col.Name = "Column"
col.MemberType = model.Member1DType.Column
col.CrossSection = css_hss
col.NodeBegin = nodes[0]
col.NodeEnd = nodes[1]
open_model.Member1D.Add(col)

# Concrete pedestal
ped = model.ConnectedMember()
ped.Id = 2
ped.Name = "Pedestal"
ped.MemberType = model.Member1DType.Other
ped.CrossSection = css_concrete
ped.NodeBegin = nodes[0]
ped.NodeEnd = nodes[2]
open_model.Member1D.Add(ped)

# === Connection Point ===
cp = iom_conn.ConnectionPoint()
cp.Id = 1
cp.Name = "CON1"
cp.Node = nodes[0]
cp.ConnectedMembers.Add(col)
cp.ConnectedMembers.Add(ped)
open_model.ConnectionPoint.Add(cp)

# === Connection Data ===
conn_data = iom_conn.ConnectionData()
conn_data.Id = 1
conn_data.Name = "CON1"
conn_data.ConnectionPoint = cp

# Beams (column and pedestal)
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
plate.Name = "BasePlate"
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
plate.Region = "M 0 0 L 0.3 0 L 0.3 0.3 L 0 0.3 L 0 0"
conn_data.Plates.Add(plate)

# Concrete block with ALL required properties
block = iom_conn.ConcreteBlockData()
block.Id = 20
block.Name = "PedestalBlock"
block.Material = "C25/30"

# The block should be below the connection point
# Depth = how far down it goes
# OutlinePoints should be in local coordinates relative to Origin

block.Origin = geo.Point3D()
block.Origin.Id = 0
block.Origin.X = 0
block.Origin.Y = 0
block.Origin.Z = -0.425  # Half of 0.85 depth centered

block.Depth = 0.85

# Outline points for 500x500 square (in local coords, X-Y plane)
# The block extends 0.25 in X and Y directions
outline_points = System.Collections.Generic.List[geo.Point3D]()
outline_points.Add(geo.Point3D(X=0.25, Y=0.25))
outline_points.Add(geo.Point3D(X=-0.25, Y=0.25))
outline_points.Add(geo.Point3D(X=-0.25, Y=-0.25))
outline_points.Add(geo.Point3D(X=0.25, Y=-0.25))
block.OutlinePoints = outline_points

block.AxisX = geo.Vector3D()
block.AxisX.X = 1
block.AxisY = geo.Vector3D()
block.AxisY.Y = 1
block.AxisZ = geo.Vector3D()
block.AxisZ.Z = 1

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
# Reference to the bolt assembly
bolt_ref = System.Type.GetType("IdeaRS.OpenModel.ReferenceElement, IdeaRS.OpenModel")
bolt_grid.BoltAssembly = om.ReferenceElement(bolt_assembly)
bolt_grid.Length = 0.3
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

# 8 anchors in 2x4 pattern
# 4 columns x 2 rows
positions = System.Collections.Generic.List[geo.Point3D]()
xs = [-0.075, 0.075]  # 2 rows, 150mm apart
zs = [-0.15, -0.05, 0.05, 0.15]  # 4 columns, 100mm apart
for x in xs:
    for z in zs:
        p = geo.Point3D()
        p.X = x
        p.Y = 0
        p.Z = z
        positions.Add(p)
bolt_grid.Positions = positions
bolt_grid.ConnectedParts = System.Collections.Generic.List[om.ReferenceElement]()
bolt_grid.ConnectedParts.Add(om.ReferenceElement(plate))
bolt_grid.ConnectedParts.Add(om.ReferenceElement(col))
conn_data.BoltGrids.Add(bolt_grid)

# Weld between column and base plate
weld = iom_conn.WeldData()
weld.Id = 40
weld.Name = "W1"
weld.ConnectedPartIds = System.Collections.Generic.List[str]()
weld.ConnectedPartIds.Add(plate.OriginalModelId)
weld.ConnectedPartIds.Add(beam1.OriginalModelId)
weld.Start = geo.Point3D()
weld.Start.X = -0.1
weld.Start.Y = 0.1
weld.Start.Z = 0
weld.End = geo.Point3D()
weld.End.X = 0.1
weld.End.Y = 0.1
weld.End.Z = 0
weld.Thickness = 0.006
weld.WeldType = iom_conn.WeldType.DoubleFillet
conn_data.Welds.Add(weld)

open_model.Connections.Add(conn_data)

# === Load Cases ===
# Create load case for the frame 109 results
lc = loading.LoadCase()
lc.Id = 1
lc.Name = "Frame109"
lc.LoadType = loading.LoadCaseType.Variable
lc.Type = loading.LoadCaseSubType.VariableNone
lc.Variable = loading.VariableType.Standard
open_model.LoadCase.Add(lc)

# === Load Combination ===
lg = loading.LoadGroupEC()
lg.Id = 1
lg.Name = "LOAD_GRP"
lg.GroupType = loading.LoadGroupType.Permanent
lg.Relation = loading.Relation.Standard
open_model.LoadGroup.Add(lg)

lc.LoadGroup = om.ReferenceElement(lg)

# Combination input
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
open_model.CombiInput.Add(combo)

# === Apply forces to the loaded member ===
# The column should carry the forces
# Forces are applied at the node connected to the column
# IDEA expects forces at the connection node

# Let's check what Force3D or similar types exist
print("\n=== Available Loading types ===")
loading_types = [x for x in dir(loading) if 'Force' in x or 'Load' in x]
print(loading_types)

# Serialize to XML
from System.Xml.Serialization import XmlSerializer
from System.IO import StringWriter

serializer = XmlSerializer(om.GetType())
writer = StringWriter()
serializer.Serialize(writer, om)
xml_str = writer.ToString()

with open("col109_final_iom_fixed.xml", "w", encoding="utf-16") as f:
    f.write(xml_str)

print(f"\nIOM written to col109_final_iom_fixed.xml ({len(xml_str)} chars)")

# Also create results XML for the forces
results_xml = f"""<?xml version="1.0" encoding="utf-16"?>
<Results>
  <ConnectionResultsData>
    <ConnectionId>1</ConnectionId>
    <ConnectionIdentifier>{conn_data.Id}</ConnectionIdentifier>
    <ResultsInNodes>
      <ResultOfNode>
        <Node>1</Node>
        <Name>CON1</Name>
        <Loading>
          <N>{N_kN * 1000}</N>
          <Qy>{Vy_kN * 1000}</Qy>
          <Qz>{Vz_kN * 1000}</Qz>
          <Mx>{Mx_kNm * 1000000}</Mx>
          <My>{My_kNm * 1000000}</My>
          <Mz>{Mz_kNm * 1000000}</Mz>
        </Loading>
      </ResultOfNode>
    </ResultsInNodes>
  </ConnectionResultsData>
</Results>
"""
with open("col109_final_results.xmlR", "w", encoding="utf-16") as f:
    f.write(results_xml)
print(f"Results XML written to col109_final_results.xmlR ({len(results_xml)} chars)")