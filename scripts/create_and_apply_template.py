import clr, os, sys, json

idea_dir = r"C:\Program Files\IDEA StatiCa\StatiCa 20.1"
sys.path.append(idea_dir)

# Create a proper template XML for column base with concrete block + 8 anchors M20 + loads
template_xml = '''<?xml version="1.0" encoding="utf-16"?>
<ConnectionTemplate xmlns:i="http://www.w3.org/2001/XMLSchema-instance" xmlns="http://schemas.datacontract.org/2004/07:IdeaRS.Connections.Data">
  <Criteria i:nil="true" />
  <Name i:nil="true" />
  <Parameters xmlns:d2p1="http://schemas.microsoft.com/2003/10/Serialization/Arrays" />
  <ParametersModelLinks xmlns:d2p1="http://schemas.microsoft.com/2003/10/Serialization/Arrays" />
  <Properties>
    <Items xmlns:d3p1="http://schemas.microsoft.com/2003/10/Serialization/Arrays">
      <d3p1:KeyValueOfintConnectionCmdData62S_SxYjN>
        <d3p1:Key>1</d3p1:Key>
        <d3p1:Value i:type="BasePlateData">
          <Name>BP1</Name>
          <OperationId>1</OperationId>
          <PlateMaterialName i:nil="true" />
          <ShapeData xmlns:d6p1="http://schemas.datacontract.org/2004/07/IdeaRS.Connections.Data.PlateEditor">
            <d6p1:PlateEditorData>
              <d6p1:CountEdge>0</d6p1:CountEdge>
              <d6p1:IsWeldEdge>false</d6p1:IsWeldEdge>
              <d6p1:Operations />
              <d6p1:PartType>BasePlate</d6p1:PartType>
            </d6p1:PlateEditorData>
          </ShapeData>
          <Thickness>0.02</Thickness>
          <Anchoring>
            <Name></Name>
            <OperationId>0</OperationId>
            <AnchorLength>0.1</AnchorLength>
            <AnchorName i:nil="true" />
            <AnchorTypeData>Straight</AnchorTypeData>
            <AnchorTypeDataSize>0.1</AnchorTypeDataSize>
            <Angles i:nil="true" />
            <ApplyBoltShearType>Bearing</ApplyBoltShearType>
            <CircularLayerRadius i:nil="true" />
            <Cols i:nil="true" />
            <CustomLcsAngle>0</CustomLcsAngle>
            <CustomReferencePoint i:nil="true" />
            <CustomReferencePointPosition>Default</CustomReferencePointPosition>
            <EditorData xmlns:d7p1="http://schemas.datacontract.org/2004/07/IdeaRS.Connections.Data.PlateEditor" i:nil="true" />
            <GridType>Regular</GridType>
            <HorizontalGridLinesBottom>
              <d3p1:double>0.02</d3p1:double>
            </HorizontalGridLinesBottom>
            <HorizontalGridLinesTop>
              <d3p1:double>0.02</d3p1:double>
            </HorizontalGridLinesTop>
            <NumberOfAnchorsCL i:nil="true" />
            <PositionType>Default</PositionType>
            <ReferencePointPosition>Center</ReferencePointPosition>
            <Rows i:nil="true" />
            <ShearPlaneThread>true</ShearPlaneThread>
            <VerticalGridLinesLeft>
              <d3p1:double>0.02</d3p1:double>
            </VerticalGridLinesLeft>
            <VerticalGridLinesRight>
              <d3p1:double>0.02</d3p1:double>
            </VerticalGridLinesRight>
          </Anchoring>
          <BasePlateContact>Direct</BasePlateContact>
          <ColumnPath>BeamByOperationId(1)</ColumnPath>
          <CoordSystem>ParentCss</CoordSystem>
          <Fastening>
            <Name></Name>
            <OperationId>0</OperationId>
            <AnchorLength>0.3</AnchorLength>
            <AnchorTypeData>Straight</AnchorTypeData>
            <AnchorTypeDataSize>0.1</AnchorTypeDataSize>
            <Angle>0</Angle>
            <Angles xmlns:d7p1="http://schemas.microsoft.com/2003/10/Serialization/Arrays">
              <d7p1:ArrayOfValueCount>
                <d7p1:ValueCount><d7p1:Count>1</d7p1:Count><d7p1:Value>0</d7p1:Value></d7p1:ValueCount>
                <d7p1:ValueCount><d7p1:Count>7</d7p1:Count><d7p1:Value>0.78539816339744828</d7p1:Value></d7p1:ValueCount>
              </d7p1:ArrayOfValueCount>
            </Angles>
            <BoltEndOffset>0</BoltEndOffset>
            <BoltInteraction>Interaction</BoltInteraction>
            <BoltStartOffest>0</BoltStartOffest>
            <Cols xmlns:d7p1="http://schemas.microsoft.com/2003/10/Serialization/Arrays">
              <d7p1:ArrayOfValueCount>
                <d7p1:ValueCount><d7p1:Count>1</d7p1:Count><d7p1:Value>0.04</d7p1:Value></d7p1:ValueCount>
              </d7p1:ArrayOfValueCount>
            </Cols>
            <ColsGridType>Regular</ColsGridType>
            <ColsNegative xmlns:d7p1="http://schemas.microsoft.com/2003/10/Serialization/Arrays">
              <d7p1:ArrayOfValueCount>
                <d7p1:ValueCount><d7p1:Count>1</d7p1:Count><d7p1:Value>0.02</d7p1:Value></d7p1:ValueCount>
              </d7p1:ArrayOfValueCount>
            </ColsNegative>
            <ColsPosition>Profile</ColsPosition>
            <ColsSymmetry>Symmetrical</ColsSymmetry>
            <CoordinateSystem>Cartesian</CoordinateSystem>
            <Counts>
              <d3p1:int>8</d3p1:int>
            </Counts>
            <CustomLcsAngle>0</CustomLcsAngle>
            <CustomLcsPoint xmlns:d7p1="http://schemas.datacontract.org/2004/07:System.Windows">
              <d7p1:_x>0</d7p1:_x>
              <d7p1:_y>0</d7p1:_y>
            </CustomLcsPoint>
            <EditorData xmlns:d7p1="http://schemas.datacontract.org/2004/07/IdeaRS.Connections.Data.PlateEditor">
              <d7p1:BoltGrids />
            </EditorData>
            <FastenerName>M20</FastenerName>
            <IsCustomLcs>false</IsCustomLcs>
            <PolarInput>ByCount</PolarInput>
            <PolarPosition>Axis</PolarPosition>
            <Positions xmlns:d7p1="http://schemas.datacontract.org/2004/07:System.Windows" i:nil="true" />
            <Radii xmlns:d7p1="http://schemas.microsoft.com/2003/10/Serialization/Arrays">
              <d7p1:ArrayOfValueCount>
                <d7p1:ValueCount><d7p1:Count>1</d7p1:Count><d7p1:Value>0.05</d7p1:Value></d7p1:ValueCount>
              </d7p1:ArrayOfValueCount>
            </Radii>
            <Rows xmlns:d7p1="http://schemas.microsoft.com/2003/10/Serialization/Arrays">
              <d7p1:ArrayOfValueCount>
                <d7p1:ValueCount><d7p1:Count>1</d7p1:Count><d7p1:Value>0.04</d7p1:Value></d7p1:ValueCount>
              </d7p1:ArrayOfValueCount>
            </Rows>
            <RowsGridType>Regular</RowsGridType>
            <RowsNegative xmlns:d7p1="http://schemas.microsoft.com/2003/10/Serialization/Arrays">
              <d7p1:ArrayOfValueCount>
                <d7p1:ValueCount><d7p1:Count>1</d7p1:Count><d7p1:Value>0.02</d7p1:Value></d7p1:ValueCount>
              </d7p1:ArrayOfValueCount>
            </RowsNegative>
            <RowsPosition>Profile</RowsPosition>
            <RowsSymmetry>Symmetrical</RowsSymmetry>
            <ShearPlaneThread>true</ShearPlaneThread>
          </Fastening>
          <FlangesWeld>
            <BeginOffset>0</BeginOffset>
            <EndOffset>0</EndOffset>
            <IntermittentGap>0</IntermittentGap>
            <IntermittentLength>0</IntermittentLength>
            <Size>0</Size>
            <WeldMaterialName i:nil="true" />
            <WeldType>DoubleFillet</WeldType>
          </FlangesWeld>
          <FoundationBlockHeight>0.5</FoundationBlockHeight>
          <FoundationBlockOffset>0.3</FoundationBlockOffset>
          <InnerRadius>0</InnerRadius>
          <IsWeld>true</IsWeld>
          <MatConcreteName>#2</MatConcreteName>
          <MortarJoint>false</MortarJoint>
          <MortarJointThickness>0</MortarJointThickness>
          <OffsetBottom>0.08</OffsetBottom>
          <OffsetLeft>0.08</OffsetLeft>
          <OffsetRight>0.08</OffsetRight>
          <OffsetTop>0.08</OffsetTop>
          <Orientation>Perpendicular</Orientation>
          <OuterRadius>0.3</OuterRadius>
          <PlateSizeMethod>ToProfileSymmetrical</PlateSizeMethod>
          <RotationOnZ>0</RotationOnZ>
          <ShearForceTransfer>Shear</ShearForceTransfer>
          <ShearIronCssName i:nil="true" />
          <ShearIronLength>0</ShearIronLength>
          <ShearIronPosition xmlns:d6p1="http://schemas.datacontract.org/2004/07:System.Windows">
            <d6p1:_x>0</d6p1:_x>
            <d6p1:_y>0</d6p1:_y>
          </ShearIronPosition>
          <ShearIronRotation>0</ShearIronRotation>
          <ShearLugFlangesWeld>
            <BeginOffset>0</BeginOffset>
            <EndOffset>0</EndOffset>
            <IntermittentGap>0</IntermittentGap>
            <IntermittentLength>0</IntermittentLength>
            <Size>0</Size>
            <WeldMaterialName i:nil="true" />
            <WeldType>DoubleFillet</WeldType>
          </ShearLugFlangesWeld>
          <ShearLugWebsWeld>
            <BeginOffset>0</BeginOffset>
            <EndOffset>0</EndOffset>
            <IntermittentGap>0</IntermittentGap>
            <IntermittentLength>0</IntermittentLength>
            <Size>0</Size>
            <WeldMaterialName i:nil="true" />
            <WeldType>DoubleFillet</WeldType>
          </ShearLugWebsWeld>
          <Weld>
            <BeginOffset>0</BeginOffset>
            <EndOffset>0</EndOffset>
            <IntermittentGap>0</IntermittentGap>
            <IntermittentLength>0</IntermittentLength>
            <Size>0</Size>
            <WeldMaterialName i:nil="true" />
            <WeldType>DoubleFillet</WeldType>
          </Weld>
        </d3p1:Value>
      </d3p1:KeyValueOfintConnectionCmdData62S_SxYjN>
    </Items>
  </Properties>
  <Sequence>
    <Operations>
      <ManufacturingOperationData>
        <CommandId>56f869bd-ee80-473a-ba50-ba63d11b1268</CommandId>
        <ParameterId>1</ParameterId>
      </ManufacturingOperationData>
    </Operations>
  </Sequence>
  <TemplateId>6cd989c7-f74f-4233-aedb-9a68b4ae0464</TemplateId>
  <TopologyCode>0</TopologyCode>
  <Version>26</Version>
</ConnectionTemplate>
'''

