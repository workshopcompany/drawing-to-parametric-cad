# Macro test 3 — new drawing macro test report

## Status: final candidate, closure confirmation pending — NOT yet closed

This is the final candidate version (v5 fix3). The user has confirmed
the centre-peak correction below, but has not yet explicitly confirmed
this test as closed. Do not read this report as a closure confirmation;
the header will be updated to "CLOSED" only after the user says so.

Method: an LLM reads the drawing plus the principles file, generates a
FreeCAD macro, and the result is verified by independent STEP
comparison against the drawing (dimension / tree / constraint gates).
Volume is reference only, never a gate.

Security, same rule as test1/test2: no source drawing image is included
in this report, in the results zip, or in any GitHub upload. Only files
the user generated (model, STEP, script, report, previews of the model)
may be published. This part is referred to here only as "new drawing";
no company name is used.

## 1. Final candidate: new drawing macro v5 fix3

- Files: `scripts/new_drawing_macro_v5_fix3.py`,
  `models/new_drawing_macro_v5_fix3.fcstd`,
  `exports/new_drawing_macro_v5_fix3.step`
- Base (F1, gate passed exactly): section 3.6 x 3.15, height 2.8
  (bbox 3.6000 x 3.1500 x 2.8000), left R0.75 x 2, right R0.7989 x 2
  (0.7989 inferred from endpoints vs nominal R0.8), 24° diagonals.
- Crown (F2): green-outline boundary, width 4.8000 by tessellation
  (NOT BoundBox — see fix2 below), peak at the centre (see below),
  thickness Y 2.124 (Y ±1.062), bottom buried to Z = 2.7.
- Slots (F3/F4): top-open rectangular notches, NOT closed holes.
  Width exactly 0.500 both, angles +35° (left) / −55° (right) from
  horizontal, through the full Y 2.124 thickness, inner ends 90°.
  Inner-end face area 1.0620 = 0.500 x 2.124 both, centres
  (−1.1930, 3.8840) left / (0.9845, 3.8224) right. Slot datum is the
  centreline intersection (0.2392, 4.8868), a construction point in
  air above the peak, not a solid feature.
- Centre peak (user-confirmed Oct 29, 2026 18:21–18:22 EDT): a single
  sharp RIGHT-ANGLE peak, NOT a flat or dipped top. Peak point is
  the intersection of the two centre-facing slot sides (+35° left,
  −55° right, perpendicular), verified at (X 0.1778, Z 4.5386)
  vs computed (0.178, 4.539), angle 90.0° exactly, flat top length 0.
  Peak height is NOT a preset dimension — it emerges from the slot
  intersection, by the user's method: let the two slots meet /
  overlap when cutting, so the peak is created by their intersection.
  Implementation: S2 spline removed, F2 centre top is a sacrificial
  line at Z = 4.8 (does not survive the slot cuts, does not set the
  peak); slot outer ends extended to datum I itself (centreline
  distance 0.0).
- Tessellation bounding box: X 4.8000, Y 3.1500, Z 0–4.5386.
- Single valid solid, volume 36.5198 mm^3 (reference only; the
  manual v12 volume was 36.514, fix2 was 36.5997 — do not gate on
  volume equality).
- No zero-cut pocket: slot faces exist with non-zero areas.
- Confirmed dimensions used (user, Oct 29, 2026): base 3.6 x 3.15,
  height 2.8, upper thickness Y 2.124, crown height 1.7, slot
  angles +35° / −55° from horizontal, slot outer end at the outline
  drawing position (superseded for the centre peak by the
  user-confirmed overlap method above), crown outline taken from
  the user's outline tool (green region boundary, width set to
  4.800).

## 2. How fix3 was reached (v1–v5 fix3, condensed, one cause per step)

- v1: block only — single solid 3.6 x 3.15 x 2.8, crown, section
  shape and slots skipped rather than invented (correct behaviour
  under "ask first, do not invent"; the part was not complete).
- v2: never ran — `py_compile` failed on a syntax error (one extra
  ")" and a typo in a log line).
- v3: never ran as a model — sketch null. Bottom R0.8 arc built as
  `Part.ArcOfCircle` with 3 vectors (wrong form for a 3-point arc),
  plus DistanceX/Y on already-Coincident endpoints
  (over-constraint suspicion). Only a failed-sketch diagnostic body
  was kept.
