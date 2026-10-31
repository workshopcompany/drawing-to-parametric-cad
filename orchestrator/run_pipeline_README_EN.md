# run_pipeline.py Usage (v0.1 prototype)

English version. The Korean original is `run_pipeline_README.md`.

## What is this?
An orchestrator: give it a drawing image + text, the Meta API generates
a FreeCAD macro, and FreeCAD runs it to export a `.fcstd` + STEP +
report. It bundles into one script what used to be done step by step
in chat.

## What you need
- FreeCAD 1.1.4 (free)
- This repo as a ZIP (everything needed to run is in the `orchestrator/`
  folder)
- A `META_API_KEY` (from the Meta developer portal — never hardcode it
  into code)

## Run (one line)
Run from inside the `orchestrator` folder:
```
cd orchestrator
export META_API_KEY="..."
python3 run_pipeline.py --drawing my_drawing.png --text "part notes" --output-dir ./my_run_output
```
Windows equivalents for the key: PowerShell `$env:META_API_KEY="..."`,
cmd `set META_API_KEY=...`.

Add `--gear` only if the drawing contains a gear. Do not add it for
non-gear parts — the gear reference is included only with that flag.

Optional inputs:
- `--outline <file>`: an outline attachment from the outline snap tool.
  A JSON outline is summarized for the prompt (structure + at most 200
  sampled points + bounding box, never the full point list verbatim);
  an image outline is sent to the LLM as a second image. The original
  file is copied to the output folder as `outline_input.*`.
- `--dry-run`: assemble the prompt only, without calling the API.

## Before any API call
The script checks that `freecadcmd` is findable first (the command in
the `--freecadcmd` argument, default `freecadcmd`, or an existing file
path). If it is not found, the script stops with an error before any
API call, so no API credit is spent. On Windows, if FreeCAD 1.1.4 is
installed but not in PATH, pass the full path, e.g.
`C:\Program Files\FreeCAD 1.1.4\bin\freecadcmd.exe` (the actual folder
varies by installation).

## How to verify the result (in the FreeCAD GUI)
- Open `<output-dir>/model.fcstd`.
- Check the tree is Body → Sketch → Pad/Pocket, in order.
- Check each sketch is FullyConstrained and its dimensions match the
  drawing.
- Change one dimension and Recompute. If it regenerates as a single
  valid solid, the parametric history is alive.
- Open `<output-dir>/model.step` too and check it shows the same shape.
- `<output-dir>/report.txt` lists solid count, validity, bounding box,
  and volume (volume is reference only).
- Pass means exactly 1 solid and valid. Volume equality alone is NOT
  the pass criterion.

## Result previews
After a verification pass, the pipeline writes `tris.json` (STEP
tessellation) and renders `preview_iso.png` (isometric) and
`preview_main.png` (the two largest bounding-box axes) with Lambertian
shading, no edge lines, white background. It tries `render_preview.py`
(matplotlib) first, then `render_preview_pil.py` (Pillow + numpy) as a
fallback. Previews are best-effort only: if both renderers fail, the
run itself does not fail, and the report says "Previews: unavailable".

## If it fails
- Code/API errors are self-fixed and rerun, up to 3 attempts total.
- On the 3rd failure it stops and writes `<output-dir>/guidance.txt`
  with the feature name, geometry index, exact error, cause, and a
  question or alternative.
- Design/dimension questions are never self-fixed: the run stops
  instead of inventing a dimension. Answer the question and rerun.

## Modeling complete + matching table (matching.json)
The word "success" is no longer used. The gate is only STEP
solids == 1 and valid True, and the result is "RESULT: MODELING
COMPLETE". It does NOT mean "same as the drawing". The matching
table goes to matching.json and as lines in report.txt. Drawing
values are the LLM's reading from the drawing (macro parameters,
ask-first D-dimensions, confirmed answers). Modeling values resolve
per row, in order: (1) a macro parameter whose name shares a word
with the dimension (slot width, tip height, ...), (2) STEP cylinder
faces for diameters/radii (only if a cylinder near that size exists),
(3) whole-part size X for total/overall/axial lengths. Width/height
words are NOT compared to whole-part bbox sizes: they are
view-dependent and often local, so without a matching macro parameter
they show ? instead of a bogus X. Reference dimensions (parenthesized
on the drawing) show "? (참조치수)". D-dimensions carry a view tag
([front]/[section]/[side]/[top]) from ask-first through /answer to
the table. O = within 0.01 mm, X = differs, ? = cannot be compared
this way, ? (참조치수) = reference dimension, ~ = reference only.
In the ask-first step, the D-dimension list goes to dimensions.json,
and if positions exist, red numbered badges are drawn into
drawing_numbered.png (skipped if PIL is missing or no positions;
positions are estimates).

