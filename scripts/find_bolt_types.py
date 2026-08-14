import clr, os, sys
idea_dir = r"C:\Program Files\IDEA StatiCa\StatiCa 20.1"
sys.path.append(idea_dir)
clr.AddReference(os.path.join(idea_dir, "IdeaRS.OpenModel.dll"))

# Check all namespaces for BoltAssembly
import System
# Find types containing "Bolt"
from System import Reflection
asm = Reflection.Assembly.LoadFrom(os.path.join(idea_dir, "IdeaRS.OpenModel.dll"))
for t in asm.GetTypes():
    if 'olt' in t.Name:
        print(f"Found: {t.FullName} in {t.Namespace}")
        props = [p.Name for p in t.GetProperties()]
        print(f"  Properties: {props[:20]}")