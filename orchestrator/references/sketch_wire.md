# sketch_wire.md — wire closure and arc endpoints (FreeCAD facts)

Scope: Sketcher geometry, Part edges/wires, Pad input. Only what the
geometry API does and which numeric signature each failure has.

## Symptom -> cause index
| Symptom | Likely cause | Section |
|---|---|---|
| Pad returns null shape | Open wire: ≥1 gap between consecutive edges | §1, §4 |
| Pad input has 2 wires, not 1 | One gap exceeds OCC tolerance, splitting the loop | §1 |
| Arc foot does not meet diagonal | Arc endpoints computed from angle, not shared points | §2 |
| Face looks right but wire count > 1 | Endpoint gap 1e-6..1e-5: invisible, still open | §1 |
| Wire closes in GUI but not headless | GUI snap hid the gap; headless keeps exact coords | §2 |

## 1. Closure and the OCC tolerance
- A Pad profile must be one closed wire: every edge end coincides
  with the next edge start, last end = first start.
- Wire check: `Part.Wire(edges).isClosed()` must be `True`;
  `sketch.Shape.Wires` count must be 1 for a single profile.
- OCC wire tolerance is 1e-7 mm. A gap larger than 1e-7 is NOT closed,
  however small it looks.
- Observed case: angle-built R0.8 arc endpoints missed the rounded
  diagonal feet by 8.8e-6 mm — 88x the tolerance. Result: 2 open wires,
  Pad null. 8.8e-6 is invisible at any normal zoom; only the wire
  count / `isClosed()` exposes it.
- Rounding coordinates to 2-3 decimals does NOT fix a gap: it moves
  it. Fix the endpoint source (§2), not the display precision.
- Diagnostic numbers per profile: `len(wires)`, `wire.isClosed()`,
  max endpoint-to-next-start distance. Max gap > 1e-7 = open, full stop.

## 2. ArcOfCircle vs 3-point Arc
- `Part.ArcOfCircle(Part.Circle(center, normal, radius), a1, a2)`:
  endpoints are *derived* from center + radius + angles a1, a2 (radians).
  Any rounding in center/radius/angle shifts both endpoints, so the arc
  can miss a neighbour edge even when the math "looks" exact.
- `Part.Arc(p_start, p_mid, p_end)`: the arc passes exactly through
  the three given points. Endpoints are inputs, not results.
- Fix for the 8.8e-6 case: 3-point arc through the two shared
  endpoints (the points already used by the neighbouring edges).
- In a sketch the same idea is a Coincident constraint, not a
  coordinate copy: see constraint_solver.md. Equal-looking numbers
  do not join edges; only a shared point / Coincident holds them.
- Point-position codes (Sketcher): line/arc start = 1, end = 2,
  circle/arc centre = 3. Sketch axes: -1 = X axis (its point 1 is the
  origin), -2 = Y axis.

## 3. Geometry constructors (exact forms)
```
import Part, FreeCAD as App
V = App.Vector
line = Part.LineSegment(V(x1,y1,0), V(x2,y2,0))
circ = Part.Circle(V(cx,cy,0), V(0,0,1), radius)
arcA = Part.ArcOfCircle(circ, a_start_rad, a_end_rad)  # endpoints derived
arc3 = Part.Arc(V(x1,y1,0), V(xm,ym,0), V(x2,y2,0))    # endpoints exact
sketch.addGeometry(line, False)   # False = normal geometry, not construction
sketch.addGeometry(arc3, False)
```
- `addGeometry(..., True)` = construction geometry: never part of
  the profile wire. A profile edge flagged construction yields an
  open/missing wire with no solver error.
- Angles for ArcOfCircle are radians from the circle's local X
  direction; a degree value passed as radians gives a wildly wrong arc.

## 4. Example: closed profile with a 3-point round
```
# P0..P3 are shared by the lines; the arc reuses P1, P2 as endpoints.
P0 = V(0.0, 0.0, 0); P1 = V(10.0, 0.0, 0)
P2 = V(10.0, 5.0, 0); P3 = V(0.0, 5.0, 0)
sketch.addGeometry(Part.LineSegment(P0, P1), False)          # geo 0
sketch.addGeometry(Part.LineSegment(P1, P2), False)          # geo 1
sketch.addGeometry(Part.LineSegment(P2, P3), False)          # geo 2
sketch.addGeometry(Part.LineSegment(P3, P0), False)          # geo 3
mid = V(9.6, 4.6, 0)  # a point on the intended round, between its ends
sketch.addGeometry(Part.Arc(P1, mid, P2), False)  # NOT ArcOfCircle here
wire = Part.Wire(sketch.Shape.Edges)
assert wire.isClosed() and len(sketch.Shape.Wires) == 1
```
- If the arc must keep an exact radius R, derive its mid point from
  the same endpoints + R, then still pass the endpoints through
  `Part.Arc`. Radius-first ArcOfCircle re-derives the endpoints and
  re-opens the 8.8e-6 class of gap.

## 5. Numbers
| Quantity | Value |
|---|---|
| OCC wire-join tolerance | 1e-7 mm |
| Observed failing gap (R0.8 arc feet) | 8.8e-6 mm (88x tolerance) |
| Result of that gap | 2 open wires -> Pad null |
| Required, single profile | 1 wire, `isClosed() == True` |
| ArcOfCircle angle unit | radians, not degrees |
