# Macro tests 1–3 — GitHub upload manifest (LOCAL ONLY, NOT yet pushed)

Prepared Oct 29, 2026. Nothing in this folder has been pushed to GitHub
yet. The parent agent will show this list to the user and get push
confirmation first. Previous pattern for test1/test2: text files via
snapshot push, binaries via the GitHub web UI by the user — confirm
that method is still used, because this packaging agent cannot do a
web-UI upload.

Dispositions: (a) = inside a results zip, (b) = separate GitHub file,
(c) = local-only, NOT uploaded. "Proposed GitHub path" is a proposal
for the user to confirm, not a push.

## Test 1 — 1U macro, v14 PASS (user-confirmed Oct 29, 2026 13:32 EDT)

| Local file | Proposed GitHub path | Disposition | Reason |
|---|---|---|---|
| test/macro_tests/macro_test1_report.md (5.4 KB) | test/macro_tests/macro_test1_report.md | (b) separate | Per-test problem / solution report; text, snapshot-pushable. |
| test/macro_tests/macro_test1_results.zip (71 KB) | test/macro_tests/macro_test1_results.zip | (b) separate binary | Results zip; see contents below. Binary, web-UI method. |
| models/csf3_1u_macro_v14.fcstd (70 KB) | inside macro_test1_results.zip | (a) in zip | Final model only; zip = fcstd + step, 2 files. |
| exports/csf3_1u_macro_v14.step (42 KB) | inside macro_test1_results.zip | (a) in zip | Final STEP only; same 2-file rule. |
| scripts/csf3_1u_macro_v14.py (13 KB) | scripts/csf3_1u_macro_v14.py | (b) separate | Final macro script; text, snapshot-pushable. Not in the zip, so the zip stays model-only. |
| exports/csf3_1u_macro_v14_preview_side.png (47 KB) | test/macro_tests/csf3_1u_macro_v14_preview_side.png | (b) separate binary | Model preview (generated from STEP), NOT a source drawing. Web-UI method. |
| exports/csf3_1u_macro_v14_preview_input_end.png (75 KB) | test/macro_tests/csf3_1u_macro_v14_preview_input_end.png | (b) separate binary | Model preview, same rule as above. |
| validations/csf3_1u_macro_v14_report.txt (5.0 KB) | — | (c) local-only | Detailed validation log; its numbers are summarised in macro_test1_report.md. No need to publish the raw log. |
| 1U v14 LLM prompt / raw response | — | (c) MISSING | No v14 prompt or raw-response file exists locally (only the validation report). Do NOT invent one. If the user wants it, it cannot be recovered from v14 files. |
| Intermediate 1U macro scripts/models v1–v13 + offsetfix (15 scripts in scripts/, validation reports in validations/) | — | (c) local-only | History is summarised in macro_test1_report.md section 2. Uploading all intermediates is an option the user can ask for, not the default. |

## Test 2 — Gear macro, v6 CLOSED (user-confirmed Oct 29, 2026 16:04 EDT)

| Local file | Proposed GitHub path | Disposition | Reason |
|---|---|---|---|
| test/macro_tests/macro_test2_report.md (7.2 KB) | test/macro_tests/macro_test2_report.md | (b) separate | Final report (finalises the draft, pending items confirmed: body chamfer D22 front X=6 + back X=13 C0.5, tap axial X=9.5). Text, snapshot-pushable. |
| test/macro_tests/macro_test2_results.zip (1.2 MB) | test/macro_tests/macro_test2_results.zip | (b) separate binary | Results zip; same 2 files as the draft zip (verified below). Binary, web-UI method. |
| models/real_drawing_gear_macro_v6.fcstd (1.1 MB) | inside macro_test2_results.zip | (a) in zip | Final model only. |
| exports/real_drawing_gear_macro_v6.step (640 KB) | inside macro_test2_results.zip | (a) in zip | Final STEP only. |
| scripts/real_drawing_gear_macro_v6.py (17 KB) | scripts/real_drawing_gear_macro_v6.py | (b) separate | Final macro script; text. Not in the zip. |
| exports/real_drawing_gear_macro_v6_preview_side.png (186 KB) | test/macro_tests/real_drawing_gear_macro_v6_preview_side.png | (b) separate binary | Model preview, NOT a source drawing. Web-UI method. |
| exports/real_drawing_gear_macro_v6_preview_iso.png (472 KB) | test/macro_tests/real_drawing_gear_macro_v6_preview_iso.png | (b) separate binary | Model preview, same rule. |
| validations/real_drawing_gear_macro_v6_report.txt (6.1 KB) | — | (c) local-only | Detailed validation log; summarised in macro_test2_report.md. |
| validations/real_drawing_gear_macro_v6_prompt.txt (20 KB) + _raw_response.txt (18 KB) | — | (c) local-only | Per the user's preference, LLM raw responses are kept in the workspace for reference, not published (same decision as the draft report section 4). |
| test/gear_macro_v6_report_DRAFT.md + gear_macro_v6_results_DRAFT.zip | — | (c) local-only, DO NOT push | Draft files kept untouched alongside the final files. Parent decides on draft cleanup after user confirmation. |
| Intermediate gear macro scripts/models v1–v5 | — | (c) local-only | History summarised in macro_test2_report.md section 2. Default: not uploaded. |

## Test 3 — New drawing macro, v5 fix3 final candidate (closure confirmation PENDING)

