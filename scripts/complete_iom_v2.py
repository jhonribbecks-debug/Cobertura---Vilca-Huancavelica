import clr, os, sys, xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from project_paths import project_file  # noqa: E402

idea_dir = r"C:\Program Files\IDEA StatiCa\StatiCa 20.1"
sys.path.append(idea_dir)

from System.Collections.Generic import List
clr.AddReference(os.path.join(idea_dir, "IdeaRS.OpenModel.dll"))
clr.AddReference(os.path.join(idea_dir, "IdeaStatiCa.Plugin.dll"))
import IdeaStatiCa.Plugin as plug
from IdeaRS.OpenModel import OpenModel, OriginSettings, CrossSectionConversionTable, CountryCode, ReferenceElement
from IdeaRS.OpenModel.Geometry3D import Point3D, Vector3D, LineSegment3D, PolyLine3D, Plane, CoordSystemByPoint
from IdeaRS.OpenModel.Material import MatSteelEc2, MatConcreteEc2, MatReinforcementEc2, BoltAssembly, MaterialBoltGrade, SteelDiagramType
from IdeaRS.OpenModel.CrossSection import CrossSectionParameter, CrossSectionType, ParameterString
from IdeaRS.OpenModel.Model import Member1D, Member1DType, Element1D
from IdeaRS.OpenModel.Loading import LoadGroupEC, LoadCase, LoadCaseType, LoadCaseSubType, VariableType, LoadGroupType, Relation, CombiInputEC, CombiItem, TypeOfCombiEC, TypeCalculationCombiEC
from IdeaRS.OpenModel.Connection import ConnectionPoint, ConnectedMember, ConnectionData, BeamData, PlateData, ConcreteBlockData, BoltGrid, WeldData, WeldType, CutBeamByBeamData, CutOrientation

# Forces from SAP2000 frame 109
N_kN = -96.73; Vy_kN = -37.11; Vz_kN = -4.79; Mx_kNm = 0.43; My_kNm = 0.0; Mz_kNm = 0.0

# === Build IOM ===
m = OpenModel()
m.OriginSettings = OriginSettings()
m.OriginSettings.ProjectName = "HUANCALPI Col 109"
m.OriginSettings.CrossSectionConversionTable = CrossSectionConversionTable.NoUsed
m.OriginSettings.CountryCode = CountryCode.ECEN

# Nodes
n1 = Point3D(); n1.Name="N_PedBase"; n1.Id=1; n1.X=0.0; n1.Y=0.0; n1.Z=-1.7
n2 = Point3D(); n2.Name="N_Conn";    n2.Id=2; n2.X=0.0; n2.Y=0.0; n2.Z=0.0
n3 = Point3D(); n3.Name="N_ColTop";  n3.Id=3; n3.X=0.0; n2.Y=0.0; n3.Z=3.4
for n in (n1,n2,n3): m.AddObject(n)

# Materials
st = MatSteelEc2(); st.Id=1; st.Name="S355"; st.E=210000000000.0; st.Poisson=0.3; st.G=st.E/(2*(1+0.3))
st.UnitMass=7850; st.fy=355000000.0; st.fu=510000000.0; st.DiagramType=SteelDiagramType.Bilinear; st.IsDefaultMaterial=False; st.OrderInCode=0
m.AddObject(st)

co = MatConcreteEc2(); co.Id=2; co.Name="C25/30"; co.LoadFromLibrary=True; co.Fck=25000000.0; co.IsDefaultMaterial=False; co.OrderInCode=0
m.AddObject(co)

rebar = MatReinforcementEc2(); rebar.Id=3; rebar.Name="B500B"; rebar.LoadFromLibrary=True; rebar.IsDefaultMaterial=False; rebar.OrderInCode=0
m.AddObject(rebar)

bg = MaterialBoltGrade(); bg.Id=1; bg.Name="8.8"; bg.LoadFromLibrary=True; bg.IsDefaultMaterial=False; bg.OrderInCode=0
m.AddObject(bg)

