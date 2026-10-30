# thread_tap.md — tap holes: drill size, depth, no helical thread

Scope: tapped-hole modelling in PartDesign. Only drill/thread
arithmetic and Pocket behaviour — no workflow policy.

## Symptom -> cause index
| Symptom | Likely cause | Section |
|---|---|---|
| Tap hole modelled at nominal dia. | Drill dia. used = tap nominal, not nominal - pitch | §1 |
| Hole too tight/loose vs tap table | Pitch subtracted wrong (TPI vs metric pitch) | §1 |
| Hole depth measures from the wrong face | Depth counted from sketch plane, not entry face | §2 |
| Blind hole goes through / stops in air | Pocket length vs air gap + material misjudged | §2 |
| Thread helix modelled as a solid | Helical thread built; FreeCAD tap = plain drill hole | §3 |
| "Hole" appears on the wrong side | Pocket Reversed wrong; entry face misidentified | §4 |

## 1. Tap-drill diameter: nominal minus pitch
- Rule: `drill_dia = tap_nominal_dia - pitch`. The tap cuts its own
  thread into the drilled hole; the modelled hole is the drill hole,
  at drill diameter, with no thread ridge.
- Metric: pitch is the number after "x" (mm/thread). Examples:
  M1.6, pitch 0.35 -> drill Ø1.25 (1.6 - 0.35 = 1.25).
  M2, pitch 0.4 -> Ø1.6. M3, pitch 0.5 -> Ø2.5.
- Unified/inch: pitch = 25.4 / TPI (mm). Example: 11/64"-40:
  nominal = 11/64 in = 4.365 mm; TPI 40 -> pitch 25.4/40 = 0.635 mm;
  drill Ø3.73 (4.365 - 0.635 = 3.730). Round drill dia. to 0.01 mm.
- Do NOT model at nominal: M1.6 at Ø1.6 is 0.35 mm oversize — the
  thread has no material to cut into. Do NOT use a clearance-drill
  table (those give a looser hole for a bolt to pass through).
- Sketch form: a plain circle at drill diameter, centred on the
  hole axis. Diameter constraint:
  `Sketcher.Constraint('Diameter', geo, drill_dia)`.

## 2. Depth measured from its face
- Tap depth is measured from the entry face — the face the tap
  enters — along tool travel, NOT from the sketch plane if the
  sketch sits elsewhere, and NOT from the part origin.
- Blind tap: `Pocket, Type = "Length", Length = tap_depth`, with
  the sketch on (or offset to) the entry face, cutting into
  material. Depth counts only material travel; an air gap between
  sketch plane and entry face is not depth.
- Through tap: `Pocket, Type = "ThroughAll"` in the entry-to-exit
  direction. ThroughAll ignores Length; it cuts everything in that
  direction, so a second feature behind the hole is also cut — check
  what lies beyond before using it.
- Blind-to-bore behaviour: if a blind pocket's Length exceeds the
  material thickness at that axis, it breaks into the void/bore
  behind and becomes effectively through at that spot. If Length
  stops short of a bore behind the material, a web remains.
  Report depth as: entry face -> bottom, plus material breakdown
  (e.g. "3.2 deep: 2.0 material + 1.2 air gap" is NOT 3.2 of cut).
- Pocket form:
```
pock = body.newObject("PartDesign::Pocket", "Pocket_Tap")
pock.Profile = sketch   # circle at drill dia., on entry face
pock.Type = "Length"; pock.Length = tap_depth
pock.Reversed = <True if sketch normal points out of material>
doc.recompute()
```

## 3. No helical thread solid
- FreeCAD has no tap-thread solid in a PartDesign Pocket, and none
  is built here: no helix, no swept thread profile, no threaded
  cylinder added to the body. The tap is represented by its drill
  hole only.
- A helical thread cut (Part Helix + sweep) is a different feature
  with its own pitch/lead arithmetic; building one for a small tap
  (M1.6, Ø1.25 hole) adds fragile geometry for no drawing benefit
  and risks breaking the single-solid gate (see solid_pad.md).
- Thread callout on a drawing (e.g. "4-M1.6 tap 3.2") is read as:
  count 4, tap M1.6, drill Ø1.25, depth 3.2 from the entry face.
  The "tap" word never changes the modelled diameter to 1.6.

## 4. Entry-side-only verification
- After the pocket, verify on the ENTRY side only: count drill-
  diameter circular faces/edges on the entry face (expect = tap
  count), and check the hole bottom depth from that face.
- Do NOT count faces on the exit/opposite face: a blind tap has no
  exit opening, and a through tap's exit count can coincide with
  other bores. Opposite-face counts of 0 (blind, correct) or 6
  (through, double-counted) are both misread as failures if the
  entry side is not checked first.
- Failure signatures: 0 entry faces = pocket cut air (Reversed
  wrong, or sketch off the entry face); entry faces at nominal dia.
  = §1 error; depth short by exactly the air gap = §2 error.

## 5. Numbers
| Quantity | Value |
|---|---|
| Drill formula | nominal - pitch |
| M1.6 (pitch 0.35) | drill Ø1.25 |
| 11/64"-40 (pitch 0.635) | drill Ø3.73 |
| Metric pitch, M2 / M3 | 0.4 / 0.5 -> drill Ø1.6 / Ø2.5 |
| Depth datum | entry face, along tool travel |
| Thread solid | none — drill hole only |
