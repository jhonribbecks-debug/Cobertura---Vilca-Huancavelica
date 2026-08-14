import clr, os, sys, json

idea_dir = r"C:\Program Files\IDEA StatiCa\StatiCa 20.1"
sys.path.append(idea_dir)

clr.AddReference(os.path.join(idea_dir, "IdeaStatiCa.Plugin"))
import IdeaStatiCa.Plugin as plug
clr.AddReference(os.path.join(idea_dir, "IdeaRS.OpenModel.dll"))
import IdeaRS.OpenModel as om
import IdeaRS.OpenModel.Connection as conn

factory = plug.ConnHiddenClientFactory(idea_dir)
client = factory.Create()

project = r"C:\Users\aintc\OneDrive\Escritorio\Tenorious\Coneccion plancha base.ideaCon"
template_path = r"C:\Users\aintc\AppData\Local\Temp\opencode\manual_template.xml"

try:
    print("=== OpenProject ===")
    client.OpenProject(project)
    info = client.GetProjectInfo()
    print("Project:", info.Name, "| Code:", info.DesignCode)
    conn_id = info.Connections[0].Identifier
    print("Connection:", info.Connections[0].Name, "| Id:", conn_id)

    # Read template XML
    with open(template_path, "r", encoding="utf-16") as f:
        template_content = f.read()
    print("\nTemplate length:", len(template_content))

    # Create ApplyConnTemplateSetting
    settings = conn.ApplyConnTemplateSetting()
    
    print("\n=== ApplyTemplate ===")
    result = client.ApplyTemplate(conn_id, template_content, settings)
    print("ApplyTemplate result:", result)

    # Save the modified project
    output_path = r"C:\Users\aintc\AppData\Local\Temp\opencode\project_with_concrete.ideaCon"
    print("\n=== SaveAsProject ===")
    save_result = client.SaveAsProject(output_path)
    print("SaveAsProject result:", save_result)

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