# Cross sections
css_col = CrossSectionParameter(); css_col.Id=1; css_col.Name="RHS 200/200/6"
css_col.CrossSectionType = CrossSectionType.RolledRHS
p = ParameterString(); p.Name="Depth"; p.Value="0.2"; css_col.Parameters.Add(p)
p = ParameterString(); p.Name="Width"; p.Value="0.2"; css_col.Parameters.Add(p)
p = ParameterString(); p.Name="Thickness"; p.Value="0.006"; css_col.Parameters.Add(p)
p = ParameterString(); p.Name="Radius"; p.Value="0"; css_col.Parameters.Add(p)
css_col.Material = ReferenceElement(st); m.AddObject(css_col)

css_ped = CrossSectionParameter(); css_ped.Id=2; css_ped.Name="Rect 500/500"
css_ped.CrossSectionType = CrossSectionType.Rect
p = ParameterString(); p.Name="Width"; p.Value="0.5"; css_ped.Parameters.Add(p)
p = ParameterString(); p.Name="Height"; p.Value="0.5"; css_ped.Parameters.Add(p)
css_ped.Material = ReferenceElement(co); m.AddObject(css_ped)

# Bolt assembly
ba = BoltAssembly(); ba.Id=1; ba.Name="M20"; ba.Diameter=0.02; ba.HeadDiameter=0.034
ba.HeadHeight=0.012; ba.Borehole=0.022; ba.TensileStressArea=245; ba.NutThickness=0.018
ba.BoltGrade = ReferenceElement(bg); m.AddObject(ba)

# Segments
seg_ped = LineSegment3D(); seg_ped.Id=1; seg_ped.StartPoint=ReferenceElement(n1); seg_ped.EndPoint=ReferenceElement(n2); m.AddObject(seg_ped)
seg_col = LineSegment3D(); seg_col.Id=2; seg_col.StartPoint=ReferenceElement(n2); seg_col.EndPoint=ReferenceElement(n3)
csys = CoordSystemByPoint(); csys.Point = Point3D(); csys.Point.X=0; csys.Point.Y=100000; csys.Point.Z=0
csys.InPlane = Plane.YZ; seg_col.LocalCoordinateSystem = csys; m.AddObject(seg_col)

pl_ped = PolyLine3D(); pl_ped.Id=1; pl_ped.Segments.Add(ReferenceElement(seg_ped)); m.AddObject(pl_ped)
pl_col = PolyLine3D(); pl_col.Id=2; pl_col.Segments.Add(ReferenceElement(seg_col)); m.AddObject(pl_col)

# Elements
e_ped = Element1D(); e_ped.Id=1; e_ped.Name="E_Ped"; e_ped.CrossSectionBegin=ReferenceElement(css_ped); e_ped.CrossSectionEnd=ReferenceElement(css_ped); e_ped.Segment=ReferenceElement(seg_ped); m.AddObject(e_ped)
e_col = Element1D(); e_col.Id=2; e_col.Name="E_Col"; e_col.CrossSectionBegin=ReferenceElement(css_col); e_col.CrossSectionEnd=ReferenceElement(css_col); e_col.Segment=ReferenceElement(seg_col); m.AddObject(e_col)

# Members
pm = Member1D(); pm.Id=1; pm.Name="Pedestal"; pm.Member1DType=Member1DType.Beam; pm.Elements1D.Add(ReferenceElement(e_ped)); m.Member1D.Add(pm)
cm = Member1D(); cm.Id=2; cm.Name="Columna"; cm.Member1DType=Member1DType.Column; cm.Elements1D.Add(ReferenceElement(e_col)); m.Member1D.Add(cm)

# Connection point
cp = ConnectionPoint(); cp.Id=1; cp.Name="Base Col 109"; cp.Node=ReferenceElement(n2)
cm_col = ConnectedMember(); cm_col.Id=2; cm_col.MemberId=ReferenceElement(cm); cm_col.IsContinuous=False
cm_ped = ConnectedMember(); cm_ped.Id=1; cm_ped.MemberId=ReferenceElement(pm); cm_ped.IsContinuous=True
cp.ConnectedMembers.Add(cm_col); cp.ConnectedMembers.Add(cm_ped)
m.AddObject(cp)

# Connection data
conn_data = ConnectionData()

