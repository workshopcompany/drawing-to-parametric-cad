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

## Questions and provisional results
- If the macro asks Q1–Q9 questions, they are extracted to
  `<output-dir>/questions.txt` and listed in `report.txt`, and shown
  on the web UI QA tab.
- If a solid is built while questions are unanswered, the exit code
  is still 0, but the result is "PASS (provisional — questions
  pending)", not a clean PASS. It was built with provisional values,
  so answer and rerun.
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
