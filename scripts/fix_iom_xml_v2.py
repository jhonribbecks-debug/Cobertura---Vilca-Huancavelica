import os, sys

idea_dir = r"C:\Program Files\IDEA StatiCa\StatiCa 20.1"
sys.path.append(idea_dir)
clr = None
import clr
clr.AddReference(os.path.join(idea_dir, "IdeaStatiCa.Plugin.dll"))
import IdeaStatiCa.Plugin as plug

from System.Collections.Generic import List as SList

# Read the working IOM file
iom_path = r"C:\Users\aintc\AppData\Local\Temp\opencode\col109_final_iom.xml"
content = open(iom_path, 'r', encoding='utf-16').read()

# --- 1. Fix ConcreteBlockData - add all required properties ---
old_cb_start = content.find('<ConcreteBlockData>')
old_cb_end = content.find('</ConcreteBlockData>') + len('</ConcreteBlockData>')
if old_cb_start >= 0:
    new_cb = '''<ConcreteBlockData>
          <Id>20</Id>
          <Name>PedestalBlock</Name>
          <Material>C25/30</Material>
          <OriginalModelId>20</OriginalModelId>
          <Origin>
            <Id>0</Id>
            <X>0</X>
            <Y>0</Y>
            <Z>0</Z>
          </Origin>
          <Depth>0.85</Depth>
          <OutlinePoints>
            <Point2D><Id>0</Id><X>0.25</X><Y>0.25</Y></Point2D>
            <Point2D><Id>1</Id><X>-0.25</X><Y>0.25</Y></Point2D>
            <Point2D><Id>2</Id><X>-0.25</X><Y>-0.25</Y></Point2D>
            <Point2D><Id>3</Id><X>0.25</X><Y>-0.25</Y></Point2D>
          </OutlinePoints>
          <AxisX><X>1</X><Y>0</Y><Z>0</Z></AxisX>
          <AxisY><X>0</X><Y>1</Y><Z>0</Z></AxisY>
          <AxisZ><X>0</X><Y>0</Y><Z>1</Z></AxisZ>
          <Center>
            <Id>0</Id>
            <X>0</X>
            <Y>0</Y>
            <Z>-0.425</Z>
          </Center>
          <Region>M 0 0 L 0.5 0 L 0.5 0.5 L 0 0.5 L 0 0</Region>
        </ConcreteBlockData>'''
    content = content[:old_cb_start] + new_cb + content[old_cb_end:]
    print("ConcreteBlockData fixed")
else:
    print("ERROR: ConcreteBlockData not found")

# --- 2. Add BoltAssembly and MatBoltGrade ---
# Add after last MatSteel
mat_steel_end = content.find('</MatSteel>')
if mat_steel_end >= 0:
    extra_xml = '''</MatSteel>
  <MatBoltGrade>
    <MaterialBoltGrade>
      <Id>1</Id>
      <Name>8.8</Name>
      <LoadFromLibrary>true</LoadFromLibrary>
      <IsDefaultMaterial>false</IsDefaultMaterial>
      <OrderInCode>0</OrderInCode>
    </MaterialBoltGrade>
  </MatBoltGrade>
  <BoltAssembly>
    <BoltAssembly>
      <Id>1</Id>
      <Name>M20</Name>
      <Diameter>0.02</Diameter>
      <HeadDiameter>0.034</HeadDiameter>
      <HeadHeight>0.012</HeadHeight>
      <Borehole>0.022</Borehole>
      <TensileStressArea>245</TensileStressArea>
      <NutThickness>0.018</NutThickness>
      <BoltGrade>
        <TypeName>MaterialBoltGrade</TypeName>
        <Id>1</Id>
      </BoltGrade>
    </BoltAssembly>
  </BoltAssembly>'''
    content = content[:mat_steel_end] + extra_xml + content[mat_steel_end+len('</MatSteel>'):]
    print("MatBoltGrade and BoltAssembly added")

