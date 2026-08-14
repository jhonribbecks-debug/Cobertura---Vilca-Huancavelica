import clr, os, sys
idea_dir = r"C:\Program Files\IDEA StatiCa\StatiCa 20.1"
sys.path.append(idea_dir)
clr.AddReference(os.path.join(idea_dir, "IdeaRS.OpenModel.dll"))

import System
from System import Reflection
asm = Reflection.Assembly.LoadFrom(os.path.join(idea_dir, "IdeaRS.OpenModel.dll"))
for t in asm.GetTypes():
    if 'Cut' in t.Name and 'Orientation' in t.Name:
        print(f"Found: {t.FullName}")
        members = [x for x in dir(t) if not x.startswith('_')]
        print(f"  Members: {members}")
    if 'CutOrientation' in t.Name:
        print(f"Found CutOrientation: {t.FullName}")