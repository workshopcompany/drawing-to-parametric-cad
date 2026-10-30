# web_ui.py Usage

English version. The Korean original is `web_ui_README.md`.

## What is this?
A small browser UI for `run_pipeline.py` — the same pipeline, without
the command line. It uses only the Python standard library, so no
extra installation is needed.

## Start
From inside the `orchestrator` folder (the folder that holds
`run_pipeline.py`):
- Windows: `python web_ui.py`
- Mac/Linux: `python3 web_ui.py`

Then open http://127.0.0.1:8000/ in a browser.
To change the port: `python web_ui.py --port 8001`.

## Form fields
- Drawing image: uploaded and saved in the output folder as
  `input_drawing.<ext>`. You can view it directly in the browser on
  the result page.
- Outline attachment (optional): a JSON file from the outline snap
  tool, or an outline image. JSON is summarized for the LLM prompt
  (the full point list is not pasted verbatim); an image is sent to
  the LLM as a second image. The original is kept in the output
  folder as `outline_input.*`.
- Part notes: optional, notes about the drawing.
- Gear part: check this only for gear parts. Only then is the gear
  reference included.
- Output folder: default `./my_run_output`, relative to the folder
  where the server was started.
- freecadcmd: default `freecadcmd`. If FreeCAD 1.1.4 is not in PATH,
  enter the full path. The UI checks this before any API call, so a
  wrong path stops here with an error instead of spending API credit.
- dry-run: check the prompt assembly without calling the API.
- Meta API key: a password field, never saved, used for this run
  only. If the field is empty, the UI uses the key from a local
  `.env` file in the repo folder. To make one: copy `.env.example`
  to `.env` and put your key after `META_API_KEY=`. Never push `.env`
  to GitHub (`.gitignore` blocks it). The form shows only whether a
  `.env` key is present or absent, never its value.

## Start with dry-run
The first time, check dry-run and run. Confirm the prompt assembles
and that `report.txt` and `prompt_dryrun.txt` appear in the output
folder.

## Check the result
When a run finishes, the result page shows the exit code,
`report.txt`, `guidance.txt` (on failure), `questions.txt` (when the
macro asked questions), the input images, result previews, and the
output file list with download links.
If the macro asked Q1–Q9 questions, they are extracted to
`questions.txt` and shown on the QA tab. A result built with
provisional values while questions were unanswered is shown as
"success (provisional — questions pending)", not a clean success.
Answer the questions and rerun.

## Output folders (timestamped, never overwritten)
Running with the default (`./my_run_output`) creates a timestamped
folder instead (e.g. `my_run_output_20261030_090411`). Specifying a
folder that already holds a previous result creates a timestamped
sibling folder. An empty new folder is used as-is. Timestamped
sibling folders (not nested date subfolders) keep the recent-runs
list working, since it scans the server folder's top level. The result
page has tabs (Drawing recognition / Parameters & 3D / FreeCAD
export / QA log) and an interactive 3D viewer (`viewer3d.js`, based on
`tris.json`, no CDN) so you can rotate the model and check its shape.
If previews cannot be made (e.g. no matplotlib), the pipeline retries
with the Pillow fallback (`render_preview_pil.py`); if both fail, the
run itself does not fail and the report says "Previews: unavailable".
Result previews (`preview_iso.png`, `preview_main.png`) are shaded
images from the STEP tessellation — for shape checking, not a
dimensioned drawing. Open the `.fcstd` in the FreeCAD GUI to check
the tree, full constraint, and whether a dimension change + Recompute
still regenerates.

## Reopen recent runs
Below the form, a recent-runs list appears. A finished output folder
can be reopened on its result page without rerunning. An unreadable
folder is skipped instead of crashing the form.

## Sample drawings (the `image/` folder, local only)
Images placed in `orchestrator/image/` can be previewed directly
from the form. The folder is empty by default. If you put drawings
there, never push drawings containing company information (logo,
company name, etc.) to GitHub. Keep sample drawings for local testing
only.

## Not yet supported
- PDF drawings are not supported yet: the pipeline has no PDF-to-image
  conversion. Convert a PDF drawing to PNG/JPG first.
- No external fonts are loaded. The UI uses only system fonts
  (sans-serif / monospace) so it works offline.

## Key security
The key is never written to disk, never appears in logs, URLs, or the
result page, and reaches `run_pipeline.py` only as the
`META_API_KEY` environment variable for that run. If the key field is
empty, there is no `.env` key, and dry-run is off, nothing runs.
The `.env` file itself cannot be served as a download (files outside
the output folder are blocked from download).

## Outline tool
Opening `outline_snap_tool.html` in a browser lets you trace an
outline directly on a drawing and export it as JSON. This file is a
copy of `test/test2_snap_tool.html`. The `test/` original stays
untouched as the test2 record; future outline-tool edits go to the
`orchestrator/` copy only.

## Honest limits
This UI runs only on the user's own PC. It does not let Muse control
that PC, and it does not replace FreeCAD. FreeCAD 1.1.4 is needed
separately. Real API runs must be tested at home with the user's own
key.
