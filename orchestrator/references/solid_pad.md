# solid_pad.md — Pad/Pocket solids, fusion, and result gates (FreeCAD facts)

Scope: PartDesign Pad/Pocket API, `Shape` result checks. Only what
the features do and which numeric signature each failure has.

## Symptom -> cause index
| Symptom | Likely cause | Section |
|---|---|---|
| Pad null shape / "Linked shape object is empty" | Open/invalid profile, or Invalid sketch (redundant constraint) | §2 |
| "Result has multiple solids. This is not supported" | Self-intersecting wire, or disjoint/non-touching pads | §2 |
| Second feature vanishes / body splits | New pad touches nothing; pocket cut through a neck | §3 |
| Run "succeeded" but no model file / empty .fcstd | freecadcmd exited 0 while the macro raised | §4 |
| Volume/bbox "pass" but shape wrong | Volume/bbox used as gates; they are reference only | §4 |

## 1. Pad/Pocket API (exact forms)
```
pad = body.newObject("PartDesign::Pad", "Pad_Name")
pad.Profile = sketch
pad.Length = 10.0          # mm, extrusion distance
pad.Reversed = False       # True = opposite the sketch normal
pad.Midplane = False       # True = half length each side
pad.Type = "Length"        # Length | UpToLast | UpToFirst | UpToFace
doc.recompute()
pock = body.newObject("PartDesign::Pocket", "Pocket_Name")
pock.Profile = sketch
pock.Length = 3.2
pock.Type = "Length"       # Length | ThroughAll | UpToFirst | UpToFace
pock.Reversed = False
```
- Pad adds material along the sketch normal; Pocket removes it.
  `Reversed` flips the direction — a pad extruded away from the
  body, or a pocket cutting air, is a direction error.
- `Type = "ThroughAll"` cuts through everything in the cut
  direction, regardless of `Length`. A blind pocket keeps `Length`.
- Every new feature must be based on the previous feature in the
  tree (`BaseFeature` chain via `body.newObject` order). A feature
  whose Base link points at itself or at a later feature recomputes
  to null.

## 2. Null-shape and multiple-solids causes
- Null shape causes: (a) open wire profile (see sketch_wire.md);
  (b) sketch state Invalid — e.g. a redundant constraint (see
  constraint_solver.md); (c) profile geometry that self-intersects.
- Multiple-solids causes: (a) a self-intersecting wire, which the
  extrusion splits into separate regions; (b) a sketch with two
  disjoint closed profiles padded at once; (c) a later pad that does
  not touch the existing solid at all.
- PartDesign rule: one Body = one contiguous solid (a compound of
  several solids is rejected for a normal Body). The error text is
  literal: "Result has multiple solids. This is not supported".
- Check per feature, in code, not by eye:
```
sh = feature.Shape
n = len(sh.Solids); ok = sh.isValid()
print("solids", n, "valid", ok, "vol", sh.Volume)
```
  `sh.isNull()` / `sh.isValid() == False` also catch the null case;
  an empty shape has 0 solids.

## 3. Fusion by overlap / burial
- A new pad fuses with the body only where the two volumes overlap
  (shared volume > 0) or at least share a face with real area.
  Touching at a single edge or point does not fuse.
- Practical form: a raised feature's profile must overlap the base
  in the extrusion direction. If the feature sits exactly on a face
  with zero overlap, extend its start INTO the base instead.
- Observed case: crown roots ending at Z = 2.70 while the base top
  is Z = 2.8 — roots buried 0.1 mm into the base — fused to a
  single solid, whereas roots stopping exactly at the base top face
  risk a zero-overlap seam.
- Same rule in reverse for pockets: a cut that severs the only neck
  joining two regions leaves two solids and fails. A through-cut
  must leave a connecting bridge, or be split into separate bodies.
- Burial depth is a modelling overlap margin, not a drawing
  dimension. The buried portion must not poke through the opposite
  face.

## 4. Gates, and the exit-code trap
- Gates (the only two that decide pass): `len(shape.Solids) == 1`
  AND `shape.isValid() == True`. Both must hold after EVERY feature,
  not only at the end — a bad middle feature is masked by later ones.
- Reference only, never gates: `shape.Volume`, `shape.BoundBox`
  sizes, face/edge counts. Volume can match while positions are
  wrong (wrong-side cut still removes volume); bbox can match while
  a feature is mirrored. Use them to describe a result, not to
  accept it.
- freecadcmd exit code trap: `freecadcmd` exits 0 even when the
  macro raises an exception. Verified on real runs: a macro that
  died at the first Pad still exited 0, leaving an empty .fcstd.
  Judge a run ONLY by its output files: .fcstd exists, reopens,
  has the expected feature tree, and its final Shape passes §4
  gates. Exit 0 alone proves nothing; a non-zero exit is not
  required for failure.
- STEP check: reimport the exported STEP and apply the same two
  gates to the imported shape. Failure there means the export
  failed, not just the model.

## 5. Numbers
| Quantity | Value |
|---|---|
| Gate 1 | `len(Solids) == 1` |
| Gate 2 | `isValid() == True` |
| Observed burial for fusion | 0.1 mm (roots Z=2.70 vs base top Z=2.8) |
| freecadcmd exit on macro raise | 0 — not a pass signal |
| Volume / bbox role | reference only, never a gate |
