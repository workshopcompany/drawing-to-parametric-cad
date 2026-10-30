# constraint_solver.md — Sketcher solver facts: signs, DoF, redundancy

Scope: `Sketcher.Constraint` forms, solver arithmetic, DoF counting.
Only API/syntax behaviour — no build order or workflow policy.

## Symptom -> cause index
| Symptom | Likely cause | Section |
|---|---|---|
| Profile jumps to the opposite side | (point, origin) DistanceX/Y sign read backwards | §1 |
| Profile drags to x≈-5.4, self-intersects | Point-point DistanceX negated | §1 |
| Corner flips when a constraint is added | Dimensional value fights constructed coords | §2 |
| Edges frozen but endpoints stay apart | Block-only: no Coincident joining them | §3 |
| Flat drifts (e.g. -1.8 -> -1.05), wire self-intersects | Under-constrained: Coincident+Radius only | §4 |
| Sketch reports Invalid, Pad null | Redundant/conflicting constraint | §5 |

## 1. DistanceX/Y sign rules (verified solver arithmetic)
Point codes: start = 1, end = 2, centre = 3; origin = axis -1, point 1.
Forms:
```
Sketcher.Constraint('DistanceX', geo1, pos1, geo2, pos2, value)
Sketcher.Constraint('DistanceY', geo1, pos1, geo2, pos2, value)
Sketcher.Constraint('DistanceX', geo, pos, -1, 1, value)  # point to origin
```
- (point, origin): solver satisfies `point = -value`. NOT `point = value`.
  To place a point at x = +2.0 with a (point, origin) constraint, the
  value must be -2.0. Coding +2.0 puts it at x = -2.0.
- (point, point): solver satisfies `second - first = value`.
  Do NOT negate. From x = -1.8 to x = +1.8 needs DistanceX = +3.6;
  -3.6 dragged the profile to x ≈ -5.4, self-intersecting it.
  Same rule for DistanceY (vertical difference).
- Check after solving: read solved coordinates back
  (`sketch.Geometry[i].StartPoint/EndPoint`), never trust the coded
  sign. A sign error satisfies the constraint either way.

## 2. Exact value or omit
- A dimensional constraint is an equation the solver enforces exactly.
  If it disagrees with the constructed coordinates, the solver moves
  or flips geometry to satisfy it — it does not warn "close enough".
- Observed: forcing 24.0 deg on a diagonal constructed at 24.04 deg
  flipped the corner. Fix: use the exact computed value (24.04) or
  omit that constraint; do not round a computed angle/distance to a
  "nice" number and keep it driving.
- Angle form: `Sketcher.Constraint('Angle', geo, value_rad)` — value
  in RADIANS in the Python API, even though the GUI shows degrees.
  24.04 deg = 0.4196 rad. Passing 24.04 as radians = 1377 deg.
- Radius/diameter: `Sketcher.Constraint('Radius', geo, r)`,
  `Sketcher.Constraint('Diameter', geo, d)` — mm.

## 3. Block freezes one edge only
- `Sketcher.Constraint('Block', geo)` freezes that geometry's
  position, length and angle in place. It does NOT join anything.
- Block on every edge, with no Coincident constraints, freezes each
  edge independently: shared endpoints are never pulled together,
  so gaps remain and the wire stays open (see sketch_wire.md).
- Joining form: `Sketcher.Constraint('Coincident', g1, p1, g2, p2)`
  — one per shared endpoint pair, e.g. end of geo 0 to start of geo 1:
  `('Coincident', 0, 2, 1, 1)`.

## 4. Under-constrained drift
- DoF = free parameters left after all constraints. Coincident +
  Radius only still leaves DoF > 0: the solver may move
  unconstrained points on any later solve.
- Observed: such a profile drifted, its left flat moving from
  x = -1.8 to x ≈ -1.05; the wire self-intersected and the Pad
  produced multiple solids.
- Drift signature: coordinates read back after `doc.recompute()`
  differ from constructed coordinates, with NO error message.
  Only a solved-vs-constructed comparison detects it.
- `sketch.FullyConstrained` is `True` only at DoF = 0. Under
  (DoF > 0) drifts silently; over (redundant/conflicting) reports
  Invalid (§5).

## 5. Fully-constrained minimum set; redundancy
- Target: DoF = 0 with a minimum, non-redundant set — every DoF
  removed exactly once. One constraint past DoF = 0 makes the sketch
  redundant or conflicting.
- Redundant signature: solver message "redundant constraints", sketch
  state Invalid, downstream Pad null. A redundant constraint is not
  "extra safety"; it invalidates the sketch.
- Known redundant pairs (same DoF removed twice): Symmetric + origin
  Coincident on the same points; two DistanceX on the same point
  coordinate.
- Minimum-set example, rectangle (4 lines, 4 Coincident joins):
  4x Coincident + 2x Horizontal/Vertical + DistanceX (width) +
  DistanceY (height) + DistanceX/Y of one corner to origin (with
  the §1 sign rule) = DoF 0. Verify `FullyConstrained == True`
  and no redundant/conflicting message after recompute.
- Reference (non-driving) constraints remove no DoF and do not count
  toward the set.

## 6. Numbers
| Quantity | Value |
|---|---|
| (point, origin) DistanceX/Y | point = -value |
| (point, point) DistanceX/Y | second - first = value |
| Observed negated-span error | -1.8 -> +1.8 coded -3.6 -> profile at x≈-5.4 |
| Observed angle conflict | 24.0 forced on 24.04-built diagonal -> corner flip |
| Observed under-constrained drift | left flat -1.8 -> ≈-1.05, self-intersecting wire |
| Fully constrained | DoF = 0, zero redundant, zero conflicting |
| Angle unit, Python API | radians (GUI shows degrees) |