# Beams
bd_ped = BeamData(); bd_ped.Id=1; bd_ped.Name="Pedestal"; bd_ped.OriginalModelId="1"; bd_ped.IsAdded=False; bd_ped.MirrorY=False; bd_ped.RefLineInCenterOfGravity=False; bd_ped.CrossSectionType="Rect"
bd_col = BeamData(); bd_col.Id=2; bd_col.Name="Columna"; bd_col.OriginalModelId="2"; bd_col.IsAdded=False; bd_col.MirrorY=False; bd_col.RefLineInCenterOfGravity=False; bd_col.CrossSectionType="RolledRHS"
conn_data.Beams = List[BeamData](); conn_data.Beams.Add(bd_ped); conn_data.Beams.Add(bd_col)

# Base plate
plate = PlateData()
plate.Id=10; plate.Name="BasePlate"; plate.Thickness=0.02
plate.Material="S355"; plate.OriginalModelId="10"; plate.IsNegativeObject=False
plate.Origin=Point3D(); plate.Origin.X=0.0; plate.Origin.Y=0.0; plate.Origin.Z=0.0
plate.AxisX=Vector3D(); plate.AxisX.X=1.0
plate.AxisY=Vector3D(); plate.AxisY.Y=1.0
plate.AxisZ=Vector3D(); plate.AxisZ.Z=1.0
plate.Region="M 0 0 L 0.6 0 L 0.6 0.6 L 0 0.6 L 0 0"
conn_data.Plates = List[PlateData](); conn_data.Plates.Add(plate)

# Concrete block - ALL required properties
cb = ConcreteBlockData()
cb.Id=20; cb.Name="PedestalBlock"; cb.Material="C25/30"; cb.OriginalModelId="20"
cb.Origin=Point3D(); cb.Origin.X=0.0; cb.Origin.Y=0.0; cb.Origin.Z=0.0
cb.Depth=0.85

# Outline points
outline = List[Point3D]()
outline.Add(Point3D()); outline[0].X=0.25; outline[0].Y=0.25; outline[0].Z=0
outline.Add(Point3D()); outline[1].X=-0.25; outline[1].Y=0.25; outline[1].Z=0
outline.Add(Point3D()); outline[2].X=-0.25; outline[2].Y=-0.25; outline[2].Z=0
outline.Add(Point3D()); outline[3].X=0.25; outline[3].Y=-0.25; outline[3].Z=0
cb.OutlinePoints = outline

cb.AxisX=Vector3D(); cb.AxisX.X=1.0
cb.AxisY=Vector3D(); cb.AxisY.Y=1.0
cb.AxisZ=Vector3D(); cb.AxisZ.Z=1.0
cb.Center=Point3D(); cb.Center.X=0.0; cb.Center.Y=0.0; cb.Center.Z=-0.425
cb.Region="M 0 0 L 0.5 0 L 0.5 0.5 L 0 0.5 L 0 0"
conn_data.ConcreteBlocks = List[ConcreteBlockData](); conn_data.ConcreteBlocks.Add(cb)

# BoltGrid with 8 anchors M20
bolt_grid = BoltGrid()
bolt_grid.Id=30; bolt_grid.Name="Anchors"; bolt_grid.OriginalModelId="30"
bolt_grid.BoltAssemblyName="M20"
bolt_grid.Length=0.4
bolt_grid.Origin=Point3D(); bolt_grid.Origin.X=0.0; bolt_grid.Origin.Y=0.0; bolt_grid.Origin.Z=0.0
bolt_grid.AxisX=Vector3D(); bolt_grid.AxisX.X=1.0
bolt_grid.AxisY=Vector3D(); bolt_grid.AxisY.Y=1.0
bolt_grid.AxisZ=Vector3D(); bolt_grid.AxisZ.Z=1.0

positions = List[Point3D]()
ys = [-0.075, 0.075]
zs = [-0.15, -0.05, 0.05, 0.15]
for y in ys:
    for z in zs:
        p=Point3D(); p.X=0.0; p.Y=y; p.Z=z; positions.Add(p)
bolt_grid.Positions = positions
bolt_grid.ConnectedPlates = List[ReferenceElement]()
bolt_grid.ConnectedPlates.Add(ReferenceElement(plate))
bolt_grid.ConnectedPlates.Add(ReferenceElement(bd_col))
conn_data.BoltGrids = List[BoltGrid](); conn_data.BoltGrids.Add(bolt_grid)

