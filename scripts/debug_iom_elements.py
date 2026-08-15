import clr, os, sys, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from project_paths import project_file, out_dir  # noqa: E402

idea_dir = r"C:\Program Files\IDEA StatiCa\StatiCa 20.1"
sys.path.append(idea_dir)

from System.Collections.Generic import List
clr.AddReference(os.path.join(idea_dir, "IdeaRS.OpenModel.dll"))
clr.AddReference(os.path.join(idea_dir, "IdeaStatiCa.Plugin.dll"))
import IdeaStatiCa.Plugin as plug

from IdeaRS.OpenModel import OpenModel, OriginSettings, CrossSectionConversionTable, CountryCode, ReferenceElement
from IdeaRS.OpenModel.Geometry3D import Point3D, Vector3D, LineSegment3D, PolyLine3D, Plane, CoordSystemByPoint
from IdeaRS.OpenModel.Geometry2D import Point2D
from IdeaRS.OpenModel.Material import MatSteelEc2, MatConcreteEc2, MatReinforcementEc2, BoltAssembly, MaterialBoltGrade, SteelDiagramType
from IdeaRS.OpenModel.CrossSection import CrossSectionParameter, CrossSectionType, ParameterString
from IdeaRS.OpenModel.Model import Member1D, Member1DType, Element1D
from IdeaRS.OpenModel.Loading import LoadGroupEC, LoadCase, LoadCaseType, LoadCaseSubType, VariableType, LoadGroupType, Relation, CombiInputEC, CombiItem, TypeOfCombiEC, TypeCalculationCombiEC
from IdeaRS.OpenModel.Connection import ConnectionPoint, ConnectedMember, ConnectionData, BeamData, PlateData, ConcreteBlockData, BoltGrid, WeldData, WeldType, CutBeamByBeamData

idea_dir_local = idea_dir

