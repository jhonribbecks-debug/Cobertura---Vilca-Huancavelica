import clr, os, sys
idea_dir = r"C:\Program Files\IDEA StatiCa\StatiCa 20.1"
sys.path.append(idea_dir)
clr.AddReference(os.path.join(idea_dir, "IdeaRS.OpenModel.dll"))
import IdeaRS.OpenModel as om

# Check OriginSettings properties
print("=== OriginSettings properties ===")
os_type = om.OriginSettings
props = [p for p in dir(os_type) if not p.startswith('_')]
print(props)

# Check CountryCode enum
print("\n=== CountryCode ===")
print(type(om.CountryCode))
members = [x for x in dir(om.CountryCode) if not x.startswith('_')]
print("Members:", members)

# Check if ECEN exists
print("\nECEN value:", om.CountryCode.ECEN)