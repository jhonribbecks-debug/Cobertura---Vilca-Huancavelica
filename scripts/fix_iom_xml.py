import os, sys, xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from project_paths import out_dir  # noqa: E402

idea_dir = r"C:\Program Files\IDEA StatiCa\StatiCa 20.1"
sys.path.append(idea_dir)

# Read the working IOM file
iom_path = os.path.join(out_dir(), "col109_final_iom.xml")
content = open(iom_path, 'r', encoding='utf-16').read()

# Find the ConcreteBlockData section
# Our original had:
#   <ConcreteBlockData>
#     <Id>20</Id>
#     <Name>PedestalBlock</Name>
#     <Depth>0.5</Depth>
#     <Material>C25/30</Material>
#     <Center>...</Center>
#     <OriginalModelId>20</OriginalModelId>
#   </ConcreteBlockData>

# Replace it with the correct version including all properties
old_cb = '''<ConcreteBlockData>
          <Id>20</Id>
          <Name>PedestalBlock</Name>
          <Depth>0.5</Depth>
          <Material>C25/30</Material>
          <Center>
            <Id>0</Id>
            <X>0</X>
            <Y>0</Y>
            <Z>-0.85</Z>
          </Center>
          <OriginalModelId>20</OriginalModelId>
        </ConcreteBlockData>'''

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
            <Point2D>
              <X>0.25</X>
              <Y>0.25</Y>
            </Point2D>
            <Point2D>
              <X>-0.25</X>
              <Y>0.25</Y>
            </Point2D>
            <Point2D>
              <X>-0.25</X>
              <Y>-0.25</Y>
            </Point2D>
            <Point2D>
              <X>0.25</X>
              <Y>-0.25</Y>
            </Point2D>
          </OutlinePoints>
          <AxisX>
            <X>1</X>
            <Y>0</Y>
            <Z>0</Z>
          </AxisX>
          <AxisY>
            <X>0</X>
            <Y>1</Y>
            <Z>0</Z>
          </AxisY>
          <AxisZ>
            <X>0</X>
            <Y>0</Y>
            <Z>1</Z>
          </AxisZ>
          <Center>
            <Id>0</Id>
            <X>0</X>
            <Y>0</Y>
            <Z>-0.425</Z>
          </Center>
          <Region>M 0 0 L 0.5 0 L 0.5 0.5 L 0 0.5 L 0 0</Region>
        </ConcreteBlockData>'''

# Replace
if old_cb in content:
    content = content.replace(old_cb, new_cb)
    print("ConcreteBlockData replaced successfully")
else:
    print("WARNING: Could not find old ConcreteBlockData")
    # Check what's there
    idx = content.find('ConcreteBlock')
    if idx >= 0:
        print("Found ConcreteBlock at:", idx)
        print(content[idx:idx+500])

# Now add BoltGrid before ConcreteBlocks closing tag
# Find </ConcreteBlocks> and add BoltGrids after it
bolt_grid_xml = '''</ConcreteBlocks>
      <BoltGrids>
        <BoltGrid>
          <Id>30</Id>
          <Name>Anchors</Name>
          <OriginalModelId>30</OriginalModelId>
          <BoltAssemblyName>M20</BoltAssemblyName>
          <IsAnchor>true</IsAnchor>
          <Length>0.4</Length>
          <Origin>
            <Id>0</Id>
            <X>0</X>
            <Y>0</Y>
            <Z>0</Z>
          </Origin>
          <AxisX>
            <X>1</X>
            <Y>0</Y>
            <Z>0</Z>
          </AxisX>
          <AxisY>
            <X>0</X>
            <Y>1</Y>
            <Z>0</Z>
          </AxisY>
          <AxisZ>
            <X>0</X>
            <Y>0</Y>
            <Z>1</Z>
          </AxisZ>
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

content = content.replace('</ConcreteBlocks>', bolt_grid_xml)

# Add MaterialBoltGrade and BoltAssembly to materials section
# Find </MatReinforcement> and add after it
bolt_grade_xml = '''<MatReinforcement />
  <MatBoltGrade>
    <MaterialBoltGrade>
      <Id>1</Id>
      <Name>8.8</Name>
      <LoadFromLibrary>true</LoadFromLibrary>
      <IsDefaultMaterial>false</IsDefaultMaterial>
      <OrderInCode>0</OrderInCode>
    </MaterialBoltGrade>
  </MatBoltGrade>'''

if '<MatBoltGrade>' not in content:
    content = content.replace('<MatReinforcement />', bolt_grade_xml.replace('</MatReinforcement>', '<MatReinforcement />'))
    print("MatBoltGrade added")
else:
    print("MatBoltGrade already exists")

# Add BoltAssembly to cross-section area (after last CrossSection)
bolt_assembly_xml = '''</CrossSection>
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

# Check for BoltAssembly
if '<BoltAssembly' not in content and '<BoltAssemblies' not in content:
    content = content.replace('</CrossSection>', bolt_assembly_xml)
    print("BoltAssembly added")
else:
    print("BoltAssembly already exists")

# Save
new_iom_path = os.path.join(out_dir(), "col109_fixed_iom.xml")
with open(new_iom_path, 'w', encoding='utf-16') as f:
    f.write(content)

print(f"\nFixed IOM saved: {os.path.getsize(new_iom_path)} bytes")

# Verify
content2 = open(new_iom_path, 'r', encoding='utf-16').read()
print("Has OutlinePoints:", "OutlinePoints" in content2)
print("Has BoltGrid:", "BoltGrid" in content2)
print("Has BoltAssembly:", "BoltAssembly" in content2)
print("Has MatBoltGrade:", "MatBoltGrade" in content2)
print("Has MatConcrete:", "MatConcrete" in content2)