| Local file | Proposed GitHub path | Disposition | Reason |
|---|---|---|---|
| test/macro_tests/macro_test3_report.md (8.0 KB) | test/macro_tests/macro_test3_report.md | (b) separate | Final-candidate report; header says "closure confirmation pending", NOT closed. Text, snapshot-pushable. |
| test/macro_tests/macro_test3_results.zip (54 KB) | test/macro_tests/macro_test3_results.zip | (b) separate binary | Results zip; see contents below. Binary, web-UI method. |
| models/new_drawing_macro_v5_fix3.fcstd (49 KB) | inside macro_test3_results.zip | (a) in zip | Final-candidate model only. |
| exports/new_drawing_macro_v5_fix3.step (37 KB) | inside macro_test3_results.zip | (a) in zip | Final-candidate STEP only. |
| scripts/new_drawing_macro_v5_fix3.py (35 KB) | scripts/new_drawing_macro_v5_fix3.py | (b) separate | Final-candidate macro script; text. Not in the zip. |
| exports/new_drawing_macro_v5_fix3_preview_front.png (123 KB) | test/macro_tests/new_drawing_macro_v5_fix3_preview_front.png | (b) separate binary | Model preview, NOT a source drawing. Web-UI method. |
| exports/new_drawing_macro_v5_fix3_preview_iso.png (237 KB) | test/macro_tests/new_drawing_macro_v5_fix3_preview_iso.png | (b) separate binary | Model preview, same rule. |
| validations/new_drawing_macro_v5_fix3_report.txt (3.7 KB) + _selffix_log.txt (7.5 KB) | — | (c) local-only | Detailed validation + self-fix log; summarised in macro_test3_report.md. The self-fix log is evidence for the 3-attempt rule, but the report already carries the attempt history. |
| validations/new_drawing_macro_v5_prompt.txt (28 KB) + _raw_response.txt (32 KB), plus v1–v4 prompt/raw files | — | (c) local-only | LLM raw responses kept in the workspace for reference, not published, same as test 2. |
| Intermediate new-drawing scripts/models v1–v5, v5_fixed, v5_fix2 | — | (c) local-only | History summarised in macro_test3_report.md section 2. Default: not uploaded. |
| Diagnostic FAIL bodies (e.g. v3 FAIL_F1, v5_fix2 FAIL_F2, v5_fix3 FAIL_F4) | — | (c) local-only | Failed sketches only, NOT models. Never uploaded as results. |

## Shared / program files (not per-test, link — do not duplicate in macro_tests/)

| Local file | Proposed GitHub path | Disposition | Reason |
|---|---|---|---|
| MACRO_PRINCIPLES_EN.md (8.4 KB) | orchestrator/MACRO_PRINCIPLES_EN.md (moved Oct 29, 2026) | (b) separate, orchestrator/ | Program principles file, shared by all three tests. Reports link to it; do not copy it into each test folder. |
| GEAR_CREATION_REFERENCE.md (4.2 KB) | orchestrator/GEAR_CREATION_REFERENCE.md (moved Oct 29, 2026) | (b) separate, orchestrator/ | Gear-only reference, included in prompts only when the drawing contains a gear. Link, do not duplicate. |
| GEAR_QA_CONFIRMED.md (5.4 KB) | GEAR_QA_CONFIRMED.md (repo root) | (b) separate, repo root | Confirmed Q&A for test 2. Link from macro_test2_report.md. |
| NEW_DRAWING_QA_DRAFT.md (13 KB) | NEW_DRAWING_QA_DRAFT.md (repo root) | (b) separate, repo root, DRAFT note | Q&A draft for test 3, including the confirmed centre-peak correction. Still called DRAFT because test 3 itself is not yet closed; link with that note, do not present it as confirmed-final. |

## EXCLUDED — never uploaded, for any test

- All source drawing images the user attached / captured: main views,
  section views, annotated views, and green-outline tool outputs.
  (Exact local filenames are deliberately NOT listed here, so this
  manifest itself cannot be mistaken for an upload list. They stay
  local only.)
- Any file containing API keys, tokens, or secret-bearing content.
  Grep check on the three new reports and the three validation
  reports found no API-key / token / password strings and no
  company name. The three new reports contain no source-image
  filename.
- /tmp files, run logs that are not validation reports, and any
  diagnostic body that is not a final model.

## Zip verification (run Oct 29, 2026, `unzip -l`, exactly 2 files each)

- macro_test1_results.zip (71 KB): csf3_1u_macro_v14.fcstd
  (71,526 bytes) + csf3_1u_macro_v14.step (42,237 bytes).
- macro_test2_results.zip (1.2 MB): real_drawing_gear_macro_v6.fcstd
  (1,106,044 bytes) + real_drawing_gear_macro_v6.step (654,834
  bytes) — identical file names and sizes to the draft zip.
- macro_test3_results.zip (54 KB): new_drawing_macro_v5_fix3.fcstd
  (49,197 bytes) + new_drawing_macro_v5_fix3.step (37,525 bytes).
- All sizes non-zero. No test1/test2 file was modified; the gear
  draft files were not overwritten.

## Open questions for the user (push confirmation, via parent)

1. Push at all, and with the dispositions above (reports + scripts
   as text, zips + previews as binaries)?
2. Test 3 wording: keep "final candidate, closure confirmation
   pending" in macro_test3_report.md, or wait for closure
   confirmation before pushing test 3?
3. Binary upload method: confirm text via snapshot + binaries via
   the GitHub web UI by the user, as for test1/test2.
4. Optional, default NO: upload intermediate v1–v13 / v1–v5 /
   v1–v5 models and scripts as separate files, or keep them local
   as in this manifest?
