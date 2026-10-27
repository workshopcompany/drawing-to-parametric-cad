# Smoke test: build a parametric box (sketch -> pad) and save a real .fcstd.
# Run with: freecadcmd smoke_test.py
import FreeCAD as App
import Part
import Sketcher

DOC_PATH = "/home/hatch/workspace/drawing-to-parametric-cad/models/smoke_test.fcstd"
STEP_PATH = "/home/hatch/workspace/drawing-to-parametric-cad/exports/smoke_test.step"

doc = App.newDocument("SmokeTest")
body = doc.addObject("PartDesign::Body", "Body")
sketch = body.newObject("Sketcher::SketchObject", "Sketch")

V = App.Vector
lines = [
    Part.LineSegment(V(0, 0, 0), V(50, 0, 0)),
    Part.LineSegment(V(50, 0, 0), V(50, 30, 0)),
    Part.LineSegment(V(50, 30, 0), V(0, 30, 0)),
    Part.LineSegment(V(0, 30, 0), V(0, 0, 0)),
]
for ln in lines:
    sketch.addGeometry(ln, False)
for a, b in [(0, 1), (1, 2), (2, 3), (3, 0)]:
    sketch.addConstraint(Sketcher.Constraint("Coincident", a, 2, b, 1))

doc.recompute()
print("sketch wires:", len(sketch.Shape.Wires), "edges:", len(sketch.Shape.Edges))

pad = body.newObject("PartDesign::Pad", "Pad")
pad.Profile = sketch
pad.Length = 10
doc.recompute()

shape = pad.Shape
print("pad valid:", shape.isValid())
print("pad volume:", shape.Volume)
print("pad solids:", len(shape.Solids))
assert shape.isValid(), "pad shape invalid"
assert abs(shape.Volume - 15000.0) < 1.0, "unexpected volume: %s" % shape.Volume

doc.saveAs(DOC_PATH)
print("saved:", DOC_PATH)
shape.exportStep(STEP_PATH)
print("step exported:", STEP_PATH)
print("SMOKE TEST PASSED")
