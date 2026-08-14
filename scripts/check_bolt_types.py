import clr, os, sys
idea_dir = r"C:\Program Files\IDEA StatiCa\StatiCa 20.1"
sys.path.append(idea_dir)
clr.AddReference(os.path.join(idea_dir, "IdeaRS.OpenModel.dll"))
import IdeaRS.OpenModel as om

# Check IdeaRS.OpenModel for BoltAssembly, MaterialBoltGrade
print("=== IdeaRS.OpenModel types ===")
namespace_types = [x for x in dir(om) if not x.startswith('_')]
bolt_related = [x for x in namespace_types if 'olt' in x or 'Bolt' in x or 'Grade' in x]
print("Bolt/Grade related:", bolt_related)

# Check if BoltAssembly exists
print("\nBoltAssembly:", om.BoltAssembly)
print("MaterialBoltGrade:", om.MaterialBoltGrade)

# Create a test instance
ba = om.BoltAssembly()
print("\nBoltAssembly props:", [x for x in dir(ba) if not x.startswith('_')])

bg = om.MaterialBoltGrade()
print("\nMaterialBoltGrade props:", [x for x in dir(bg) if not x.startswith('_')])

# Check OpenModel collections for bolt assembly
m = om.OpenModel()
print("\nOpenModel collections:", [x for x in dir(m) if not x.startswith('_') and not callable(getattr(m, x, None))])