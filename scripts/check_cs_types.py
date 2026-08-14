import clr, os, sys
idea_dir = r"C:\Program Files\IDEA StatiCa\StatiCa 20.1"
sys.path.append(idea_dir)
clr.AddReference(os.path.join(idea_dir, "IdeaRS.OpenModel.dll"))
import IdeaRS.OpenModel as om
import IdeaRS.OpenModel.CrossSection as cs

# Check CrossSectionType members
print("=== CrossSectionType members ===")
members = [x for x in dir(cs.CrossSectionType) if not x.startswith('_')]
print(members)

# Check CrossSectionParameter
print("\n=== CrossSectionParameter ===")
props = [x for x in dir(cs.CrossSectionParameter) if not x.startswith('_')]
print(props)

# Check Param
print("\n=== CrossSectionParameter.Param ===")
try:
    p = cs.CrossSectionParameter.Param("B", 0.2)
    print("Param created:", p)
    print("Param properties:", [x for x in dir(p) if not x.startswith('_')])
except Exception as e:
    print("Param error:", e)

# Check if Rectangle exists
print("\n=== Check for Rect types ===")
rect_members = [x for x in dir(cs) if 'rect' in x.lower() or 'rhs' in x.lower() or 'box' in x.lower()]
print("Rect/RHS related:", rect_members)