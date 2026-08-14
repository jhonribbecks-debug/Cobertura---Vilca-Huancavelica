import clr, os, sys

idea_dir = r"C:\Program Files\IDEA StatiCa\StatiCa 20.1"
sys.path.append(idea_dir)

clr.AddReference(os.path.join(idea_dir, "IdeaRS.OpenModel.dll"))
clr.AddReference(os.path.join(idea_dir, "IdeaStatiCa.Plugin.dll"))
import IdeaStatiCa.Plugin as plug
import IdeaRS.OpenModel as om

factory = plug.ConnHiddenClientFactory(idea_dir)
client = factory.Create()

# Use the originally created project (col109.ideaCon) which had working geometry
project = r"C:\Users\aintc\AppData\Local\Temp\opencode\col109.ideaCon"

try:
    print("=== OpenProject ===")
    client.OpenProject(project)
    info = client.GetProjectInfo()
    print("Project:", info.Name, "| Code:", info.DesignCode)
    for c in info.Connections:
        conn_id = c.Identifier
        print("  Connection:", c.Name, "| Id:", conn_id)

    print("\n=== Calculate ===")
    calc_result = client.Calculate(conn_id)
    ccr = calc_result.ConnectionCheckRes
    print("CheckRes count:", len(ccr) if ccr else 0)
    if ccr:
        for cr in ccr:
            print("  ConRes:", cr.Name)
            print("  CheckResSummary count:", len(cr.CheckResSummary) if cr.CheckResSummary else 0)
            if cr.CheckResSummary:
                for s in cr.CheckResSummary:
                    print("    ", s.Name, "| Value:", s.CheckValue, "| Status:", s.CheckStatus)
            print("  ConcreteBlock:", len(cr.CheckResConcreteBlock) if cr.CheckResConcreteBlock else 0)
            print("  Anchor:", len(cr.CheckResAnchor) if cr.CheckResAnchor else 0)

except Exception as e:
    import traceback; traceback.print_exc()
finally:
    try: client.CloseProject()
    except: pass