## Design-question FAIL (questions instead of a macro)
If the LLM answers with questions instead of a macro, the
pipeline does not self-fix and does not invent around it: it
writes the question verbatim to guidance.txt and exits with
"RESULT: FAIL - design question" (exit code 1, no model). The
question also goes to questions.txt, so the web UI offers
Continue work right away. A design question is never bypassed
by invention.

## Ask first (--ask-first)
With `--ask-first`, the first run builds no model and only extracts
questions. The LLM is told "no macro, no code, questions only in
Q1: ... format". With questions, the run leaves questions.txt +
"RESULT: QUESTIONS PENDING (ask-first ...)"; with none, it leaves
"RESULT: ASK-FIRST NO QUESTIONS". The freecadcmd check is skipped
in this step (nothing is built). Answers go into the next run as
`--text` via the web UI Continue work button. If new questions
arise during a build, that run is QUESTIONS PENDING too, and
answering rebuilds.

## Questions and provisional results
- If the macro asks Q1–Q9 questions, they are extracted to
  `<output-dir>/questions.txt` and listed in `report.txt`, and shown
  on the web UI QA tab.
- questions.txt holds open questions only. Items already answered,
  confirmed, or built exact, and pointers to another question
  (`see Q30`), are left out. The prompt also tells the LLM never to
  list a closed item as a Q-line.
- If a solid is built while questions are unanswered, the exit code
  is still 0, but the result is NOT a success. `report.txt` says
  "RESULT: QUESTIONS PENDING", and the result page banner says
  "Questions pending — NOT a success". It was built with provisional
  values, so answer and rerun.
- The safety check does not check comments. A comment mentioning
  "AttachmentOffset" does not block a macro; only actual code use
  does.
- Generated macros pass a safety check before running. Dangerous calls
  (subprocess, socket, urllib, requests, shutil, eval, exec, open,
  `os.system`, `os.environ`, `AttachmentOffset`) are rejected; plain
  path joining (`os.path.join`, `os.makedirs`) and saving with
  `doc.saveAs()` / `Part.export()` are allowed.

## Not yet supported
- Automatic 2D drawing extraction from `.fcstd` via TechDraw is not
  automated yet. For now, build TechDraw pages manually in the FreeCAD
  GUI to get 2D views.
- PDF drawings are not supported yet: the pipeline has no PDF-to-image
  conversion. Convert a PDF drawing to PNG/JPG first.

## Real measurement (실측): --measure mode

`python3 run_pipeline.py --measure --output-dir <result folder>
--freecadcmd <path>` measures an EXISTING result folder's model.step
(no drawing, no API call, no rebuild) and adds a Measured column to
matching.json. It runs measure_step.py under freecadcmd, which reports
a battery of real geometry: parallel planar face distances, straight
edge lengths (with direction axis), vertex coordinate differences
from topological vertices only, horizontal section extents (25 Z
levels), whole-part bbox extents, and cylinder diameters.

Matching rules (match_measured): diameter/radius rows use cylinders
only; offset/position/tolerance rows are not measured (positions,
not sizes). Other size rows take the best battery value, but rows
with a view-determined axis (front/side/top, or depth/thickness
words) only accept candidates on that axis or angled ones; other
axes are excluded. Bands: axis-aligned face/section/bbox values use
max(0.1, 10% of value); exact or numerous values (edges, vertex
deltas, angled face pairs) use 0.05, because dense pools "find"
coincidences under a loose band. The measured value has NO verdict:
compare it with the drawing value yourself (general tolerance ±0.1,
not the strict 0.01 table tolerance). The method (e.g. "parallel
faces (angled)") is stored per row and shown on hover.

Honest gaps in v1 (shown as —, not faked): smooth curve maxima with
no corner point (e.g. hook tip tops) have no vertex to measure from;
tessellation points are deliberately NOT used for deltas, because
mesh points exist near almost any value and would "confirm"
anything. Files: measurements.json (+ measured_at), measure_log.txt,
matching.json gains measured/measured_method per D-row, and a
summary line is appended to report.txt.
Note: --measure also refreshes the Modeling and Result columns with
the current matching rules when the folder still holds macro.py
(the macro that built the model). Old result folders carry stale
modeling values from the whole-bbox mapping (widths -> size Y,
heights -> size Z), which showed X even where the measured value is
nearly exact; after a re-measure those rows become O or ? under the
current rules. Folders without macro.py keep their old rows, and a
failed verification never downgrades good rows to ?.
The --measure run also writes a measured verdict per D-row
(measured_result): O if the measured value is within general
tolerance ±0.1 of the drawing value, X if it differs more, ?
if there is no measurement. It is deliberately NOT the strict
0.01 table tolerance: accepted outline deviations (peak height
1.739 vs 1.70) would otherwise show X. The web UI shows it as a
"Measured result" column next to Measured, separate from the
modeling-based Result.
