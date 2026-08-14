import clr, os, sys
idea_dir = r"C:\Program Files\IDEA StatiCa\StatiCa 20.1"
sys.path.append(idea_dir)
clr.AddReference(os.path.join(idea_dir, "IdeaRS.OpenModel.dll"))
import IdeaRS.OpenModel as om
import IdeaRS.OpenModel.Connection as conn

# Check ConcreteBlockData properties
cbd_type = conn.ConcreteBlockData
print("=== ConcreteBlockData ===")
print("Type:", cbd_type)
props = [p for p in dir(cbd_type) if not p.startswith('_')]
print("Properties:", props)

# Create an instance and check
cbd = conn.ConcreteBlockData()
print("\nDefault instance properties:")
for p in props:
    try:
        val = getattr(cbd, p)
        print(f"  {p}: {val}")
    except Exception as e:
        print(f"  {p}: ERROR - {e}")

# Check BasePlateData too
print("\n=== BasePlateData ===")
bpd = conn.BasePlateData()
bpd_props = [p for p in dir(bpd) if not p.startswith('_')]
print("Properties:", bpd_props)