# Gear macro test report

## Status: CLOSED, confirmed by the user Oct 29, 2026 16:04 EDT

This report finalises the earlier draft (gear_macro_v6_report_DRAFT.md,
kept untouched alongside this file). The two items that were pending in
that draft are now confirmed, as used in v6 for closure:

1. Body chamfer: body D22 outer edges, front (X = 6) and back (X = 13),
   C0.5, 2 places — NOT a bore chamfer.
2. Tap-hole axial position: X = 9.5, as used in v6 (provisional body
   mid-thickness 6–13, accepted for closure).

Method: an LLM reads the drawing plus the principles file, generates a
FreeCAD macro, and the result is verified by independent STEP comparison
against the drawing (dimension / tree / constraint gates). Volume is
reference only, never a gate.

Security, same rule as test1/test2: no source drawing image is included
in this report, in the results zip, or in any GitHub upload. Only files
the user generated (model, STEP, script, report, previews of the model)
may be published.

## 1. Final version: gear macro v6

- Files: `scripts/real_drawing_gear_macro_v6.py`,
  `models/real_drawing_gear_macro_v6.fcstd`,
  `exports/real_drawing_gear_macro_v6.step`
- Generation: muse-spark-1.3, image direct, prompt 5,660 /
  completion 21,958 / total 27,618 tokens.
- Single valid solid, volume 2805.0703 mm^3 (reference only, not a
  gate; test1 manual v5 was 2821.577, v5 macro was 3042.4791 — v6
  differs because the body chamfer and taps are present).
- Bounding box: X 14.5 (0–14.5), Y ±11.0, flat Z = −10, height 21.
  (BoundBox Z 21.4762 is curved-face inflation; vertices prove 21.0.)
- Gear: 30T, tip 16.001 / pitch 15.0 / root 13.750, thickness 5.
  API used: `InvoluteGearFeature.makeInvoluteGear("InvoluteGear")`
  (single name string). Banned forms (`addObject` / `newObject`
  InvoluteGear) were not used. The detailed gear method lives in
  `GEAR_CREATION_REFERENCE.md`, included in the prompt ONLY because
  the drawing contains a gear.
- Stack, in order: gear -> step D16 x 1 (5–6) -> body D22 x 7 (6–13)
  -> back boss D10 +1.5 (to 14.5) -> back step D12 −1.5 (bottom
  X = 11.5) -> bore D7.93 through 0–14.5 including the boss
  -> body chamfer -> flat grinding -> tap holes.
- Body chamfer: C0.5, body D22 outer edges X = 6 (front) and X = 13
  (back), 2 places, 4 conical faces at X = 6.5 / 12.5, 45 degrees.
  (4 faces, not 2, because the flat cut afterwards splits each
  chamfer cone into a large face, area 32.976, and a small face,
  area 9.095.)
- Flat: Z = −10, height 21, AFTER the chamfer, BEFORE the taps.
- Bore: D7.93, 0–14.5 through, boss included. The centre bore and the
  reamer callout are the same hole, not two holes.
- Tap holes, verified by the corrected entry-only rule: exactly 3
  faces of radius 1.865 (drill D3.73 + 11/64"-40), all on the entry
  side only, no opposite-side face. Angles 270 / 30 / 150 degrees,
  axial X = 9.5. Length 8 reaches the bore void (0.965–1.965 mm past
  the bore wall) without reaching the opposite wall (13.965 /
  14.965 mm). Not a through hole. The 1.5 mm dims in the drawing
  were ignored, as decided; the bottom tab (width 10) was not made
  in v6 (it was approved for a later gear v2, not for this closure).
- Back-face note (deliberate, not a failure): boss top is 3.0 mm
  above the recess bottom, which differs from the Oct 27 manual v5
  model; this was made deliberately in the macro run.
- Tree order: Pad_Gear, Pad_Step, Pad_Body, Pad_Boss, Pocket_Recess,
  Pocket_Bore, Chamfer_Body, Pocket_Flat, Pocket_Tap1–3. All sketches
  FullyConstrained. No Lock, no single-point-alone, no
  AttachmentOffset.

## 2. How v6 was reached (v1–v6, condensed)

- v1: executed but wrong part — toothless D18 x 16 cylinder, total
  23 mm instead of 13, 1 tap hole, invented bottom notch, no
  chamfers.
- v2: failed at the first feature — headless FreeCAD rejected the
  `newObject` InvoluteGear call, so no later features ran.
- v3: failed on gear API arguments — tried several multi-argument
  forms of `makeInvoluteGear`, never the verified single-name form.
- v4: executed but wrong part — toothless D16.001 cylinder
  substitute, flat, recess, bore and two tap holes uncut.
- v5: partial pass, first time gear + directions were right, but
  chamfer and tap holes failed together. `Chamfer_Bore` used itself
  as Base (it became Tip on `newObject`, then `body.Tip` was taken
  as Base), a self-link DAG error that invalidated the chamfer and
  blocked the following taps. The macro's own log still said PASS
  (valid + single solid only); the failure was found only by
  drawing-comparison face checks (0 conical faces, 0 radius-1.865
  faces).
- v6: the fixes were (a) gear only via `GEAR_CREATION_REFERENCE.md`
  (included in the prompt only because the drawing contains a
  gear), (b) Pad / Pocket direction stated per feature, (c) body
  chamfer instead of bore chamfer, in its original tree position
  (after bore, before flat — NOT moved to the end), with Base
  captured as the preceding bore Pocket before `newObject`,
  (d) order changed to chamfer -> flat grinding -> taps,
  (e) taps verified by exactly-3 entry-side radius-1.865 faces,
  not by face existence alone.

## 3. Lessons carried forward

- Principles stay short (tool name + one example). The detailed gear
  method lives in `GEAR_CREATION_REFERENCE.md` and is included in
  the prompt ONLY when the drawing contains a gear.
- After EACH step, verify by drawing comparison (projection /
  section / dimension for that feature), not by volume change
  alone — a wrong-side cut still decreases volume.
- A macro log of valid + single solid is not a pass. Face
  existence, face count, and face position (entry side vs opposite
  side) are separate gates.
- Failure handling at the time of v6: present an alternative or a
  question first, then retry once after the user's answer. Current
  rule (since Oct 29, 2026 17:59 EDT, from the new-drawing test):
  code / API errors are self-fixed and rerun up to 3 attempts, with
  fixes logged to a file; on the 3rd failure, stop and guide with
  feature name, geometry index, exact error, cause and a specific
  question or alternative. Dimension questions are never self-fixed.
- Follow-up already known, not a v6 model failure: the macro's own
  tap check was still written as "3 or more" faces. For the next
  run it should be "exactly 3, entry side only" so the macro
  itself catches a through hole.

## 4. File list for the results zip

- `real_drawing_gear_macro_v6.fcstd`
- `real_drawing_gear_macro_v6.step`
- This report is a separate file, not inside the zip. (The draft
  zip contained exactly these same 2 files.)
- Excluded: source drawing images, LLM raw responses / prompts
  (kept locally in the workspace for reference, per the user's
  preference, not published — see the manifest), intermediate
  v1–v5 models and scripts, diagnostic bodies. The v1–v5 history
  above is the record; the intermediate files stay local unless
  the user asks for them.

## 5. What remains after this test closes

- The known program gap before the Nov 4, 2026 21:00 ET Meta
  hackathon deadline: automatic 2D drawing extraction from .fcstd
  via TechDraw. That choice (headless route / GUI retry / defer)
  was already put to the user on Oct 29 morning and is NOT
  re-asked by this report.
