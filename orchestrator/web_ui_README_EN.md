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
"Questions pending — NOT a success", not a success at all.
Answer the questions and continue work.

## Language: English by default, Korean switchable
The default UI is English. Click the "한국어" link at the top of
the sidebar for the Korean UI, and the same link on a result page
to switch there (`?lang=ko`). Click "English" to switch back. The
choice travels with the form's hidden field to the result page.

## "Modeling complete", not "success", plus a matching table
The old "Success" label is now "Modeling complete". The gate is
still only solids == 1 and valid True; it does NOT mean "same as
the drawing". The result page has a new "Drawing ↔ Modeling match"
tab with a table: No. | Item | Drawing value | Modeling value |
Result (O/X/?/-). Drawing value = the value the LLM read from the
drawing and wrote into the macro (a D-dimension from the ask-first
step, or a user-confirmed answer); modeling value = measured from
STEP (bbox sizes, cylinder diameters, solids, validity, volume).
O = within 0.01 mm, X = differs, ? = cannot be mapped automatically,
~ = reference only. Note: the drawing value is NOT a directly
measured drawing truth. If the LLM misread the drawing, both
columns can be wrong together. The table checks "was the intent
built?", not "does it equal the drawing truth?".

## Numbered drawing (D1, D2, …)
In the ask-first step, the LLM lists dimensions it can read as
"D1: outer diameter = 22 mm @ (0.75, 0.20)". (x, y) is the
approximate position on the drawing image (0-1, origin top-left).
The pipeline draws red numbered badges at those positions into
drawing_numbered.png and saves the list in dimensions.json. The
matching tab shows the numbered drawing together with the table.
Badge positions are LLM vision estimates and can be off. The table
is authoritative; check badges against the original drawing. The
numbered drawing only comes from ask-first runs, and it is copied
into the new folder on Continue work. Older result folders have
none.

## Continuing after a failure (design-question FAIL is not a dead end)
If the LLM answers with questions instead of a macro, the
pipeline stops with FAIL (design question) rather than inventing
values. No model in that case is normal (stopping beats building
a wrong part). The LLM's question goes verbatim into
guidance.txt and also into questions.txt. Read the guidance on
the result page QA tab and answer in the "Continue work" form
below it. Older failed folders with guidance but no questions
also get the form now. Continue work is a fresh run, not a
resume, so paste the previous answers again too. Chained
Continue-work runs no longer compound timestamps in folder names
(the old stamp is stripped before a new one is appended).

## Q&A history auto-accumulates (qa_history.txt) — no re-pasting
When you answer via Continue work, that round's questions +
answers accumulate into qa_history.txt in the new folder. The
next run's prompt includes the full Q&A history automatically,
so each round only needs the new answers (previously only the
immediate previous questions + new answers were carried, so
everything had to be re-pasted every round). The accumulated
history is visible/downloadable as qa_history.txt in the result's
file list. Note: Continue work is still a fresh run from scratch,
not a patch to the old macro — there is no resume-the-model
feature. Each result folder IS the saved project: drawing,
outline, report, questions, macro, and model (if any) stay in
the folder, and restarting the server in the same folder shows
them in recent runs again (starting in a different folder does
not — recent runs scan the server's working folder).

## Ask first (on by default) — the back-and-forth loop
"Ask questions first" is on by default. The first run builds no
model and only extracts questions (report says "ASK-FIRST", no
model file, banner is "Questions pending" or "Ask-first done — no
model yet"). Answer in the QA tab form and press Continue work, and
only then is the model built with your answers. If new questions
arise or the build fails during building, questions come up again
and answering rebuilds. That is the loop. Turning ask-first off
restores the old behaviour: build immediately, questions afterwards.
Three reasons the old loop broke, now fixed: (1) question
extraction only matched lines starting with "Q1:", now it also
matches "Question 1:", "Q1.", "- Q1:" and similar forms. (2) Only
the answers went into the next prompt; now the previous question
list goes in too. (3) The build prompt now requires a Q-line for
every INFERRED value, and self-fix must carry previous Q-lines
forward. If the LLM still asks nothing, the result is a PASS —
that is the LLM not asking, not the code hiding questions; in an
ask-first step it writes "NO QUESTIONS" and Continue work builds
right away.

## Answer questions and continue work (answer form on the QA tab)
A result with questions is NOT a success. The banner says
"Questions pending — NOT a success", and `report.txt` says
"RESULT: QUESTIONS PENDING" (the exit code stays 0 only so the
built solid's files are kept).
A result with questions shows an answer form below the questions on
the QA tab. Fill in an answer per question and press Continue work:
the drawing and outline are taken automatically from that result,
and a new run starts with the answers reflected as `--text`. This
is a fresh run from scratch, not a resume of the old macro, and its
output goes to a new timestamped folder. The gear checkbox defaults
to the previous result's setting (from `report.txt`) and can be
changed. freecadcmd and the API key must be entered again (previous
values are not stored). Previous part notes are not carried over
automatically, so include anything still needed in the answers. An
empty answer does not run.
Note: the web UI server loads its code into memory at startup, so
after replacing files, stop and restart the server for the new UI
(questions banner, answer form, language switch) to appear.
run_pipeline is read fresh on every run, so with an old server
still running, questions can land in the report while the page
still shows the old UI.

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