def build_and_test_iom(include_cuts=False, include_welds=False, include_bolts=True, include_concrete=True, name="test"):
    """Build an IOM with configurable elements and try to import it."""
    
    m = OpenModel()
    m.OriginSettings = OriginSettings()
    m.OriginSettings.ProjectName = f"Test {name}"
    m.OriginSettings.CrossSectionConversionTable = CrossSectionConversionTable.NoUsed
    m.OriginSettings.CountryCode = CountryCode.ECEN

    # Nodes
    n1 = Point3D(); n1.Name="N_PedBase"; n1.Id=1; n1.X=0.0; n1.Y=0.0; n1.Z=-1.7
    n2 = Point3D(); n2.Name="N_Conn";    n2.Id=2; n2.X=0.0; n2.Y=0.0; n2.Z=0.0
    n3 = Point3D(); n3.Name="N_ColTop";  n3.Id=3; n3.X=0.0; n3.Y=0.0; n3.Z=3.4
    for n in (n1,n2,n3): m.AddObject(n)

    # Materials
    st = MatSteelEc2(); st.Id=1; st.Name="S355"; st.E=210000000000.0; st.Poisson=0.3; st.G=st.E/(2*(1+0.3))
    st.UnitMass=7850; st.fy=355000000.0; st.fu=510000000.0; st.DiagramType=SteelDiagramType.Bilinear
    m.AddObject(st)

    co = MatConcreteEc2(); co.Id=2; co.Name="C25/30"; co.LoadFromLibrary=True; co.Fck=25000000.0
    m.AddObject(co)

    rebar = MatReinforcementEc2(); rebar.Id=3; rebar.Name="B500B"; rebar.LoadFromLibrary=True
    m.AddObject(rebar)

    bg = MaterialBoltGrade(); bg.Id=1; bg.Name="8.8"; bg.LoadFromLibrary=True
    m.AddObject(bg)

    # Cross sections
    css_col = CrossSectionParameter(); css_col.Id=1; css_col.Name="RHS 200/200/6"
    css_col.CrossSectionType = CrossSectionType.RolledRHS
    for name_p, val in [("Depth","0.2"), ("Width","0.2"), ("Thickness","0.006"), ("Radius","0")]:
        p = ParameterString(); p.Name=name_p; p.Value=val; css_col.Parameters.Add(p)
    css_col.Material = ReferenceElement(st)
    m.AddObject(css_col)

    css_ped = CrossSectionParameter(); css_ped.Id=2; css_ped.Name="Rect 500/500"
    css_ped.CrossSectionType = CrossSectionType.Rect
    for name_p, val in [("Width","0.5"), ("Height","0.5")]:
        p = ParameterString(); p.Name=name_p; p.Value=val; css_ped.Parameters.Add(p)
    css_ped.Material = ReferenceElement(co)
    m.AddObject(css_ped)

    # Bolt assembly
    ba = BoltAssembly(); ba.Id=1; ba.Name="M20"; ba.Diameter=0.02; ba.HeadDiameter=0.034
    ba.HeadHeight=0.012; ba.Borehole=0.022; ba.TensileStressArea=245; ba.NutThickness=0.018
    ba.BoltGrade = ReferenceElement(bg)
    m.AddObject(ba)

    # Segments
    seg_ped = LineSegment3D(); seg_ped.Id=1; seg_ped.StartPoint=ReferenceElement(n1); seg_ped.EndPoint=ReferenceElement(n2)
    m.AddObject(seg_ped)
    seg_col = LineSegment3D(); seg_col.Id=2; seg_col.StartPoint=ReferenceElement(n2); seg_col.EndPoint=ReferenceElement(n3)
    csys = CoordSystemByPoint(); csys.Point = Point3D(); csys.Point.X=0; csys.Point.Y=100000; csys.Point.Z=0
    csys.InPlane = Plane.YZ; seg_col.LocalCoordinateSystem = csys
    m.AddObject(seg_col)
    pl_ped = PolyLine3D(); pl_ped.Id=1; pl_ped.Segments.Add(ReferenceElement(seg_ped)); m.AddObject(pl_ped)
    pl_col = PolyLine3D(); pl_col.Id=2; pl_col.Segments.Add(ReferenceElement(seg_col)); m.AddObject(pl_col)

    # Elements
    e_ped = Element1D(); e_ped.Id=1; e_ped.Name="E_Ped"; e_ped.CrossSectionBegin=ReferenceElement(css_ped); e_ped.CrossSectionEnd=ReferenceElement(css_ped); e_ped.Segment=ReferenceElement(seg_ped)
    m.AddObject(e_ped)
    e_col = Element1D(); e_col.Id=2; e_col.Name="E_Col"; e_col.CrossSectionBegin=ReferenceElement(css_col); e_col.CrossSectionEnd=ReferenceElement(css_col); e_col.Segment=ReferenceElement(seg_col)
    m.AddObject(e_col)

    # Members
    pm = Member1D(); pm.Id=1; pm.Name="Pedestal"; pm.Member1DType=Member1DType.Beam; pm.Elements1D.Add(ReferenceElement(e_ped))
    m.Member1D.Add(pm)
    cm = Member1D(); cm.Id=2; cm.Name="Columna"; cm.Member1DType=Member1DType.Column; cm.Elements1D.Add(ReferenceElement(e_col))
    m.Member1D.Add(cm)

    # Connection point
    cp = ConnectionPoint(); cp.Id=1; cp.Name="Base Col 109"; cp.Node=ReferenceElement(n2)
    cm_col = ConnectedMember(); cm_col.Id=2; cm_col.MemberId=ReferenceElement(cm); cm_col.IsContinuous=False
    cm_ped = ConnectedMember(); cm_ped.Id=1; cm_ped.MemberId=ReferenceElement(pm); cm_ped.IsContinuous=True
    cp.ConnectedMembers.Add(cm_col); cp.ConnectedMembers.Add(cm_ped)
    m.AddObject(cp)

    # Connection data
    conn_data = ConnectionData()

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

    # Concrete block
    if include_concrete:
        cb = ConcreteBlockData()
        cb.Id=20; cb.Name="PedestalBlock"; cb.Material="C25/30"; cb.OriginalModelId="20"
        cb.Origin=Point3D(); cb.Origin.X=0.0; cb.Origin.Y=0.0; cb.Origin.Z=0.0
        cb.Depth=0.85
        outline = List[Point2D]()
        for (x, y) in [(0.25,0.25), (-0.25,0.25), (-0.25,-0.25), (0.25,-0.25)]:
            p = Point2D(); p.X=x; p.Y=y; outline.Add(p)
        cb.OutlinePoints = outline
        cb.AxisX=Vector3D(); cb.AxisX.X=1.0
        cb.AxisY=Vector3D(); cb.AxisY.Y=1.0
        cb.AxisZ=Vector3D(); cb.AxisZ.Z=1.0
        cb.Center=Point3D(); cb.Center.X=0.0; cb.Center.Y=0.0; cb.Center.Z=-0.425
        cb.Region="M 0 0 L 0.5 0 L 0.5 0.5 L 0 0.5 L 0 0"
        conn_data.ConcreteBlocks = List[ConcreteBlockData](); conn_data.ConcreteBlocks.Add(cb)

    # Bolt grid
    if include_bolts:
        bolt_grid = BoltGrid()
        bolt_grid.Id=30; bolt_grid.Name="Anchors"; bolt_grid.OriginalModelId="30"
        bolt_grid.BoltAssemblyName="M20"
        bolt_grid.Length=0.4
        bolt_grid.IsAnchor=True
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
        bolt_grid.ConnectedPartIds = List[str]()
        bolt_grid.ConnectedPartIds.Add(plate.OriginalModelId)
        bolt_grid.ConnectedPartIds.Add(bd_col.OriginalModelId)
        conn_data.BoltGrids = List[BoltGrid](); conn_data.BoltGrids.Add(bolt_grid)

    # Cuts
    if include_cuts:
        conn_data.CutBeamByBeams = List[CutBeamByBeamData]()
        cut1 = CutBeamByBeamData()
        cut1.ModifiedObject = ReferenceElement(bd_col); cut1.CuttingObject = ReferenceElement(plate)
        cut1.IsWeld = True
        conn_data.CutBeamByBeams.Add(cut1)

    # Welds
    if include_welds:
        conn_data.Welds = List[WeldData]()
        weld = WeldData()
        weld.Id=40; weld.Name="W1"
        weld.ConnectedPartIds = List[str]()
        weld.ConnectedPartIds.Add(plate.OriginalModelId)
        weld.ConnectedPartIds.Add(bd_col.OriginalModelId)
        weld.Start=Point3D(); weld.Start.X=-0.3; weld.Start.Y=0.1; weld.Start.Z=0
        weld.End=Point3D(); weld.End.X=0.3; weld.End.Y=0.1; weld.End.Z=0
        weld.Thickness=0.006; weld.WeldType=WeldType.DoubleFillet
        conn_data.Welds.Add(weld)

    m.Connections = List[ConnectionData](); m.Connections.Add(conn_data)

    # Load cases
    lg = LoadGroupEC(); lg.Id=1; lg.Name="LG"; lg.GroupType=LoadGroupType.Permanent; lg.Relation=Relation.Standard
    m.AddObject(lg)
    lc = LoadCase(); lc.Id=1; lc.Name="LC1"; lc.LoadType=LoadCaseType.Permanent; lc.Type=LoadCaseSubType.PermanentStandard
    lc.Variable = VariableType.Standard; lc.LoadGroup = ReferenceElement(lg)
    m.AddObject(lc)
    ci = CombiInputEC(); ci.Id=1; ci.Name="Comb1"; ci.TypeCombiEC=TypeOfCombiEC.ULS; ci.TypeCalculationCombi=TypeCalculationCombiEC.Linear
    it = CombiItem(); it.Id=1; it.Coeff=1.0; it.LoadCase = ReferenceElement(lc); ci.Items.Add(it)
    m.AddObject(ci)

    # Save
    iom_path = os.path.join(out_dir(), "test_iom_{}.xml".format(name))
    m.SaveToXmlFile(iom_path)
    print(f"  IOM saved: {os.path.getsize(iom_path)} bytes")

    # Test
    factory = plug.ConnHiddenClientFactory(idea_dir_local)
    client = factory.Create()
    
    out_path = os.path.join(out_dir(), "test_{}.ideaCon".format(name))
    empty_res = project_file("empty_res.xmlR")
    with open(empty_res, "w", encoding="utf-16") as f:
        f.write('<?xml version="1.0" encoding="utf-16"?><OpenModelResult xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" />')
    
    try:
        client.CreateConProjFromIOM(iom_path, empty_res, out_path)
        print(f"  ✓ SUCCESS: Project created ({os.path.getsize(out_path)} bytes)")
        return True
    except Exception as e:
        print(f"  ✗ FAILED: {type(e).__name__}")
        return False
    finally:
        try: client.CloseProject()
        except: pass

# Test each element individually
print("=== Testing IOM elements ===")
print("\n1. Beams + plate (no cuts, welds, bolts, concrete):")
build_and_test_iom(include_cuts=False, include_welds=False, include_bolts=False, include_concrete=False, name="basic")

print("\n2. Beams + plate + concrete block:")
build_and_test_iom(include_cuts=False, include_welds=False, include_bolts=False, include_concrete=True, name="concrete")

print("\n3. Beams + plate + bolts (no concrete):")
build_and_test_iom(include_cuts=False, include_welds=False, include_bolts=True, include_concrete=False, name="bolts")

print("\n4. Beams + plate + concrete + bolts:")
build_and_test_iom(include_cuts=False, include_welds=False, include_bolts=True, include_concrete=True, name="concrete_bolts")

print("\n5. Beams + plate + cuts + welds + concrete + bolts:")
build_and_test_iom(include_cuts=True, include_welds=True, include_bolts=True, include_concrete=True, name="all")