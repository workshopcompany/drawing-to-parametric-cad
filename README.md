# drawing-to-parametric-cad

Multimodal (2D drawing + text) to parametric CAD, built for the Meta Global AI
Developer Hackathon (submission due Nov 4, 2026, 9 PM ET).

## Problem

Existing text-to-CAD tools output dead STEP geometry: no sketch, no feature
history, no dimensions to extract or edit. That makes 2D drawings, dimension
changes, change management, and mold-production adaptations impossible.

## Approach

Like a real designer works: sketch, then create features, one verified step at
a time — and save the result as a proper FreeCAD `.fcstd` file (sketch +
feature history). STEP is just an export, available anytime.

Pipeline:

1. **Input** — 2D drawing image + text description.
2. **Review** — Muse Spark reads the drawing (views, dimensions, features)
   and asks the user questions for anything missing instead of guessing.
3. **Generate** — a FreeCAD Python script builds a PartDesign body:
   sketch → pad/pocket → ... with named parameters.
4. **Verify per sketch** — every sketch and every feature is checked before
   the next step is generated (closed wire, valid solid, dimensions match the
   drawing). A failed step is repaired in place, not by regenerating everything.
5. **Finish** — fillets and chamfers are separate, toggleable feature nodes,
   applied either per feature or all at the end of the tree (configurable).
6. **Output** — `.fcstd` (the design file), plus STEP and 2D drawings on
   demand, with version history.

## Repository layout

- `inputs/` — source drawings and text descriptions
- `scripts/` — generated FreeCAD Python scripts (versioned)
- `models/` — `.fcstd` files (versioned)
- `exports/` — STEP files and 2D drawings
- `validations/` — per-sketch / per-feature verification logs

## Status

Early build. Testing starts with 2D drawings (not hand sketches).