# --- 3. Add BoltGrid after ConcreteBlocks ---
cb_end = content.find('</ConcreteBlocks>')
if cb_end >= 0:
    bolt_grid_xml = '''</ConcreteBlocks>
      <BoltGrids>
        <BoltGrid>
          <Id>30</Id>
          <Name>Anchors</Name>
          <OriginalModelId>30</OriginalModelId>
          <BoltAssemblyName>M20</BoltAssemblyName>
          <IsAnchor>true</IsAnchor>
          <Length>0.4</Length>
          <Origin><Id>0</Id><X>0</X><Y>0</Y><Z>0</Z></Origin>
          <AxisX><X>1</X><Y>0</Y><Z>0</Z></AxisX>
          <AxisY><X>0</X><Y>1</Y><Z>0</Z></AxisY>
          <AxisZ><X>0</X><Y>0</Y><Z>1</Z></AxisZ>
          <Positions>
            <Point3D><Id>1</Id><X>0</X><Y>-0.075</Y><Z>-0.15</Z></Point3D>
            <Point3D><Id>2</Id><X>0</X><Y>-0.075</Y><Z>-0.05</Z></Point3D>
            <Point3D><Id>3</Id><X>0</X><Y>-0.075</Y><Z>0.05</Z></Point3D>
            <Point3D><Id>4</Id><X>0</X><Y>-0.075</Y><Z>0.15</Z></Point3D>
            <Point3D><Id>5</Id><X>0</X><Y>0.075</Y><Z>-0.15</Z></Point3D>
            <Point3D><Id>6</Id><X>0</X><Y>0.075</Y><Z>-0.05</Z></Point3D>
            <Point3D><Id>7</Id><X>0</X><Y>0.075</Y><Z>0.05</Z></Point3D>
            <Point3D><Id>8</Id><X>0</X><Y>0.075</Y><Z>0.15</Z></Point3D>
          </Positions>
          <ConnectedPartIds>
            <string>10</string>
            <string>2</string>
          </ConnectedPartIds>
        </BoltGrid>
      </BoltGrids>'''
    content = content[:cb_end] + bolt_grid_xml + content[cb_end+len('</ConcreteBlocks>'):]
    print("BoltGrid added")

# --- 4. Fix beam CrossSectionType and add ConnectedMember refs ---
# The original had BeamData with CrossSectionType but no ConnectedMember
# Let's add ConnectedMember reference to each BeamData
for bt_name, bt_id in [("Pedestal", "1"), ("Columna", "2")]:
    bt_start = content.find(f'<BeamData>\n          <Id>{bt_id}</Id>')
    if bt_start >= 0:
        bt_end = content.find('</BeamData>', bt_start) + len('</BeamData>')
        conn_member = f'\n          <ConnectedMember><TypeName>ConnectedMember</TypeName><Id>{bt_id}</Id></ConnectedMember>'
        if '<ConnectedMember>' not in content[bt_start:bt_end]:
            content = content[:bt_end] + conn_member + content[bt_end:]

# Save
new_iom_path = r"C:\Users\aintc\AppData\Local\Temp\opencode\col109_fixed_iom.xml"
with open(new_iom_path, 'w', encoding='utf-16') as f:
    f.write(content)

print(f"\nFixed IOM saved: {os.path.getsize(new_iom_path)} bytes")

# Verify
content2 = open(new_iom_path, 'r', encoding='utf-16').read()
print("Has OutlinePoints:", "OutlinePoints" in content2)
print("Has BoltGrid:", "BoltGrid" in content2)
print("Has BoltAssembly:", "BoltAssembly" in content2)
print("Has MatBoltGrade:", "MatBoltGrade" in content2)
print("Has IsAnchor:", "IsAnchor>true" in content2)

# Now try CreateConProjFromIOM
factory = plug.ConnHiddenClientFactory(idea_dir)
client = factory.Create()

results_path = r"C:\Users\aintc\AppData\Local\Temp\opencode\col109_results.xmlR"
out_path = r"C:\Users\aintc\AppData\Local\Temp\opencode\col109_fixed_test.ideaCon"

# Create empty results file
with open(results_path, "w", encoding="utf-16") as f:
    f.write('<?xml version="1.0" encoding="utf-16"?><OpenModelResult xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" />')

try:
    print("\n=== CreateConProjFromIOM ===")
    result = client.CreateConProjFromIOM(new_iom_path, results_path, out_path)
    print("Create result:", result)
    print("Created:", os.path.exists(out_path), "| Size:", os.path.getsize(out_path) if os.path.exists(out_path) else 0)

    print("\n=== OpenProject ===")
    client.OpenProject(out_path)
    info = client.GetProjectInfo()
    print("Project:", info.Name, "| Code:", info.DesignCode)
    conn_id = info.Connections[0].Identifier

    print("\n=== GetConnectionModel ===")
    cm = client.GetConnectionModel(conn_id)
    print("  Beams:", len(cm.Beams) if cm.Beams else 0)
    print("  Plates:", len(cm.Plates) if cm.Plates else 0)
    print("  ConcreteBlocks:", len(cm.ConcreteBlocks) if cm.ConcreteBlocks else 0)
    for cb in cm.ConcreteBlocks or []:
        print("    Block:", cb.Name, "| Depth:", cb.Depth, "| Mat:", cb.Material)
    print("  BoltGrids:", len(cm.BoltGrids) if cm.BoltGrids else 0)
    for bg in cm.BoltGrids or []:
        print("    Grid:", bg.Name, "| BoltAssemblyName:", bg.BoltAssemblyName, "| IsAnchor:", bg.IsAnchor, "| Count:", len(bg.Positions) if bg.Positions else 0)
    print("  Welds:", len(cm.Welds) if cm.Welds else 0)

    print("\n=== Calculate ===")
    calc_result = client.Calculate(conn_id)
    ccr = calc_result.ConnectionCheckRes
    print("  CheckRes count:", len(ccr) if ccr else 0)
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
    import traceback
    traceback.print_exc()
finally:
    try: client.CloseProject()
    except: pass