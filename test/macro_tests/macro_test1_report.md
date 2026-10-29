# Macro test 1 — 1U (CSF-3) macro test report

## Status: PASS, confirmed by the user Oct 29, 2026 13:32 EDT ("Ok")

Method for all macro tests in this folder: an LLM reads the drawing plus the
principles file, generates a FreeCAD macro, and the result is verified by
independent STEP comparison against the drawing (dimension / tree /
constraint gates). Volume is reference only, never a gate.

Security, same rule as test1/test2: no source drawing image is included in
this report, in the results zip, or in any GitHub upload. Only files the
user generated (model, STEP, script, report, previews of the model) may be
published.

## 1. Final version: 1U macro v14

- Files: `scripts/csf3_1u_macro_v14.py`,
  `models/csf3_1u_macro_v14.fcstd`,
  `exports/csf3_1u_macro_v14.step`
- Generation: muse-spark-1.3, image direct, one fresh generation
  (prompt 7,694 / completion 24,717 / total 32,411 tokens).
- Single valid solid, volume 2282.7376 mm^3 (reference only; differs from
  the manual 1U v3 volume 2618.891 because the corrected stack below
  removes the D7.2 collar at 5.5–7.0 and the output square plate at
  21.5–22.4 — do not gate on volume equality).
- Bounding box: 27.0000 x 13.0000 x 13.0000 (X 0–27, Y/Z ±6.5).
- Corrected stack, in order (X = axial position, total 27):
  shaft D3.5 x 0–7.0 continuous, with a 0.2 mm flat x 0–5.5 leaving
  3.3 mm (flat plane Y = 1.55), round x 5.5–7.0; flattened D7.2 segment
  x 7.0–8.5 (Y ±2.5, Z ±3.6); boss D12 x 8.5–9.9; square housing
  13 x 13 x 9.9–21.5 (chamfer ~1.0); boss D10 ALONE x 21.5–22.4;
  step D3 x 22.4–23.0; shaft D2 x 23–27.
- Holes: 4 x drill D1.25 (M1.6 tap), D15 PCD, depth 3.2 into the housing
  (X 9.9–13.1, centres Y/Z ±5.303), area 1.2272 each.
- Verified sections (from STEP, not the macro log): flat X = 2.75 area
  9.4019; round X = 6.25 area 9.6211 (D3.5, no collar); flattened
  X = 7.75 area 32.8493; housing X = 15.0 area 167.0000; boss D10 alone
  X = 21.95 area 78.5398; Y = 0 section length 80.0000.
- Tree: Body -> 9 sketches + 8 Pads + 1 Chamfer + 1 Pocket, in the stack
  order above, with 10 incremental diagnostic saves (one after each
  successful feature). All 9 sketches FullyConstrained. No Lock
  constraint in any sketch, no single-point-alone constraint, no
  AttachmentOffset (direct Placement, MapMode Deactivated).
- Provisional items carried in the v14 header (already-answered /
  provisional, not new design questions): shaft flat on +Y, housing
  chamfer 1.0 estimated, flattened D7.2 width 5.0 user-set.
- Omitted as decided: bottom protrusion under the housing (unknown /
  undimensioned); bolts (separate fasteners, modelling excluded, memoed
  in the macro header).

## 2. How v14 was reached (v1–v14, condensed, one cause per version)

- v1: AttachmentOffset axis error — a YZ-sketch AttachmentOffset written
  as (segment_start, 0, 0) shifted global Y instead of X.
- v2: square sketches drifted / stayed under-constrained (flange,
  housing, output plate).
- v3: Pocket Reversed error (pocket cut the wrong side).
- v4: chamfer over-constraint.
- v5 / v7 / v10: collar / plate misreading (D7.2 collar at 5.5–7.0 and
  an output square plate, both superseded by the corrected stack).
- v8: DistanceX/Y sign flip — a constraint coded as (point, origin) is
  solved as point = −value, so flats cut air on the wrong side.
- v9 / v11: `sk.Support` no longer exists in FreeCAD 1.1.4.
- v12: AttachmentOffset axis error again.
- v13: Lock TypeError — `Sketcher.Constraint('Lock', geometry, point)`
  raises TypeError in FreeCAD 1.1.4, where Lock takes a single geometry
  number; no model was produced and no diagnostic body was saved.
- v14: PASS. Rules resolved in v14 and carried into the principles:
  do NOT constrain a single point alone (Lock itself is NOT banned);
  point positions by DistanceX/Y (+/−) / Coincident reference; save
  the diagnostic body incrementally after EACH successful feature,
  not only on failure; direct Placement, never AttachmentOffset.

## 3. Lessons carried forward

- Principles stay short (tool name + one example). Placement method,
  API names and constraint names are program rules decided internally,
  never asked of the user; only design / dimension questions go to
  the user.
- After EACH step, verify by drawing comparison (projection / section /
  dimension for that feature), not by volume change alone — a
  wrong-side cut still decreases volume.
- A macro log of valid + single solid is not a pass. Dimension, tree
  and constraint gates are separate.
- Failure handling at the time of v14: present an alternative or a
  question first, then retry once after the user's answer. Current
  rule (since Oct 29, 2026 17:59 EDT, from the new-drawing test):
  code / API errors are self-fixed and rerun up to 3 attempts, with
  fixes logged to a file; on the 3rd failure, stop and guide with
  feature name, geometry index, exact error, cause and a specific
  question or alternative. Dimension questions are never self-fixed.

## 4. File list for the results zip

- `csf3_1u_macro_v14.fcstd`
- `csf3_1u_macro_v14.step`
- This report is a separate file, not inside the zip.
- Excluded: source drawing images, LLM raw responses / prompts for v14
  (no v14 raw-response or prompt file exists locally — see the
  manifest), intermediate v1–v13 models and scripts, diagnostic
  bodies in /tmp. The v1–v13 history above is the record; the
  intermediate files stay local unless the user asks for them.
