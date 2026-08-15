import clr, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from project_paths import out_dir  # noqa: E402

idea_dir = r"C:\Program Files\IDEA StatiCa\StatiCa 20.1"
sys.path.append(idea_dir)

clr.AddReference(os.path.join(idea_dir, "IdeaStatiCa.Plugin.dll"))
import IdeaStatiCa.Plugin as plug
clr.AddReference(os.path.join(idea_dir, "IdeaRS.OpenModel.dll"))
import IdeaRS.OpenModel as om
import IdeaRS.OpenModel.Connection as iom_conn

factory = plug.ConnHiddenClientFactory(idea_dir)
client = factory.Create()

project = os.path.join(out_dir(), "from_iom.ideaCon")
template_path = os.path.join(out_dir(), "manual_template.xml")

try:
    print("=== OpenProject from_iom ===")
    client.OpenProject(project)
    info = client.GetProjectInfo()
    conn_id = info.Connections[0].Identifier

    with open(template_path, "r", encoding="utf-16") as f:
        template_content = f.read()

    settings = iom_conn.ApplyConnTemplateSetting()
    
    # ApplySimpleTemplate takes (connId, templateXml, settings, templateId, connectionIdsList)
    template_id = 1
    connection_ids = None  # or a list
    
    print("=== ApplySimpleTemplate (no connection ids) ===")
    try:
        result = client.ApplySimpleTemplate(conn_id, template_content, settings, template_id, None)
        print("Result:", result)
    except Exception as e:
        print("Error:", type(e).__name__, str(e)[:200])

    print("\n=== ApplySimpleTemplate (with empty list) ===")
    try:
        result = client.ApplySimpleTemplate(conn_id, template_content, settings, template_id, SList[int]())
        print("Result:", result)
    except Exception as e:
        print("Error:", type(e).__name__, str(e)[:200])

    print("\n=== Calculate after templates ===")
    calc_result = client.Calculate(conn_id)
    ccr = calc_result.ConnectionCheckRes
    if ccr:
        for cr in ccr:
            print("  ConRes:", cr.Name)
            if cr.CheckResSummary:
                for s in cr.CheckResSummary:
                    print("    ", s.Name, "| Value:", s.CheckValue, "| Status:", s.CheckStatus)
            print("  ConcreteBlock:", len(cr.CheckResConcreteBlock) if cr.CheckResConcreteBlock else 0)

except Exception as e:
    import traceback; traceback.print_exc()
finally:
    try: client.CloseProject()
    except: pass
    
from System.Collections.Generic import List
import System