# outline_curve.md — B-spline curves from a traced outline

Scope: `Part.BSplineCurve` construction for smooth, undimensioned
outlines. Only curve API and continuity arithmetic — no scale factor
is stated here, because none generalises across parts.

## Symptom -> cause index
| Symptom | Likely cause | Section |
|---|---|---|
| Curve misses traced points | Poles mistaken for points on the curve | §1 |
| Curve kinks at a joint | Knot multiplicity = degree at an interior knot | §2 |
| Ends do not meet neighbours | End multiplicity < degree+1 (non-periodic) | §2 |
| `buildFromPolesMultsKnots` raises | Pole/knot/mult counts violate the count rule | §2 |
| Smooth outline replaced by arcs | Invented radii fitted where the outline is a spline | §3 |
| Closed outline leaves a seam gap | Periodic flag / first-last pole mismatch | §4 |

## 1. What a B-spline is (poles are NOT on the curve)
- A B-spline is defined by: degree d, poles (= control points),
  knots (parameter values), multiplicities, weights (default 1.0).
  The curve follows the control polygon; it passes through the
  first and last poles ONLY when the end multiplicities are d+1
  (clamped, §2). Interior poles pull the curve but are not on it.
- Do NOT use traced outline points directly as poles and expect
  the curve to pass through them. Two correct routes:
  (a) `interpolate()`: curve passes exactly through given points
  (best for a traced outline); (b) `buildFromPolesMultsKnots()`:
  poles placed by fitting/smoothing, curve approximates them.
- `interpolate` form (verified FreeCAD 1.1.4):
```
bs = Part.BSplineCurve()
bs.interpolate(Points=[V(x1,y1,0), V(x2,y2,0), ...])
bs.interpolate(Points=pts, PeriodicFlag=False, Tolerance=1e-6)
```
  Default continuity C2; `PeriodicFlag=True` closes the curve.
  End tangents optional: `InitialTangent=` + `FinalTangent=`
  (both or neither).
- For a traced outline, interpolate through the traced points, then
  check deviation against the trace — do not hand-place poles to
  "look smooth" and hope.

## 2. buildFromPolesMultsKnots: exact form and count rule
```
bs = Part.BSplineCurve()
bs.buildFromPolesMultsKnots(poles, mults, knots, periodic, degree)
# arg order: poles, mults, knots, periodic, degree, [weights, check]
# verified example (degree 2, non-periodic):
poles = [V(-10,-10,0), V(10,-10,0), V(10,10,0), V(-10,10,0)]
bs.buildFromPolesMultsKnots(poles, (3,1,3), (0,0.5,1), False, 2)
# periodic example (degree 2):
bs.buildFromPolesMultsKnots(poles, (1,1,1,1,1),
                            (0,0.25,0.5,0.75,1), True, 2)
```
- Count rule (non-periodic): `n_poles = sum(mults) - degree - 1`,
  and `n_poles >= 2`. Knots strictly increasing, same length as
  mults, `len >= 2`. Interior mults: 1 <= m <= degree.
- End multiplicity: first and last mults may be degree+1 — and for
  a clamped non-periodic curve they SHOULD be, so the curve starts
  and ends exactly on the first/last poles (neighbour-joining, §4).
- Continuity at a knot: C^(degree - multiplicity). Cubic (d=3):
  interior mult 1 -> C2 (smooth curvature), mult 2 -> C1 (tangent
  only), mult 3 -> C0 (position only = visible kink/corner).
  A kink at a joint therefore means multiplicity too high there,
  not "wrong poles".
- Degree limits: 0 < degree <= MaxDegree (OCC cap 25); traced
  outlines normally use degree 3 (cubic). Higher degree means more
  poles per span and wilder swings, not "smoother".

## 3. Traced outline vs invented radii
- An undimensioned smooth outline segment is a spline, not an arc:
  fitting one radius (or tangent arcs) to a freeform trace invents
  dimensions the drawing never gave. Keep it as the traced spline
  and label it undimensioned-from-trace. A dimensioned radius is
  an arc, not a spline (see sketch_wire.md).
- Smoothing a trace: fewer poles = smoother. A degree-3 spline
  through ~10 well spaced trace points beats a degree-5 spline
  through 50 noisy points; trace noise becomes curve waviness.
- Weights: default 1.0 (non-rational). A weight != 1.0 pulls the
  curve toward that pole and makes it rational; keep 1.0 unless a
  drawing feature (e.g. a true conic segment) needs otherwise.

## 4. Endpoint continuity with neighbours
- Joining a spline to a line/arc: the spline's first/last pole
  (clamped, §2) must be the SAME point as the neighbour's endpoint
  — same vector, or a Coincident constraint in a sketch — not a
  nearby point. A 1e-6-class mismatch is still an open wire under
  the 1e-7 OCC tolerance (see sketch_wire.md).
- Tangent continuity at a join is NOT automatic: clamped ends give
  position (C0) only. Tangent (G1) needs the end tangent along the
  neighbour direction — `InitialTangent`/`FinalTangent` in
  interpolate, or the second pole on the neighbour's tangent line.
- Closed outline: use one periodic spline rather than two open
  splines meeting at a seam; a seam re-introduces the endpoint-gap
  failure at the closure point. If two splines must meet, their
  shared endpoint AND tangent must both match.
- Check per curve: spline StartPoint/EndPoint equal the neighbour
  endpoints within 1e-7, and the edge shape is valid.

## 5. Numbers
| Quantity | Value |
|---|---|
| Count rule, non-periodic | n_poles = sum(mults) - degree - 1 |
| Clamped end multiplicity | degree + 1 (cubic -> 4) |
| Continuity at knot | C^(degree - multiplicity) |
| Cubic, mult 1 / 2 / 3 | C2 / C1 / C0 (kink at 3) |
| Default weights | 1.0 (non-rational) |
| Interpolate tolerance default | 1e-6 |
| Endpoint-join tolerance | 1e-7 (OCC wire tolerance) |
| Typical traced-outline degree | 3 (cubic) |
