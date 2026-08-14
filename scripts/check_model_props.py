import clr, os, sys
idea_dir = r"C:\Program Files\IDEA StatiCa\StatiCa 20.1"
sys.path.append(idea_dir)
clr.AddReference(os.path.join(idea_dir, "IdeaRS.OpenModel.dll"))
import IdeaRS.OpenModel as om

print("=== OpenModel collections ===")
props = [p for p in dir(om.OpenModel) if not p.startswith('_')]
# Filter for collections
collections = [p for p in props if not callable(getattr(om.OpenModel, p, None)) or hasattr(getattr(om.OpenModel, p, None), 'Add')]
print("All props:", props)

# Check what type each is
for p in props:
    try:
        attr = getattr(om.OpenModel, p)
        if hasattr(attr, '__doc__') or not callable(attr):
            pass
    except:
        pass

# Let's check for MatBoltGrade
print("\nHas MatBoltGrade:", hasattr(om.OpenModel, 'MatBoltGrade'))
print("Has MatReinforcement:", hasattr(om.OpenModel, 'MatReinforcement'))
print("Has MatConcrete:", hasattr(om.OpenModel, 'MatConcrete'))
print("Has MatSteel:", hasattr(om.OpenModel, 'MatSteel'))
print("Has BoltAssembly:", hasattr(om.OpenModel, 'BoltAssembly'))
print("Has Materials:", hasattr(om.OpenModel, 'Materials'))

# Check MaterialBoltGrade location
import IdeaRS.OpenModel.Material as mat
print("\nMaterial namespace types:", [x for x in dir(mat) if 'Bolt' in x or 'Grade' in x])