# Cuts
conn_data.CutBeamByBeams = List[CutBeamByBeamData]()
cut1 = CutBeamByBeamData()
cut1.ModifiedObject = ReferenceElement(bd_col); cut1.CuttingObject = ReferenceElement(plate)
cut1.Orientation = CutOrientation.Parallel; cut1.IsWeld = True
conn_data.CutBeamByBeams.Add(cut1)

# Welds
conn_data.Welds = List[WeldData]()
weld = WeldData()
weld.Id=40; weld.Name="W1"
weld.ConnectedPartIds = List[str](); weld.ConnectedPartIds.Add(plate.OriginalModelId); weld.ConnectedPartIds.Add(bd_col.OriginalModelId)
weld.Start=Point3D(); weld.Start.X=-0.3; weld.Start.Y=0.1; weld.Start.Z=0
weld.End=Point3D(); weld.End.X=0.3; weld.End.Y=0.1; weld.End.Z=0
weld.Thickness=0.006; weld.WeldType=WeldType.DoubleFillet
conn_data.Welds.Add(weld)

m.Connections = List[ConnectionData](); m.Connections.Add(conn_data)

# Load cases
lg = LoadGroupEC(); lg.Id=1; lg.Name="LG_ULS"; lg.GroupType=LoadGroupType.Variable; lg.Relation=Relation.Exclusive
lg.GammaQ=1.5; lg.GammaGInf=0; lg.GammaGSup=1.5; lg.Dzeta=0.85; lg.Psi0=0.7; lg.Psi1=0.5; lg.Psi2=0.3
m.AddObject(lg)
lc = LoadCase(); lc.Id=1; lc.Name="ULS_1.40CM_1.70CV"; lc.LoadType=LoadCaseType.Variable; lc.Type=LoadCaseSubType.VariableStatic
lc.Variable = VariableType.Standard; lc.LoadGroup = ReferenceElement(lg); m.AddObject(lc)
ci = CombiInputEC(); ci.Id=1; ci.Name="ULS"; ci.TypeCombiEC=TypeOfCombiEC.ULS; ci.TypeCalculationCombi=TypeCalculationCombiEC.Linear
it = CombiItem(); it.Id=1; it.Coeff=1.0; it.LoadCase = ReferenceElement(lc); ci.Items.Add(it)
m.AddObject(ci)

# Save IOM
iom_path = project_file("col109_complete_iom.xml")
m.SaveToXmlFile(iom_path)
print("IOM saved:", os.path.getsize(iom_path), "bytes")

# Verify
xml_content = open(iom_path, 'r', encoding='utf-16').read()
print("ConcreteBlockData:", "<ConcreteBlockData" in xml_content)
print("BoltGrid:", "BoltGrid" in xml_content)
print("FoundationBlockHeight:", "FoundationBlockHeight" in xml_content)
print("Width (should NOT be in ConcreteBlockData):", "Width>0.5<" in xml_content)