- v4: stopped at F1 — Pad valid but 6 solids, volume 31.77. Cause:
  Sketcher point order differs by arc type in FreeCAD 1.1.4 —
  `Part.ArcOfCircle` point 1 = start, 2 = end, 3 = centre, while
  `Part.Arc` (3-point) point 1 = END, 2 = START, 3 = centre. The
  R0.8 arcs used `Part.Arc`, but Coincident closure assumed
  sequential point order for all geometries, so the wire
  self-crossed. The macro's own check reported only "multiple 6",
  with no geometry index, point-order cause or solver error.
- v5: stopped at F1 constraint construction — `Sketcher.Constraint
  ("Length", geometry, value)` raises TypeError in FreeCAD 1.1.4
  for a line length; the point-index form `Constraint("Distance",
  geo, 1, geo, 2, value)` is required. The macro's own guidance
  function was never reached, because the error was raised while
  evaluating the `Constraint()` argument, before the try/except
  around `addConstraint`, and guidance was print-only, so a
  freecadcmd stdout loss erased it.
- Fix cycle 1 (after the user rule change, Oct 29, 2026 17:59 EDT:
  self-fix code / API errors up to 3 attempts, log fixes to a file,
  guide on the 3rd failure; dimension questions are never
  self-fixed): Length fix applied, then R0.8 major-arc fix (angles
  wrapped to 360° gave 294° major arcs instead of 66° minor arcs),
  then F1 bbox still failed (2.8585 x 3.1236 x 2.8000) — diagonal
  DistanceX/Y signs conflicted with the true geometry. 3rd failure:
  stopped, guidance given, no 4th run.
- Fix2: diagonal signs fixed (top dy −0.546, bottom dx −1.225 /
  dy −0.546) — F1 gate passed exactly, 3.6000 x 3.1500 x 2.8000.
  Then F2 stopped on BoundBox width 4.8795 vs 4.800: FreeCAD
  `Shape.BoundBox` inflates B-spline curves (control poles, not
  the curve). Fix: check tessellation vertices instead (true
  width 4.8000), with no geometry change. Full PASS, volume
  36.5997, but the centre peak was wrong (S2 flat / dipped top).
- Fix3: centre peak corrected as in section 1. Attempt 1 (slot
  outer ends −0.15 / +0.15 from datum I) left a tiny fragment
  solid (volume 0.0278, Z 4.678–4.800) on the sacrificial plateau
  top at Z = 4.8. Attempt 2 extended both slot outer ends to
  datum I itself (centreline distance 0.0); centre-facing sides
  unchanged, so the peak is unchanged, and the fragment is gone.
  Full PASS, volume 36.5198.

## 3. Lessons carried forward

- F1 base arcs are the recurring failure point in this drawing
  (v2 syntax, v3 arc form, v4 point order, v5 Length form, fix1
  diagonal signs). Arc form and point order are program rules,
  decided internally, never asked of the user.
- For B-spline models, `Shape.BoundBox` is control-pole inflation,
  not true size. STEP tessellation vertices (and Y = 0 sections)
  are the true-size check.
- Failure guidance must contain feature name, sketch / geometry
  index, exact solver / error message, cause hypothesis, and a
  specific question or alternative — a vague "FAIL" or
  "multiple N" is not guidance. Guidance and logs must be written
  to a file, not print-only, and constraint construction (not
  just `addConstraint`) must be inside try/except.
- Current failure rule (user, Oct 29, 2026 17:59 EDT): code / API
  errors are self-fixed and rerun up to 3 attempts, with fixes
  logged to a file; on the 3rd failure, stop and guide. Dimension
  questions are never self-fixed and are never invented — the
  centre-peak correction above is an example: it was a design
  question, so it was asked and confirmed before rebuilding.

## 4. File list for the results zip

- `new_drawing_macro_v5_fix3.fcstd`
- `new_drawing_macro_v5_fix3.step`
- This report is a separate file, not inside the zip.
- Excluded: source / annotated / green-outline user images (never
  uploaded), LLM raw responses / prompts (kept locally for
  reference, not published — see the manifest), intermediate
  v1–v5, v5_fixed and v5_fix2 models and scripts, diagnostic FAIL
  bodies, /tmp files. The history above is the record; the
  intermediate files stay local unless the user asks for them.