# Write the template XML
with open("custom_baseplate_template.xml", "w", encoding="utf-16") as f:
    f.write(template_xml)
print("Template written, length:", len(template_xml))

# Now try to apply it
clr.AddReference(os.path.join(idea_dir, "IdeaStatiCa.Plugin"))
import IdeaStatiCa.Plugin as plug
clr.AddReference(os.path.join(idea_dir, "IdeaRS.OpenModel.dll"))
import IdeaRS.OpenModel as om
import IdeaRS.OpenModel.Connection as conn

factory = plug.ConnHiddenClientFactory(idea_dir)
client = factory.Create()

project = r"C:\Users\aintc\OneDrive\Escritorio\Tenorious\Coneccion plancha base.ideaCon"

try:
    print("\n=== OpenProject ===")
    client.OpenProject(project)
    info = client.GetProjectInfo()
    conn_id = info.Connections[0].Identifier
    print("Connection:", conn_id)

    settings = conn.ApplyConnTemplateSetting()
    
    print("\n=== ApplyTemplate ===")
    result = client.ApplyTemplate(conn_id, template_xml, settings)
    print("ApplyTemplate result:", result)

    print("\n=== Calculate after template ===")
    calc_result = client.Calculate(conn_id)
    ccr = calc_result.ConnectionCheckRes
    print("CheckRes count:", len(ccr))
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
    try: 
        client.CloseProject()
    except: 
        pass