# Results XML
ET.register_namespace('', "http://www.w3.org/2001/XMLSchema")
ET.register_namespace('xsi', "http://www.w3.org/2001/XMLSchema-instance")
ET.register_namespace('xsd', "http://www.w3.org/2001/XMLSchema")
root = ET.Element("OpenModelResult")
root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")
root.set("xmlns:xsd", "http://www.w3.org/2001/XMLSchema")
roms = ET.SubElement(root, "ResultOnMembers")
rom = ET.SubElement(roms, "ResultOnMembers")
loading = ET.SubElement(rom, "Loading")
ET.SubElement(loading, "LoadingType").text = "LoadCase"
ET.SubElement(loading, "Id").text = "1"
items = ET.SubElement(loading, "Items")
rli = ET.SubElement(items, "ResultOfLoadingItem")
ET.SubElement(rli, "Coefficient").text = "1"
members = ET.SubElement(rom, "Members")
rom_item = ET.SubElement(members, "ResultOnMember")
member = ET.SubElement(rom_item, "Member")
ET.SubElement(member, "MemberType").text = "Member1D"
ET.SubElement(member, "Id").text = "2"
ET.SubElement(rom_item, "ResultType").text = "InternalForces"
results = ET.SubElement(rom_item, "Results")
rb = ET.SubElement(results, "ResultBase")
rb.set("xsi:type", "ResultOnSection")
ET.SubElement(rb, "AbsoluteRelative").text = "Absolute"
ET.SubElement(rb, "Position").text = "0"
sec_results = ET.SubElement(rb, "Results")
srf = ET.SubElement(sec_results, "SectionResultBase")
srf.set("xsi:type", "ResultOfInternalForces")
sloading = ET.SubElement(srf, "Loading")
ET.SubElement(sloading, "LoadingType").text = "LoadCase"
ET.SubElement(sloading, "Id").text = "1"
sitems = ET.SubElement(sloading, "Items")
srli = ET.SubElement(sitems, "ResultOfLoadingItem")
ET.SubElement(srli, "Coefficient").text = "1"
ET.SubElement(srf, "N").text = str(N_kN)
ET.SubElement(srf, "Qy").text = str(Vy_kN)
ET.SubElement(srf, "Qz").text = str(Vz_kN)
ET.SubElement(srf, "Mx").text = str(Mx_kNm)
ET.SubElement(srf, "My").text = str(My_kNm)
ET.SubElement(srf, "Mz").text = str(Mz_kNm)
res_path = project_file("col109_results.xmlR")
tree = ET.ElementTree(root)
tree.write(res_path, encoding="utf-16", xml_declaration=True)
print("Results saved:", os.path.getsize(res_path), "bytes")

# CreateConProjFromIOM + Calculate
out_path = project_file("col109_complete.ideaCon")
empty_res = project_file("empty_res.xmlR")
with open(empty_res, "w", encoding="utf-16") as f:
    f.write('<?xml version="1.0" encoding="utf-16"?><OpenModelResult xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" />')

factory2 = plug.ConnHiddenClientFactory(idea_dir)
client = factory2.Create()

try:
    print("\n=== CreateConProjFromIOM ===")
    client.CreateConProjFromIOM(iom_path, empty_res, out_path)
    print("Created:", os.path.exists(out_path), "| Size:", os.path.getsize(out_path) if os.path.exists(out_path) else 0)

    print("\n=== OpenProject ===")
    client.OpenProject(out_path)
    info = client.GetProjectInfo()
    print("Project:", info.Name, "| Code:", info.DesignCode)
    conn_id = info.Connections[0].Identifier
    print("Connection:", info.Connections[0].Name, "| Id:", conn_id)

    print("\n=== GetConnectionModel ===")
    cm = client.GetConnectionModel(conn_id)
    print("  Beams:", len(cm.Beams) if cm.Beams else 0)
    print("  Plates:", len(cm.Plates) if cm.Plates else 0)
    print("  ConcreteBlocks:", len(cm.ConcreteBlocks) if cm.ConcreteBlocks else 0)
    for cb in cm.ConcreteBlocks or []:
        print("    Block:", cb.Name, "| Depth:", cb.Depth, "| Mat:", cb.Material)
    print("  BoltGrids:", len(cm.BoltGrids) if cm.BoltGrids else 0)
    for bg in cm.BoltGrids or []:
        print("    Grid:", bg.Name, "| BoltAssemblyName:", bg.BoltAssemblyName, "| Count:", len(bg.Positions) if bg.Positions else 0)
    print("  Welds:", len(cm.Welds) if cm.Welds else 0)

    print("\n=== Calculate ===")
    calc_result = client.Calculate(conn_id)
    ccr = calc_result.ConnectionCheckRes
    print("  ConnectionCheckRes count:", len(ccr) if ccr else 0)
    if ccr:
        for cr in ccr:
            print("  ConRes:", cr.Name)
            print("  CheckResSummary count:", len(cr.CheckResSummary) if cr.CheckResSummary else 0)
            if cr.CheckResSummary:
                for s in cr.CheckResSummary:
                    print("    ", s.Name, "| Value:", s.CheckValue, "| Status:", s.CheckStatus)
            print("  ConcreteBlock count:", len(cr.CheckResConcreteBlock) if cr.CheckResConcreteBlock else 0)
            print("  Anchor count:", len(cr.CheckResAnchor) if cr.CheckResAnchor else 0)

except Exception as e:
    import traceback; traceback.print_exc()
finally:
    try: client.CloseProject()
    except: pass