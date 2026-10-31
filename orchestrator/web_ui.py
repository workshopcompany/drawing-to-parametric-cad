#!/usr/bin/env python3
"""Drawing-to-Parametric-CAD local web UI (standard library only).

Runs on the user's OWN PC and talks to run_pipeline.py in the same
folder. It is NOT a cloud app, NOT a Muse web artifact, and it does
NOT let Muse control this PC. FreeCAD is still required separately.

Start (from the orchestrator/ folder, i.e. the folder holding run_pipeline.py):
  Windows:   python web_ui.py
  Mac/Linux: python3 web_ui.py
Then open http://127.0.0.1:8000/ in a browser.
Optional port: python web_ui.py --port 8001

What it does:
  1. Shows one form (English by default, Korean via ?lang=ko):
     drawing upload, part notes, gear checkbox,
     output folder, dry-run checkbox, freecadcmd, Meta API key
     (password field).
  2. On submit, first runs pre-flight checks (key present unless
     dry-run, freecadcmd findable unless dry-run). A failed check
     stops before any API call and before any output is made.
     Then it saves the uploaded drawing under the output folder
     (input_drawing.<ext>) and runs run_pipeline.py synchronously as
     a subprocess, capturing stdout/stderr to <output>/web_ui_run.log.
     A real run takes minutes; the browser waits until it finishes.
  3. Shows a result page: exit code, report.txt, guidance.txt (if
     present), and download links for files under the output folder.

Security (read this before changing anything):
  - The server binds 127.0.0.1 ONLY. It is never exposed on a network.
  - The API key is NEVER written to disk, NEVER logged, NEVER put in
    a URL, NEVER shown on a result page, and NEVER passed as a
    command-line argument. It is passed to run_pipeline.py ONLY via
    the subprocess environment (META_API_KEY), and only for that run.
  - Key sources, in order: (1) the password field on the form,
    (2) a local .env file (current folder, then next to
    web_ui.py) read by run_pipeline.py — .env is never committed
    (.gitignore blocks it). If the key field is empty, dry-run is
    off, and no .env key is present, nothing runs.
  - The form shows only whether a .env key is present, never
    the key itself.
  - Downloads are served ONLY from inside the chosen output folder.
    Any path containing ".." or resolving outside that folder is
    rejected.
  - All file contents shown on result pages are html-escaped.
"""

import argparse
import datetime
import html
import json
import mimetypes
import os
import shutil
import subprocess
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
RUN_PIPELINE = SCRIPT_DIR / "run_pipeline.py"
SAMPLE_DIR = SCRIPT_DIR / "image"
VIEWER_JS_PATH = SCRIPT_DIR / "viewer3d.js"
OUTLINE_TOOL_PATH = SCRIPT_DIR / "outline_snap_tool.html"
MAX_TRIS_BYTES = 8 * 1024 * 1024

PAGE_CSS = (
    # No external fonts: localhost-only / offline. 'IBM Plex *' names
    # below fall back to system sans-serif / monospace when absent.
    "html,body{margin:0;padding:0;background:#0a0c10;color:#c8d0e0;"
    "font-family:'IBM Plex Sans',sans-serif;}"
    "h1,h2,h3{font-family:'IBM Plex Mono',monospace;}"
    ".layout{display:flex;min-height:100vh;}"
    ".sidebar{width:284px;flex:0 0 284px;background:#0d0f14;"
    "border-right:1px solid #1e2330;padding:22px 18px;box-sizing:border-box;}"
    ".sidebar *{color:#c8d0e0;}"
    ".sidebar h2{font-size:18px;color:#7eb8f7;margin:0 0 4px;}"
    ".sidebar .sub{font-size:12px;color:#8fa0bd;margin:0 0 14px;}"
    ".sidebar hr{border-color:#1e2330;}"
    ".main{flex:1;padding:26px 30px;max-width:1180px;box-sizing:border-box;}"
    ".card{background:#111520;border:1px solid #1e2330;border-radius:8px;"
    "padding:18px 20px;margin-bottom:14px;}"
    ".grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px;}"
    "@media (max-width:900px){.grid2{grid-template-columns:1fr;}"
    ".layout{flex-direction:column;}.sidebar{width:100%;flex:auto;}}"
    ".feat-pill{display:inline-block;background:#12203a;border:1px solid #1e3a6e;"
    "border-radius:20px;padding:3px 12px;font-size:12px;color:#5ba3f5;"
    "margin-right:6px;margin-bottom:6px;font-family:'IBM Plex Mono',monospace;}"
    ".var-badge{display:inline-block;background:#1a1f2e;border:1px solid #2a3450;"
    "border-radius:4px;padding:1px 7px;font-family:'IBM Plex Mono',monospace;"
    "font-size:12px;color:#7eb8f7;margin-right:4px;margin-bottom:4px;}"
    ".status-ok{color:#4ade80;font-weight:600;}"
    ".status-warn{color:#facc15;font-weight:600;}"
    ".status-err{color:#f87171;font-weight:600;}"
    "label{display:block;margin:1em 0 0.3em;font-weight:600;font-size:13px;}"
    "input[type=text],input[type=password],textarea{width:100%;box-sizing:border-box;"
    "background:#131824;color:#c8d0e0;border:1px solid #2a3450;border-radius:5px;"
    "padding:8px 10px;font-family:'IBM Plex Mono',monospace;font-size:13px;}"
    "textarea{height:6em;font-family:'IBM Plex Sans',sans-serif;}"
    "input[type=file]{width:100%;font-size:13px;color:#c8d0e0;}"
    "button,.btn{background:#1a2540 !important;color:#7eb8f7 !important;"
    "border:1px solid #2a3f6e !important;border-radius:6px !important;"
    "font-family:'IBM Plex Mono',monospace !important;font-size:13px !important;"
    "padding:0.6em 1.5em;cursor:pointer;text-decoration:none;display:inline-block;}"
    "button:hover,.btn:hover{background:#243260 !important;border-color:#4a6aae !important;}"
    "pre{white-space:pre-wrap;background:#0d1117;border:1px solid #1e2330;"
    "color:#c8d0e0;padding:1em;overflow:auto;border-radius:6px;max-height:420px;"
    "font-family:'IBM Plex Mono',monospace;font-size:12px;}"
    ".note{color:#8fa0bd;font-size:12px;}"
    "code{font-family:'IBM Plex Mono',monospace;background:#1a1f2e;"
    "padding:1px 5px;border-radius:4px;font-size:12px;}"
    "hr{border-color:#1e2330 !important;}"
    "img.shot{max-width:100%;border:1px solid #1e2330;border-radius:8px;background:#0d1117;"
    "cursor:zoom-in;display:block;}"
    "img.preview-live{max-width:100%;max-height:320px;border:1px solid #2a3450;"
    "border-radius:8px;background:#0d1117;display:none;margin-top:8px;}"
    ".drop-hint{border:1px dashed #2a3450;border-radius:8px;padding:10px;margin-top:8px;"
    "font-size:12px;color:#8fa0bd;}"
    "table.files{width:100%;border-collapse:collapse;font-size:13px;}"
    "table.files td,table.files th{border-bottom:1px solid #1e2330;padding:6px 8px;"
    "text-align:left;font-family:'IBM Plex Mono',monospace;font-size:12px;}"
    "table.files a{color:#7eb8f7;}"
    ".tabs{display:flex;gap:8px;margin:14px 0;flex-wrap:wrap;}"
    ".tab-btn{background:#131824;border:1px solid #2a3450;color:#c8d0e0;"
    "border-radius:6px;padding:8px 14px;cursor:pointer;"
    "font-family:'IBM Plex Mono',monospace;font-size:13px;}"
    ".tab-btn.active{background:#1a2540;color:#7eb8f7;border-color:#4a6aae;}"
    ".tab-panel{display:none;}"
    ".tab-panel.active{display:block;}"
    "a{color:#7eb8f7;}"
    ".viewer-wrap{position:relative;background:#0d1117;border:1px solid #1e2330;"
    "border-radius:8px;overflow:hidden;}"
    ".viewer-wrap canvas{width:100%;height:420px;display:block;cursor:grab;touch-action:none;}"
    ".viewer-bar{position:absolute;left:8px;top:6px;color:#8fb0c8;"
    "font:11px/1.4 monospace;text-shadow:0 0 3px #000;pointer-events:none;"
    "white-space:nowrap;overflow:hidden;max-width:96%;}"
    ".viewer-tools{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px;}"
    ".viewer-tools button{padding:0.4em 0.9em;}"
    ".kv{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;font-size:12px;"
    "font-family:'IBM Plex Mono',monospace;}"
)

FOOTER_KO = (
    "<hr><p class=\"note\">실행 방법 — Windows: <code>python web_ui.py</code> / "
    "Mac·Linux: <code>python3 web_ui.py</code> — 그 뒤 브라우저에서 "
    "http://127.0.0.1:8000/ 을 여세요.<br>"
    "이 UI는 사용자의 PC(127.0.0.1)에서만 돌아가며, Muse가 이 PC를 조종하게 하지 않습니다. "
    "FreeCAD도 대신하지 않습니다. FreeCAD 1.1.4가 필요하고, freecadcmd가 PATH에 "
    "없으면 실행 설정 칸에 전체 경로를 입력하세요.<br>"
    "스타일 참조: mp3d-cad-system 대시보드(다크 테마 · 사이드바 · 2단 카드 · 탭 결과).</p>"
)



# ---- Language: English is the default; Korean via ?lang=ko ----
def pick_lang(value):
    """'ko' only when explicitly asked; anything else is English."""
    return "ko" if value == "ko" else "en"


S = {
    # recent runs / samples / viewer
    "recent_title": ("Recent runs (open without rerunning)",
                      "최근 실행 결과 바로 보기"),
    "recent_note": ("Open a previous result without rerunning. "
                    "New results appear here too.",
                    "재실행 없이 눈으로 확인. 새 결과도 아래 목록에 바로 뜹니다."),
    "recent_empty": ("No recent runs yet. Pick a drawing above and run.",
                     "최근 실행 기록이 없습니다. 위에서 도면을 골라 실행하세요."),
    "th_folder": ("Output folder", "출력 폴더"),
    "th_status": ("Status", "상태"),
    "th_open": ("Open", "바로 보기"),
    "open_link": ("Open", "열기"),
    "outline_note1": ("To draw an outline yourself, open the ",
                      "윤곽을 직접 그리고 싶으면 "),
    "outline_note2": (" -> download JSON -> attach it on the left.",
                      " → JSON 다운 → 왼쪽 윤곽 첨부에 올리세요."),
    "sample_title": ("Bundled sample drawings (click for full size)",
                     "번들 샘플 도면 (클릭하면 원본 크기)"),
    "sample_empty": ("No samples in the image/ folder.",
                     "image/ 폴더에 샘플이 없습니다."),
    "sample_note": ("Drawings in the image/ folder. They are server "
                   "files, so you can look without uploading.",
                   "image/ 폴더에 들어있는 도면입니다. 서버 파일이라 "
                   "업로드 없이 바로 눈으로 확인됩니다."),
    "sample_original": ("Full size", "원본 크기"),
    "sample_use_note": ("To use it as the drawing for a run, pick "
                        "this file on the left.",
                        "실행 시 도면으로 쓰려면 이 파일을 왼쪽에서 직접 고르세요."),
    "viewer_title": ("Interactive 3D viewer (tris.json)",
                     "돌려보는 3D 뷰어 (tris.json)"),
    "viewer_note": ("Drag to rotate, wheel to zoom, buttons to change "
                   "view. No CDN, runs on this page only. "
                   "{n} facets. The PNG below is a still image of "
                   "the same shape.",
                   "드래그 회전 · 휠 줌 · 버튼 시점 전환. CDN 없이 이 페이지 "
                   "안에서만 돕니다. facet {n}개 · 아래 PNG는 같은 형상의 "
                   "정지 이미지입니다."),
    "viewer_none": ("No viewer ({why} See the PNG previews below.)",
                    "뷰어 없음 ({why} 아래 PNG 프리뷰를 보세요)."),
    "viewer_missing": ("no <code>tris.json</code> (not a freecadcmd result).",
                       "<code>tris.json</code> 없음 (freecadcmd 결과가 아닙니다)."),
    "viewer_toolarge": ("<code>tris.json</code> over 8MB — skipped to "
                        "protect the browser.",
                        "<code>tris.json</code> 8MB 초과 — 브라우저 보호를 위해 뷰어 생략."),
    "viewer_scope": ("path outside the folder.", "범위 밖 경로."),
    "viewer_badshape": ("<code>tris.json</code> format error.",
                        "<code>tris.json</code> 형식 오류."),
    "viewer_loading": ("Loading…", "로딩 중…"),
    "view_iso": ("ISO", "ISO"),
    "view_main": ("Front (large face)", "정면(큰 면)"),
    "view_top": ("Top", "위"),
    "view_side": ("Side", "옆"),
    # result page
    "success": ("✅ Modeling complete (exit code 0)",
                "✅ 모델링 생성완료 (종료 코드 0)"),
    "failure": ("❌ Failed (exit code {code})",
                "❌ 실패 (종료 코드 {code})"),
    "questions_pending": ("❓ Questions pending — modeling complete, "
                          "not a success (answer and continue, see "
                          "questions.txt)",
                          "❓ 질문 대기 중 — 모델링 생성완료, 성공 아님 "
                          "(답변하고 계속 작업하세요, questions.txt 확인)"),
    "tab_matching": ("Drawing ↔ Modeling match", "도면 ↔ 모델링 매칭"),
    "matching_title": ("Drawing ↔ Modeling matching table",
                        "도면 ↔ 모델링 매칭표"),
    "matching_note": ("Drawing value = the value the LLM read from the "
                      "drawing and wrote into the macro (or a D-dimension "
                      "from the ask-first step, or a user-confirmed "
                      "answer). It is NOT a directly measured drawing "
                      "truth: if the LLM misread the drawing, both "
                      "columns can be wrong together. Modeling value = "
                      "measured from the STEP file. O = within 0.01 mm, "
                      "X = differs, ? = cannot be mapped automatically, "
                      "~ = reference only.",
                      "도면값 = LLM이 도면에서 읽어 매크로에 쓴 값 (질문 "
                      "먼저 단계의 D치수, 또는 사용자가 확인한 답변). "
                      "도면을 직접 측정한 진값이 아닙니다. LLM이 도면을 "
                      "잘못 읽으면 양쪽이 같이 틀릴 수 있습니다. 모델링값 "
                      "= STEP 파일에서 측정한 값. O = 0.01mm 이내, X = "
                      "다름, ? = 자동 매핑 불가, ~ = 참고용."),
    "matching_numbered_note": ("Numbered drawing below: red badges are the "
                               "D-numbers from the ask-first step. Badge "
                               "positions are APPROXIMATE (LLM vision "
                               "estimates), not measured locations. The "
                               "table is authoritative; check badges "
                               "against the original drawing.",
                               "아래 번호 도면: 빨간 배지는 질문 먼저 단계의 "
                               "D번호입니다. 배지 위치는 대략적인 위치"
                               "(LLM 비전 추정치)이며 측정 위치가 아닙니다. "
                               "표가 기준이고, 배지는 원본 도면과 대조해 "
                               "확인하세요."),
    "matching_no_numbered": ("No numbered drawing in this result. Run "
                             "with Ask questions first to get a numbered "
                             "drawing; this table then uses the D-numbers.",
                             "이 결과에는 번호 도면이 없습니다. 질문 먼저로 "
                             "실행하면 번호 도면이 생기고, 표도 D번호를 "
                             "씁니다."),
    "th_no": ("No.", "번호"),
    "th_item": ("Item", "항목"),
    "th_drawing": ("Drawing value", "도면값"),
    "th_modeling": ("Modeling value", "모델링값"),
    "th_result": ("Result", "결과"),
    "matching_legend": ("O = within 0.01 mm, X = differs, "
                       "? = cannot be compared this way, "
                       "? (참조치수) = reference dimension (not driving), "
                       "~ = reference only.",
                       "O는 0.01mm 이내, X는 다름, ?는 이런 방식으로는 비교 불가, "
                       "? (참조치수)는 참조치수(구동치수 아님), "
                       "~는 참고용."),
    "matching_disclaimer": ("Drawing value is the value read by the LLM, "
                            "or an answer you confirmed. This checks "
                            "\u201cwas it built as intended?\u201d, not proof "
                            "that it \u201cequals the drawing truth\u201d.",
                            "도면값은 LLM이 읽은 값, 또는 네가 확인한 답이야. "
                            "\u201c의도한 대로 만들었나\u201d를 보는 거지, "
                            "\u201c도면 진값과 같나\u201d를 증명이 아님."),
    "th_measured": ("Measured", "실측값"),
    "measure_btn": ("Measure", "실측"),
    "measure_note": ("Measure real geometry from the STEP and add a "
                     "Measured column next to Modeling value. The measured "
                     "value has no verdict: compare it with the drawing "
                     "value yourself.",
                     "STEP에서 실제 형상을 재서 모델링값 옆에 실측값 칸을 "
                     "추가합니다. 실측값에는 판정이 없습니다. 도면값과 "
                     "직접 비교하세요."),
    "measure_done": ("Measured.", "실측 완료."),
    "err_measure_nostep": ("No model.step in this folder to measure.",
                           "이 폴더에 실측할 model.step이 없습니다."),
    "err_measure_failed": ("Measurement failed. See web_ui_measure.log and "
                           "measure_log.txt in the folder.",
                           "실측에 실패했습니다. 폴더의 web_ui_measure.log와 "
                           "measure_log.txt를 보세요."),
    "th_select": ("Select", "선택"),
    "export_note": ("Check rows to save only those rows.",
                    "저장할 행에 체크하세요. 체크한 행만 저장됩니다."),
    "export_format": ("Format", "형식"),
    "fmt_csv": ("CSV (Excel, Google Sheets)",
                "CSV (엑셀, 구글 시트 모두 가능)"),
    "fmt_xlsx": ("Excel (.xlsx)", "엑셀 (.xlsx)"),
    "select_all": ("Select all", "전체 선택"),
    "deselect_all": ("Deselect all", "전체 해제"),
    "save_table": ("Save table", "테이블 저장"),
    "err_export_empty": ("Select at least one row to save.",
                         "저장할 행을 하나 이상 선택하세요."),
    "err_export_nomatch": ("No matching table in this folder.",
                           "이 폴더에 매칭표가 없습니다."),
    "err_export_format": ("Unknown format.",
                          "알 수 없는 형식입니다."),
    "matching_none": ("No matching table in this result (older run). "
                      "Solids, validity, volume, and bbox are in "
                      "report.txt.",
                      "이 결과에는 매칭표가 없습니다 (예전 실행). 솔리드, "
                      "유효성, 부피, bbox는 report.txt에 있습니다."),
    "askfirst_banner": ("⏳ Ask-first done — no model yet, press "
                        "Continue work to build",
                        "⏳ 질문 먼저 완료 — 아직 모델이 없습니다, "
                        "계속 작업을 눌러 만드세요"),
    "answer_askfirst_note": ("No model was built yet in this result "
                             "(ask-first step) — Continue work will "
                             "build it with your answers.",
                             "이 결과에는 아직 모델이 없습니다 (질문 먼저 "
                             "단계) — 계속 작업을 누르면 답을 반영해 "
                             "만듭니다."),
    "result_sidebar": ("Result", "실행 결과"),
    "result_heading": ("Result", "실행 결과"),
    "back_form": ("← Back to form", "← 폼으로 돌아가기"),
    "output_folder": ("Output folder", "출력 폴더"),
    "pill_fcstd": ("Main .fcstd", ".fcstd 본체"),
    "pill_previews": ("Previews {n}", "프리뷰 {n}장"),
    "tab_drawing": ("Drawing recognition", "도면 인식"),
    "tab_params": ("Parameters & 3D", "파라미터 & 3D"),
    "tab_export": ("FreeCAD export", "FreeCAD 내보내기"),
    "tab_qa": ("QA log", "QA 로그"),
    "input_title": ("Original / input images",
                    "원본 / 입력 이미지"),
    "input_note": ("Shows <code>input_drawing.*</code> / "
                   "<code>input_outline.*</code> from the output folder "
                   "right in the browser.",
                   "출력 폴더의 <code>input_drawing.*</code> / "
                   "<code>input_outline.*</code> 을 브라우저에서 바로 봅니다."),
    "input_caption": ("Input drawing / outline (browser view)",
                      "입력 도면 / 윤곽 (브라우저 보기)"),
    "input_none": ("No input images.", "입력 이미지가 없습니다."),
    "preview_caption": ("Shaded preview from STEP tessellation — "
                        "for shape checking",
                        "STEP 테셀레이션 음영 프리뷰 — 형상 확인용"),
    "preview_none": ("No result previews (render failed — check "
                     ".fcstd / STEP in the file list above).",
                     "결과 프리뷰가 없습니다 (렌더 실패 — .fcstd / STEP 파일 "
                     "자체는 위 목록을 확인)."),
    "files_title": ("Output files", "출력 파일"),
    "th_file": ("File", "파일"),
    "th_bytes": ("bytes", "bytes"),
    "th_link": ("Links", "링크"),
    "download": ("Download", "다운로드"),
    "view_link": ("View", "보기"),
    "questions_title": ("questions.txt (unanswered questions)",
                        "questions.txt (미답변 질문)"),
    "questions_none": ("(None — this macro asked no questions)",
                       "(없음 — 이번 매크로에 질문이 없습니다)"),
    "questions_note": ("Questions taken from the macro comments/output. "
                       "This result was built with provisional values, "
                       "so answer and continue below.",
                       "매크로 주석/출력에서 뽑은 질문입니다. 임시값으로 만든 "
                       "결과라면, 답을 주고 다시 실행하세요."),
    "continue_folder_title": ("Continue from a work folder",
                               "작업 폴더에서 이어서 작업"),
    "continue_folder_note": ("Pick a previous result folder and rerun it. "
                             "The saved drawing (and outline, Q&A history, "
                             "numbered dimensions) from that folder is "
                             "reused, so you do not need to upload a "
                             "drawing again. The list shows folders next "
                             "to the server; to only open a folder and "
                             "look at it, use the path box below or a "
                             "link in the recent list. The folder must "
                             "already hold a result. This picker is only "
                             "for continuing existing work. To start "
                             "fresh, just run from the main form — a new "
                             "folder is created automatically, no need "
                             "to pick one.",
                             "이전 결과 폴더를 골라 다시 실행하세요. 그 "
                             "폴더에 저장된 도면(과 윤곽, Q&A 내역, 번호 "
                             "도면)이 그대로 쓰이므로 도면을 다시 올릴 "
                             "필요가 없습니다. 목록은 서버 옆 폴더들이고, "
                             "폴더를 열어서 보기만 하려면 아래 경로 입력란이나 "
                             "최근 목록의 링크를 쓰세요. 폴더에는 이미 "
                             "결과가 있어야 합니다. 이 선택기는 기존 작업 "
                             "이어가기 전용입니다. 새로 시작하려면 폴더를 "
                             "고를 필요 없이 메인 폼에서 그냥 실행하세요. "
                             "새 폴더가 자동으로 생깁니다."),
    "continue_folder_pick": ("Rerun selected folder", "선택한 폴더 다시 실행"),
    "continue_folder_path": ("Or type a folder path (absolute)",
                             "또는 폴더 경로 직접 입력 (절대 경로)"),
    "continue_folder_open": ("Open folder", "폴더 열기"),
    "continue_title": ("▶ Continue this project",
                        "▶ 이 프로젝트 이어서 작업"),
    "continue_note": ("Write new instructions below and press Continue "
                      "work: the drawing/outline and Q&A history from "
                      "this result are reused, and a fresh run starts. "
                      "This does not patch the old model.",
                      "아래에 새 지시를 적고 계속 작업을 누르면, 이 "
                      "결과의 도면/윤곽/Q&A 내역이 재사용되고 새 실행이 "
                      "시작됩니다. 이전 모델을 고치는 게 아니라 새로 "
                      "만드는 실행입니다."),
    "continue_label": ("New instructions", "새 지시"),
    "answer_title": ("✏️ Answer questions and continue work",
                    "✏️ 질문에 답하고 계속 작업"),
    "answer_note": ("Write your answers below and press Continue work: "
                    "the drawing/outline are taken automatically from "
                    "this result, and the full Q&A history so far is "
                    "included automatically, so write only the new "
                    "answers. This is a fresh run from scratch, not a "
                    "patch to the old macro. Output goes to a new "
                    "timestamped folder, where the accumulated Q&A is "
                    "saved as qa_history.txt.",
                    "아래에 답을 적고 계속 작업을 누르면, 도면/윤곽은 이 "
                    "결과에서 자동으로 가져오고 지금까지의 Q&A 내역도 "
                    "자동으로 포함되니 새 답변만 적으면 됩니다. 이전 "
                    "매크로를 이어서 고치는 게 아니라, 처음부터 새로 "
                    "만드는 실행입니다. 출력은 시간 붙은 새 폴더에 "
                    "생기고, 누적된 Q&A는 새 폴더의 qa_history.txt에 "
                    "저장됩니다."),
    "answer_label": ("Answers (one per question)",
                     "답변 (질문별로 적으세요)"),
    "key_note": ("Key is not stored, used only for this run. Empty "
                 "means use the repo folder .env key.",
                 "키는 저장되지 않고 이번 실행에만 사용. 비우면 레포 폴더 "
                 ".env 키 사용."),
    "gear_label": ("Gear part", "기어 부품"),
    "dry_label": ("dry-run (assemble the prompt only)",
                  "dry-run (프롬프트 조립만 확인)"),
    "continue_button": ("▶ Continue work", "▶ 계속 작업"),
    "continue_button_note": ("Continue work starts a fresh run from "
                             "scratch using this work's history "
                             "(drawing, outline, Q&A history, numbered "
                             "dimensions). It does not patch the old "
                             "model — a new model is built in a new "
                             "timestamped folder.",
                             "계속 작업은 이 작업의 히스토리(도면, 윤곽, "
                             "Q&A 내역, 번호 도면)를 가지고 처음부터 새로 "
                             "만드는 실행입니다. 이전 모델을 고치는 게 "
                             "아니라 새 폴더에 새 모델을 만듭니다."),
    "report_title": ("report.txt", "report.txt"),
    "report_none": ("(none)", "(없음)"),
    "guidance_title": ("guidance.txt", "guidance.txt"),
    "guidance_none": ("(none — not created on success)",
                      "(없음 — 성공 시 생기지 않습니다)"),
    "log_title": ("Run log (tail)", "실행 로그 (끝부분)"),
    "log_none": ("(none)", "(없음)"),
    "click_full": (" Click for full size in a new tab.",
                   " 클릭하면 원본 크기로 새 탭에 열립니다."),
    # error page
    "error_heading": ("Error", "오류"),
    "error_back": ("← Back to form", "← 폼으로 돌아가기"),
    # POST errors
    "err_form": ("Bad form format. Submit from the form again.",
                 "폼 형식이 올바르지 않습니다. 폼에서 다시 제출하세요."),
    "err_parse": ("Upload parsing failed. Try again.",
                  "업로드 파싱에 실패했습니다. 다시 제출하세요."),
    "err_prev_dir": ("Previous result folder not found.",
                     "이전 결과 폴더를 찾을 수 없습니다."),
    "err_answers_empty": ("Write your answers first.",
                          "답변을 입력하세요."),
    "err_prev_no_drawing": ("No drawing (input_drawing.*) in the "
                            "previous result.",
                            "이전 결과에 도면(input_drawing.*)이 없습니다."),
    "err_key": ("Enter an API key, pick dry-run, or make a .env file "
                "in the repo folder.",
                "API 키를 입력하거나, dry-run을 선택하거나, "
                "레포 폴더에 .env 파일을 만드세요."),
    "err_freecadcmd": ("freecadcmd not found. Check FreeCAD 1.1.4 is "
                       "installed and enter its full path in the "
                       "freecadcmd box. Windows example: "
                       "C:\\Program Files\\FreeCAD 1.1.4\\bin\\freecadcmd.exe "
                       "(depends on the install folder). No API call "
                       "was made at this step.",
                       "freecadcmd를 찾을 수 없습니다. FreeCAD 1.1.4가 설치돼 있는지 "
                       "확인하고, freecadcmd 칸에 전체 경로를 입력하세요. "
                       "Windows 예: C:\\Program Files\\FreeCAD 1.1.4\\bin\\freecadcmd.exe "
                       "(설치 폴더에 따라 다릅니다). 이 단계에서 API는 호출되지 "
                       "않았습니다."),
    "err_drawing": ("Pick a drawing image.",
                    "도면 이미지를 선택하세요."),
    "err_result_dir": ("Cannot open the result folder.",
                       "결과 폴더를 열 수 없습니다."),
    "err_result_empty": ("No folder was given. Pick a folder from the "
                         "list, or type a folder path in the box.",
                         "폴더가 지정되지 않았습니다. 목록에서 폴더를 "
                         "고르거나 경로 입력란에 폴더 경로를 입력하세요."),
    "err_result_missing": ("That folder does not exist. Check the path. "
                           "To start fresh, just run from the main form "
                           "— a new timestamped folder is created "
                           "automatically. This picker only opens folders "
                           "that already hold a result.",
                           "해당 폴더가 없습니다. 경로를 확인하세요. 새로 "
                           "시작하려면 메인 폼에서 그냥 실행하세요. 새 "
                           "타임스탬프 폴더가 자동으로 생깁니다. 이 선택기는 "
                           "이미 결과가 있는 폴더만 엽니다."),
    "err_result_nofiles": ("That folder holds no result files "
                           "(report.txt, guidance.txt, or model.step). "
                           "Pick an existing result folder to continue "
                           "it, or just run from the main form to start "
                           "fresh — a new folder is created automatically.",
                           "해당 폴더에 결과 파일(report.txt, "
                           "guidance.txt, model.step 중 하나)이 없어서 열 "
                           "수 없습니다. 이어서 작업할 기존 결과 폴더를 "
                           "고르거나, 새로 시작하려면 메인 폼에서 그냥 "
                           "실행하세요. 새 폴더가 자동으로 생깁니다."),
    "err_view_file": ("This file cannot be viewed in the browser.",
                      "브라우저에서 볼 수 없는 파일입니다."),
    "err_download_path": ("Cannot download this path.",
                          "다운로드할 수 없는 경로입니다."),
}


def tr(lang, key, **kw):
    """Translate key; lang 'ko' picks Korean, anything else English."""
    pair = S.get(key, ("", ""))
    text = pair[1] if lang == "ko" else pair[0]
    return text.format(**kw) if kw else text


FOOTER_EN = (
    "<hr><p class=\"note\">How to run — Windows: <code>python web_ui.py</code> / "
    "Mac·Linux: <code>python3 web_ui.py</code> — then open "
    "http://127.0.0.1:8000/ in a browser.<br>"
    "This UI runs only on your PC (127.0.0.1) and does not let Muse control "
    "this PC. It does not replace FreeCAD. FreeCAD 1.1.4 is required; if "
    "freecadcmd is not in PATH, enter its full path in the run settings box.<br>"
    "Style reference: mp3d-cad-system dashboard (dark theme · sidebar · "
    "2-column cards · tabbed results).</p>"
)


def dotenv_key_present():
    """True if a local .env file holds a non-empty META_API_KEY.

    Checks .env in the current folder, then next to this script.
    Returns a boolean only — the key value is never returned,
    shown, or logged anywhere in this UI.
    """
    for dotenv in (Path.cwd() / ".env", SCRIPT_DIR / ".env"):
        try:
            text = dotenv.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() == "META_API_KEY" and value.strip().strip('"').strip("'"):
                return True
    return False


def freecadcmd_found(value):
    """True if freecadcmd is an existing file path or found in PATH."""
    if not value:
        return False
    if Path(value).expanduser().is_file():
        return True
    return shutil.which(value) is not None


def page(title, body, lang="en"):
    return (
        f"<!DOCTYPE html><html lang=\"{lang}\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{html.escape(title)}</title>"
        f"<style>{PAGE_CSS}</style></head><body>"
        f"{body}{(FOOTER_KO if lang == 'ko' else FOOTER_EN)}</body></html>"
    ).encode("utf-8")


def form_page_ko():
    status = ("있음" if dotenv_key_present()
              else "없음 (키 칸에 입력하거나, 레포 폴더에 .env 파일을 만드세요)")
    body = f"""
<form action="/run" method="post" enctype="multipart/form-data" id="runForm">
<input type="hidden" name="lang" value="ko">
<div class="layout">
  <div class="sidebar">
    <h2>&#11042; Drawing&rarr;CAD</h2>
    <p class="note"><a href="/?lang=en">English</a> · 한국어</p>
    <p class="sub">orchestrator v0.1 &middot; localhost only</p>
    <hr>
    <h3 style="font-size:14px;">&#128193; 파일 열기</h3>
    <label for="drawing">도면 이미지 (PNG/JPG)</label>
    <input type="file" id="drawing" name="drawing" accept=".png,.jpg,.jpeg,.webp,.gif,.bmp" required>
    <div class="drop-hint">PDF는 아직 지원하지 않습니다. PDF 도면은 이미지(PNG/JPG)로 바꿔서 올려주세요.</div>
    <div class="drop-hint">파일을 고르면 전송 전에 이 브라우저 안에서만 미리보기가 뜹니다.</div>
    <img id="drawingPreview" class="preview-live" alt="도면 미리보기">
    <label for="outline">윤곽 첨부 (선택, JSON/이미지)</label>
    <input type="file" id="outline" name="outline" accept=".json,.bin,.png,.jpg,.jpeg,image/*,.txt">
    <img id="outlinePreview" class="preview-live" alt="윤곽 미리보기">
    <p class="note">outline_snap_tool.html 출력 JSON 또는 윤곽 이미지. 원본은 출력 폴더에 input_outline.* 로 보관.</p>
    <hr>
    <h3 style="font-size:14px;">&#129521; 실행 설정</h3>
    <label for="output_dir">출력 폴더</label>
    <input type="text" id="output_dir" name="output_dir" value="./my_run_output">
    <p class="note">기본값이면 실행 시각이 붙은 폴더(예: my_run_output_20261030_090411)로 자동 생성돼 예전 결과가 덮어씌워지지 않습니다. 이미 결과가 있는 폴더를 지정하면 시각이 붙은 형제 폴더로 바뀝니다.</p>
    <label for="freecadcmd">freecadcmd</label>
    <input type="text" id="freecadcmd" name="freecadcmd" value="freecadcmd">
    <label><input type="checkbox" name="dry_run" value="on" style="width:auto;"> dry-run (프롬프트 조립만 확인)</label>
    <label><input type="checkbox" name="gear" value="on" style="width:auto;"> 기어 부품 (체크 시에만 기어 참조 포함)</label>
    <label><input type="checkbox" name="ask_first" value="on" checked style="width:auto;"> 질문 먼저 (답하기 전에는 모델을 만들지 않음)</label>
    <label for="api_key">Meta API 키</label>
    <input type="password" id="api_key" name="api_key" autocomplete="off">
    <p class="note">키는 저장되지 않고 이번 실행에만 사용. 비우면 레포 폴더 .env 키 사용.</p>
    <p class="note">.env 키: {html.escape(status)}</p>
    <button type="submit" id="runBtn" style="width:100%;margin-top:1em;">&#9654; 실행</button>
    <div id="runState" class="drop-hint" style="display:none;">실행 중… 수 분 걸립니다. 브라우저를 닫지 마세요.</div>
    <p class="note">실제 실행은 몇 분 걸립니다. 끝날 때까지 브라우저를 닫지 마세요.</p>
  </div>
  <div class="main">
    <h2 style="color:#7eb8f7;font-size:22px;margin:0;">도면 &rarr; 파라메트릭 CAD</h2>
    <p class="note">Meta API가 FreeCAD 매크로를 만들고, freecadcmd가 <code>.fcstd</code> + <code>STEP</code> + 보고서를 만듭니다.
    왼쪽에서 도면을 고르고, 아래 탭에서 설명을 확인한 뒤 <code>▶ 실행</code>을 누르세요.</p>
    <p><span class="feat-pill">Body&rarr;Sketch&rarr;Pad/Pocket</span><span class="feat-pill">.fcstd 본체</span><span class="feat-pill">STEP export</span></p>
    <div class="tabs">
      <button type="button" class="tab-btn active" data-tab="t1">&#128008; 도면 인식</button>
      <button type="button" class="tab-btn" data-tab="t2">&#128207; 파라미터 &amp; 3D</button>
      <button type="button" class="tab-btn" data-tab="t3">&#128295; FreeCAD 내보내기</button>
      <button type="button" class="tab-btn" data-tab="t4">&#128269; QA 로그</button>
    </div>
    <div class="tab-panel active" id="t1">
      <div class="grid2">
        <div class="card"><h3>원본 / 입력 (고르기 전에도 샘플 확인)</h3>
        <p class="note">왼쪽에서 고르면 브라우저 미리보기가 여기에도 동시에 뜹니다. 클릭하면 원본 크기로 새 탭에 열립니다.</p>
        <img id="drawingPreviewMain" class="shot" style="display:none;" alt="도면 미리보기"></div>
        <div class="card"><h3>부품 설명</h3>
        <label for="notes">부품 설명 (선택)</label>
        <textarea id="notes" name="notes" placeholder="예: 베이스 D2.8, 요크 폭 4.8 ..."></textarea>
        <p class="note">치수를 지어내지 않습니다. 모호하면 멈추고 guidance.txt에 질문을 남깁니다.</p></div>
      </div>
      {recent_html("ko")}
    </div>
    <div class="tab-panel" id="t2">
      <div class="grid2">
        <div class="card"><h3>&#128207; 치수 파라미터</h3>
        <p class="note">매크로 상단 파라미터 블록에서 치수를 확인하세요. <span class="var-badge">INFERRED</span> 값은 LLM 추정치이므로 FreeCAD에서 치수를 바꿔 재계산해 단일 유효 솔리드인지 확인하세요.</p></div>
      <div class="card"><h3>&#129521; 3D 미리보기</h3>
      <p class="note">실행 후 같은 형상을 두 방식으로 눈으로 확인합니다:
      돌려보는 3D 뷰어(tris.json 기준, CDN 없음) + 음영 이미지
      (preview_iso/main.png, Pillow 폴백이라 설치 없이 항상 생성).</p></div>
      </div>
    </div>
    <div class="tab-panel" id="t3">
      <div class="card"><h3>&#128295; FreeCAD 내보내기 설정</h3>
      <p class="note">왼쪽 사이드바의 출력 폴더 &middot; freecadcmd &middot; dry-run &middot; 기어 체크가 그대로 쓰입니다. 제출하면 키 &middot; freecadcmd 유무를 먼저 점검하고 통과해야 API를 호출합니다. 결과는 <code>model.fcstd</code>가 본체, <code>model.step</code>은 export입니다.</p>
      <button type="submit">&#9654; 이 설정으로 실행</button></div>
    </div>
    <div class="tab-panel" id="t4">
      <div class="card"><h3>&#128269; QA 로그</h3>
      <p class="note">합격 기준: <code>solids == 1</code> and <code>valid == True</code> (STEP 독립 검증). 부피 &middot; bbox는 참고용. 매크로 로그 PASS만으로는 합격하지 않습니다. 코드/API 오류만 최대 3회 자가수정, 3회 실패 시 피처명 &middot; 기하번호 &middot; 정확한 에러 &middot; 원인 &middot; 질문을 남기고 멈춥니다.</p></div>
    </div>
  </div>
</div>
</form>
{picker_html("ko")}
{sample_gallery_html("ko")}
<script>
(function(){{
  function showFile(inputId, imgIds){{
    var input = document.getElementById(inputId);
    if (!input) return;
    input.addEventListener('change', function(){{
      var f = input.files && input.files[0];
      imgIds.forEach(function(id){{
        var img = document.getElementById(id);
        if (!img) return;
        if (!f || (f.type || '').indexOf('image/') !== 0) {{
          img.style.display = 'none';
          img.removeAttribute('src');
          return;
        }}
        if (img.dataset.url) URL.revokeObjectURL(img.dataset.url);
        var url = URL.createObjectURL(f);
        img.dataset.url = url;
        img.src = url;
        img.style.display = 'block';
      }});
    }});
  }}
  showFile('drawing', ['drawingPreview', 'drawingPreviewMain']);
  showFile('outline', ['outlinePreview']);
  document.querySelectorAll('.tab-btn').forEach(function(b){{
    b.addEventListener('click', function(){{
      document.querySelectorAll('.tab-btn').forEach(function(x){{x.classList.remove('active');}});
      document.querySelectorAll('.tab-panel').forEach(function(x){{x.classList.remove('active');}});
      b.classList.add('active');
      document.getElementById(b.dataset.tab).classList.add('active');
    }});
  }});
  document.querySelectorAll('img.shot').forEach(function(img){{
    img.addEventListener('click', function(){{
      if (img.src) window.open(img.src, '_blank');
    }});
  }});
  var form = document.getElementById('runForm');
  if (form) form.addEventListener('submit', function(){{
    var st = document.getElementById('runState');
    var btn = document.getElementById('runBtn');
    if (st) st.style.display = 'block';
    if (btn) {{ btn.disabled = true; btn.textContent = '실행 중…'; }}
  }});
  /* recent runs + bundled samples are rendered server-side (no fetch). */
}})();
</script>
"""
    return page("Drawing-to-Parametric-CAD", body, lang="ko")


def form_page_en():
    status = ("present" if dotenv_key_present()
              else "absent (enter it in the key box, or make a .env file in the repo folder)")
    body = f"""
<form action="/run" method="post" enctype="multipart/form-data" id="runForm">
<input type="hidden" name="lang" value="en">
<div class="layout">
  <div class="sidebar">
    <h2>&#11042; Drawing&rarr;CAD</h2>
    <p class="note">English · <a href="/?lang=ko">한국어</a></p>
    <p class="sub">orchestrator v0.1 &middot; localhost only</p>
    <hr>
    <h3 style="font-size:14px;">&#128193; Open files</h3>
    <label for="drawing">Drawing image (PNG/JPG)</label>
    <input type="file" id="drawing" name="drawing" accept=".png,.jpg,.jpeg,.webp,.gif,.bmp" required>
    <div class="drop-hint">PDF is not supported yet. Convert a PDF drawing to an image (PNG/JPG) first.</div>
    <div class="drop-hint">Once you pick a file, a preview appears in this browser only, before sending.</div>
    <img id="drawingPreview" class="preview-live" alt="Drawing preview">
    <label for="outline">Outline attachment (optional, JSON/image)</label>
    <input type="file" id="outline" name="outline" accept=".json,.bin,.png,.jpg,.jpeg,image/*,.txt">
    <img id="outlinePreview" class="preview-live" alt="Outline preview">
    <p class="note">outline_snap_tool.html output JSON or an outline image. The original is kept in the output folder as input_outline.*.</p>
    <hr>
    <h3 style="font-size:14px;">&#129521; Run settings</h3>
    <label for="output_dir">Output folder</label>
    <input type="text" id="output_dir" name="output_dir" value="./my_run_output">
    <p class="note">With the default, a timestamped folder is made automatically (e.g. my_run_output_20261030_090411), so old results are never overwritten. If you name a folder that already holds a result, a timestamped sibling folder is used instead.</p>
    <label for="freecadcmd">freecadcmd</label>
    <input type="text" id="freecadcmd" name="freecadcmd" value="freecadcmd">
    <label><input type="checkbox" name="dry_run" value="on" style="width:auto;"> dry-run (assemble the prompt only)</label>
    <label><input type="checkbox" name="gear" value="on" style="width:auto;"> Gear part (gear reference included only when checked)</label>
    <label><input type="checkbox" name="ask_first" value="on" checked style="width:auto;"> Ask questions first (no model until you answer)</label>
    <label for="api_key">Meta API key</label>
    <input type="password" id="api_key" name="api_key" autocomplete="off">
    <p class="note">Key is not stored, used only for this run. Empty means use the repo folder .env key.</p>
    <p class="note">.env key: {html.escape(status)}</p>
    <button type="submit" id="runBtn" style="width:100%;margin-top:1em;">&#9654; Run</button>
    <div id="runState" class="drop-hint" style="display:none;">Running… takes minutes. Do not close the browser.</div>
    <p class="note">A real run takes minutes. Do not close the browser until it finishes.</p>
  </div>
  <div class="main">
    <h2 style="color:#7eb8f7;font-size:22px;margin:0;">Drawing &rarr; Parametric CAD</h2>
    <p class="note">The Meta API writes a FreeCAD macro, and freecadcmd builds <code>.fcstd</code> + <code>STEP</code> + a report.
    Pick a drawing on the left, check the tabs below, then press <code>▶ Run</code>.</p>
    <p><span class="feat-pill">Body&rarr;Sketch&rarr;Pad/Pocket</span><span class="feat-pill">.fcstd as main file</span><span class="feat-pill">STEP export</span></p>
    <div class="tabs">
      <button type="button" class="tab-btn active" data-tab="t1">&#128008; Drawing recognition</button>
      <button type="button" class="tab-btn" data-tab="t2">&#128207; Parameters &amp; 3D</button>
      <button type="button" class="tab-btn" data-tab="t3">&#128295; FreeCAD export</button>
      <button type="button" class="tab-btn" data-tab="t4">&#128269; QA log</button>
    </div>
    <div class="tab-panel active" id="t1">
      <div class="grid2">
        <div class="card"><h3>Original / input (check samples even before picking)</h3>
        <p class="note">Picking a file on the left also shows a browser preview here at the same time. Click to open full size in a new tab.</p>
        <img id="drawingPreviewMain" class="shot" style="display:none;" alt="Drawing preview"></div>
        <div class="card"><h3>Part notes</h3>
        <label for="notes">Part notes (optional)</label>
        <textarea id="notes" name="notes" placeholder="e.g. base D2.8, yoke width 4.8 ..."></textarea>
        <p class="note">Dimensions are never invented. When something is unclear, the run stops and leaves the questions in guidance.txt.</p></div>
      </div>
      {recent_html("en")}
    </div>
    <div class="tab-panel" id="t2">
      <div class="grid2">
        <div class="card"><h3>&#128207; Dimension parameters</h3>
        <p class="note">Check dimensions in the parameter block at the top of the macro. <span class="var-badge">INFERRED</span> values are LLM estimates, so in FreeCAD change a dimension and recompute to confirm a single valid solid.</p></div>
      <div class="card"><h3>&#129521; 3D preview</h3>
      <p class="note">After a run, check the same shape two ways:
      interactive 3D viewer (from tris.json, no CDN) + shaded images
      (preview_iso/main.png, Pillow fallback so they are always made).</p></div>
      </div>
    </div>
    <div class="tab-panel" id="t3">
      <div class="card"><h3>&#128295; FreeCAD export settings</h3>
      <p class="note">The sidebar output folder &middot; freecadcmd &middot; dry-run &middot; gear check are used as-is. On submit, the key and freecadcmd are checked first; the API is called only after they pass. The result's main file is <code>model.fcstd</code>, <code>model.step</code> is the export.</p>
      <button type="submit">&#9654; Run with these settings</button></div>
    </div>
    <div class="tab-panel" id="t4">
      <div class="card"><h3>&#128269; QA log</h3>
      <p class="note">Pass criteria: <code>solids == 1</code> and <code>valid == True</code> (independent STEP check). Volume and bbox are reference only. A macro log PASS alone is not a pass. Code/API errors are self-fixed at most 3 times; on the 3rd failure the run stops, leaving feature name, geometry number, exact error, cause, and questions.</p></div>
    </div>
  </div>
</div>
</form>
{picker_html("en")}
{sample_gallery_html("en")}
<script>
(function(){{
  function showFile(inputId, imgIds){{
    var input = document.getElementById(inputId);
    if (!input) return;
    input.addEventListener('change', function(){{
      var f = input.files && input.files[0];
      imgIds.forEach(function(id){{
        var img = document.getElementById(id);
        if (!img) return;
        if (!f || (f.type || '').indexOf('image/') !== 0) {{
          img.style.display = 'none';
          img.removeAttribute('src');
          return;
        }}
        if (img.dataset.url) URL.revokeObjectURL(img.dataset.url);
        var url = URL.createObjectURL(f);
        img.dataset.url = url;
        img.src = url;
        img.style.display = 'block';
      }});
    }});
  }}
  showFile('drawing', ['drawingPreview', 'drawingPreviewMain']);
  showFile('outline', ['outlinePreview']);
  document.querySelectorAll('.tab-btn').forEach(function(b){{
    b.addEventListener('click', function(){{
      document.querySelectorAll('.tab-btn').forEach(function(x){{x.classList.remove('active');}});
      document.querySelectorAll('.tab-panel').forEach(function(x){{x.classList.remove('active');}});
      b.classList.add('active');
      document.getElementById(b.dataset.tab).classList.add('active');
    }});
  }});
  document.querySelectorAll('img.shot').forEach(function(img){{
    img.addEventListener('click', function(){{
      if (img.src) window.open(img.src, '_blank');
    }});
  }});
  var form = document.getElementById('runForm');
  if (form) form.addEventListener('submit', function(){{
    var st = document.getElementById('runState');
    var btn = document.getElementById('runBtn');
    if (st) st.style.display = 'block';
    if (btn) {{ btn.disabled = true; btn.textContent = 'Running…'; }}
  }});
  /* recent runs + bundled samples are rendered server-side (no fetch). */
}})();
</script>
"""
    return page("Drawing-to-Parametric-CAD", body, lang="en")


def form_page(lang="en"):
    """English by default; Korean only with ?lang=ko."""
    return form_page_ko() if lang == "ko" else form_page_en()


def error_page(message, lang="en"):
    body = (f"<div class=\"layout\"><div class=\"sidebar\">"
            f"<h2>&#11042; Drawing&rarr;CAD</h2>"
            f"<p class=\"sub\">orchestrator v0.1</p><hr>"
            f"<p><a class=\"btn\" href=\"/?lang={lang}\">{tr(lang, 'error_back')}</a></p></div>"
            f"<div class=\"main\"><h2 style=\"color:#f87171;\">{tr(lang, 'error_heading')}</h2>"
            f"<div class=\"card\"><p>{html.escape(message)}</p></div></div></div>")
    return page(tr(lang, "error_heading"), body, lang=lang)


def parse_multipart(body, boundary):
    """Minimal multipart/form-data parser (stdlib only).

    Returns (fields, files): fields maps name -> str, or a list of
    str when a field name repeats (checkbox groups); files maps
    name -> (original_filename, bytes). Raises ValueError on bad input.
    """
    delimiter = b"--" + boundary
    fields = {}
    files = {}
    parts = body.split(delimiter)
    for part in parts[1:]:
        if part in (b"--\r\n", b"--", b"\r\n", b""):
            continue
        if part.startswith(b"--"):
            break
        if part.startswith(b"\r\n"):
            part = part[2:]
        header_blob, sep, content = part.partition(b"\r\n\r\n")
        if not sep:
            continue
        if content.endswith(b"\r\n"):
            content = content[:-2]
        headers = {}
        for line in header_blob.decode("utf-8", errors="replace").split("\r\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip().lower()] = value.strip()
        disp = headers.get("content-disposition", "")
        params = {}
        for item in disp.split(";"):
            item = item.strip()
            if "=" in item:
                k, v = item.split("=", 1)
                params[k.strip()] = v.strip().strip('"')
        name = params.get("name")
        if not name:
            continue
        filename = params.get("filename")
        if filename:
            files[name] = (filename, content)
        else:
            value = content.decode("utf-8", errors="replace")
            if name in fields:
                prev = fields[name]
                if isinstance(prev, list):
                    prev.append(value)
                else:
                    fields[name] = [prev, value]
            else:
                fields[name] = value
    return fields, files


def resolve_output_dir(raw):
    """Resolve the output folder relative to the server's cwd."""
    path = Path(raw.strip() or "./my_run_output")
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def resolve_run_output_dir(raw):
    """Timestamped sibling folder so a run never overwrites the last.

    Rules (Oct 30 home-run lesson: every run overwrote
    ./my_run_output, losing the previous model/report):
    - Default folder (./my_run_output) -> ./my_run_output_YYYYMMDD_HHMMSS
    - An explicit folder that already holds a previous result
      (report.txt or model.fcstd) -> <folder>_YYYYMMDD_HHMMSS
    - An explicit, empty/new folder -> used as-is.
    Sibling folders (not nested date subfolders) keep the recent-runs
    list working, since it scans the server cwd's top level.
    """
    path = resolve_output_dir(raw)
    default = resolve_output_dir("./my_run_output")
    needs_stamp = (path == default) or (
        path.is_dir()
        and ((path / "report.txt").is_file()
             or (path / "model.fcstd").is_file()))
    if needs_stamp:
        # Strip a previous _YYYYMMDD_HHMMSS suffix first: chained
        # /answer runs otherwise compound timestamps in the folder
        # name (my_run_output_..._..._...), risking Windows MAX_PATH.
        # If the stamped name already exists (two runs in the same
        # second), append _2, _3, ... so runs never share a folder.
        import re as _re
        base = _re.sub(r"_\d{8}_\d{6}$", "", path.name)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = path.with_name(f"{base}_{stamp}")
        _n = 2
        while (path.is_dir()
               and ((path / "report.txt").is_file()
                    or (path / "model.fcstd").is_file())):
            path = path.with_name(f"{base}_{stamp}_{_n}")
            _n += 1
    return path


def safe_download_path(output_dir, requested):
    """Return a path inside output_dir, or None if the request escapes it."""
    if not requested or ".." in Path(requested).parts:
        return None
    candidate = (output_dir / requested).resolve()
    try:
        candidate.relative_to(output_dir)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


def list_result_dirs(limit=12):
    """Recent output folders next to the server cwd (for 'view without rerun').

    Returns [{name, dir, ok|fail|unknown}] — newest report.txt first.
    Never exposes file contents or keys, only folder names + PASS/FAIL.
    """
    cands = []
    try:
        entries = list(Path.cwd().iterdir())
    except OSError:
        return []
    for path in entries:
        # Any unreadable entry must be skipped, never crash the form:
        # is_file()/stat() on a permission-denied folder raises OSError.
        try:
            if not path.is_dir():
                continue
            report = path / "report.txt"
            guidance = path / "guidance.txt"
            step = path / "model.step"
            fcstd = path / "model.fcstd"
            if not (report.is_file() or guidance.is_file()
                    or step.is_file() or fcstd.is_file()):
                continue
            status = "unknown"
            try:
                if report.is_file():
                    text = report.read_text(encoding="utf-8", errors="replace")
                    if "QUESTIONS PENDING" in text:
                        status = "questions"
                    elif ("RESULT: MODELING COMPLETE" in text
                          or "RESULT: PASS" in text):
                        status = "ok"
                    elif "RESULT: FAIL" in text:
                        status = "fail"
                elif guidance.is_file():
                    status = "fail"
            except OSError:
                pass
            try:
                mtime = (report.stat().st_mtime if report.is_file()
                         else path.stat().st_mtime)
            except OSError:
                mtime = 0
            cands.append({"name": path.name, "dir": str(path.resolve()),
                          "status": status, "mtime": mtime})
        except OSError:
            continue
    cands.sort(key=lambda c: c["mtime"], reverse=True)
    return cands[:limit]


def list_sample_images():
    """Bundle sample drawings (image/*.png|jpg) for one-click preview + run."""
    out = []
    try:
        if not SAMPLE_DIR.is_dir():
            return out
        for path in sorted(SAMPLE_DIR.iterdir()):
            if path.is_file() and path.suffix.lower() in (
                    ".png", ".jpg", ".jpeg", ".gif", ".webp"):
                out.append({"name": path.name})
    except OSError:
        pass
    return out


def tris_payload(output_dir):
    """Read tris.json inside output_dir, size-capped (8MB), or (None, err)."""
    tris = (output_dir / "tris.json")
    try:
        resolved = tris.resolve()
    except OSError as exc:
        return None, str(exc)
    try:
        resolved.relative_to(output_dir)
    except ValueError:
        return None, "scope"
    if not resolved.is_file():
        return None, "missing"
    try:
        if resolved.stat().st_size > MAX_TRIS_BYTES:
            return None, "too-large"
        data = json.loads(resolved.read_text(encoding="utf-8"))
        verts, facets = data.get("verts"), data.get("facets")
        if not isinstance(verts, list) or not isinstance(facets, list):
            return None, "bad-shape"
        return {"verts": verts, "facets": facets}, ""
    except Exception as exc:
        return None, str(exc)[:200]


def sample_gallery_html(lang="en"):
    """Clickable bundled sample drawings served via /sample?name=."""
    samples = list_sample_images()
    if not samples:
        return (f"<div class=\"card\"><h3>{tr(lang, 'sample_title')}</h3>"
                f"<p class=\"note\">{tr(lang, 'sample_empty')}</p></div>")
    cards = []
    for item in samples:
        name = item["name"]
        query = urllib.parse.urlencode({"name": name})
        cards.append(
            f"<div class=\"card\"><h3>{html.escape(name)}</h3>"
            f"<img class=\"shot\" src=\"/sample?{query}\" alt=\"{html.escape(name)}\">"
            f"<p class=\"note\"><a href=\"/sample?{query}\" target=\"_blank\">{tr(lang, 'sample_original')}</a> · "
            f"{tr(lang, 'sample_use_note')}</p></div>")
    return (f"<div class=\"card\"><h3>{tr(lang, 'sample_title')}</h3>"
            f"<p class=\"note\">{tr(lang, 'sample_note')}</p></div>"
            "<div class=\"grid2\">" + "".join(cards) + "</div>")


def recent_html(lang="en"):
    """Recent runs table (server-side, no JS fetch needed) + JS fallback box."""
    rows = ""
    for item in list_result_dirs():
        badge = ({"ok": "<span class=\"status-ok\">PASS</span>",
                  "fail": "<span class=\"status-err\">FAIL</span>",
                  "questions": "<span class=\"status-warn\">QUESTIONS</span>"}.get(
                      item["status"], "<span class=\"status-warn\">?</span>"))
        query = urllib.parse.urlencode({"dir": item["dir"], "lang": lang})
        rows += (f"<tr><td>{html.escape(item['name'])}</td><td>{badge}</td>"
                 f"<td><a href=\"/result?{query}\">{tr(lang, 'open_link')}</a></td></tr>")
    if rows:
        table = (f"<table class=\"files\"><tr><th>{tr(lang, 'th_folder')}</th>"
                 f"<th>{tr(lang, 'th_status')}</th>"
                 f"<th>{tr(lang, 'th_open')}</th></tr>{rows}</table>")
    else:
        table = f"<p class=\"note\">{tr(lang, 'recent_empty')}</p>"
    outline_link = ""
    try:
        if OUTLINE_TOOL_PATH.is_file():
            outline_link = (f"<p class=\"note\">{tr(lang, 'outline_note1')}"
                            "<a href=\"/outline-tool\" target=\"_blank\">"
                            "outline snap tool</a>"
                            f"{tr(lang, 'outline_note2')}</p>")
    except OSError:
        pass
    return (f"<div class=\"card\"><h3>&#128193; {tr(lang, 'recent_title')}</h3>"
            f"<p class=\"note\">{tr(lang, 'recent_note')}</p>"
            f"{table}{outline_link}"
            "<div id=\"recentBox\" class=\"note\" style=\"display:none;\"></div></div>")


def picker_html(lang="en"):
    """Continue-from-a-folder picker card (rerun form + path box).

    MUST be rendered outside the main /run <form>: nested <form>
    tags are invalid HTML, browsers drop the inner tags, and the
    Rerun button then submits the outer /run form — whose required
    drawing field blocks it and grabs focus (reported Oct 30, 2026).
    form_page_en/ko render this after </form>."""
    pick_options = ""
    for item in list_result_dirs(limit=50):
        pick_options += (
            f"<option value=\"{html.escape(item['dir'], quote=True)}\">"
            f"{html.escape(item['name'])} [{item['status']}]</option>")
    picker = ""
    if pick_options:
        # Rerun form: POST /answer with rerun=1 reuses the picked
        # folder's saved drawing/outline/Q&A history — no drawing
        # upload needed. The path box below still only opens a
        # folder (GET /result) for viewing.
        picker = (
            f"<form action=\"/answer\" method=\"post\" "
            f"enctype=\"multipart/form-data\">"
            f"<input type=\"hidden\" name=\"lang\" value=\"{lang}\">"
            f"<input type=\"hidden\" name=\"rerun\" value=\"1\">"
            f"<label>{tr(lang, 'continue_folder_title')}</label>"
            f"<select name=\"dir\">{pick_options}</select>"
            f"<label for=\"freecadcmd_rerun\">freecadcmd</label>"
            f"<input type=\"text\" id=\"freecadcmd_rerun\" name=\"freecadcmd\" "
            f"value=\"freecadcmd\">"
            f"<label><input type=\"checkbox\" name=\"dry_run\" value=\"on\" "
            f"style=\"width:auto;\"> {tr(lang, 'dry_label')}</label>"
            f"<label for=\"api_key_rerun\">Meta API key</label>"
            f"<input type=\"password\" id=\"api_key_rerun\" name=\"api_key\" "
            f"autocomplete=\"off\">"
            f"<p class=\"note\">{tr(lang, 'key_note')}</p>"
            f"<button type=\"submit\">{tr(lang, 'continue_folder_pick')}</button>"
            f"</form>")
    picker += (
        f"<form action=\"/result\" method=\"get\">"
        f"<input type=\"hidden\" name=\"lang\" value=\"{lang}\">"
        f"<label>{tr(lang, 'continue_folder_path')}</label>"
        f"<input type=\"text\" name=\"dir\" required "
        f"placeholder=\"E:\\drawing_to_parametric_cad_orchestrator\\my_run_output_20261030_...\">"
        f"<button type=\"submit\">{tr(lang, 'continue_folder_open')}</button>"
        f"</form>")
    return (f"<div class=\"card\"><h3>&#128193; {tr(lang, 'continue_folder_title')}</h3>"
            f"<p class=\"note\">{tr(lang, 'continue_folder_note')}</p>"
            f"{picker}</div>")


def viewer_html(output_dir, lang="en"):
    """Interactive canvas viewer block (viewer3d.js + /tris data)."""
    query = urllib.parse.urlencode({"dir": str(output_dir)})
    tris, err = tris_payload(output_dir)
    if tris is None:
        why = {"missing": tr(lang, "viewer_missing"),
               "too-large": tr(lang, "viewer_toolarge"),
               "scope": tr(lang, "viewer_scope"),
               "bad-shape": tr(lang, "viewer_badshape")}.get(err, html.escape(err))
        return (f"<div class=\"card\"><h3>&#129521; {tr(lang, 'viewer_title')}</h3>"
                f"<p class=\"note\">{tr(lang, 'viewer_none', why=why)}</p></div>")
    js_query = urllib.parse.urlencode({"v": str(VIEWER_JS_PATH.stat().st_mtime)}) \
        if VIEWER_JS_PATH.is_file() else "v=1"
    return f"""
      <div class="card"><h3>&#129521; {tr(lang, 'viewer_title')}</h3>
      <p class="note">{tr(lang, 'viewer_note', n=len(tris['facets']))}</p>
      <div class="viewer-wrap"><canvas id="viewer3d" width="900" height="420"></canvas>
      <div class="viewer-bar" id="viewerBar">{tr(lang, 'viewer_loading')}</div></div>
      <div class="viewer-tools">
        <button type="button" data-view="iso">{tr(lang, 'view_iso')}</button>
        <button type="button" data-view="main">{tr(lang, 'view_main')}</button>
        <button type="button" data-view="top">{tr(lang, 'view_top')}</button>
        <button type="button" data-view="side">{tr(lang, 'view_side')}</button>
      </div>
      <div class="kv" id="viewerMeta"></div></div>
      <script>window.TRIS_URL='/tris?{query}';</script>
      <script src="/viewer3d.js?{js_query}"></script>"""


def _xml_escape(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def build_xlsx(headers, rows_values):
    """Build a minimal .xlsx workbook (stdlib only: zipfile + XML).

    No openpyxl dependency: the web UI must run on a plain Python.
    Cells use inline strings (no sharedStrings table); numbers stay
    numeric so the sheet can compute on them. Returns bytes.
    """
    import io
    import zipfile

    def col_letter(i):
        s = ""
        i += 1
        while i:
            i, r = divmod(i - 1, 26)
            s = chr(65 + r) + s
        return s

    widths = [8, 42, 14, 14, 14, 16]
    cols_xml = "".join(
        f"<col min=\"{i + 1}\" max=\"{i + 1}\" width=\"{widths[i] if i < len(widths) else 14}\" customWidth=\"1\"/>"
        for i in range(len(headers)))
    sheet_rows = []
    header_cells = "".join(
        f"<c r=\"{col_letter(i)}1\" s=\"1\" t=\"inlineStr\"><is><t>"
        f"{_xml_escape(h)}</t></is></c>"
        for i, h in enumerate(headers))
    sheet_rows.append(f"<row r=\"1\">{header_cells}</row>")
    for ri, row in enumerate(rows_values, start=2):
        cells = []
        for ci, v in enumerate(row):
            ref = f"{col_letter(ci)}{ri}"
            if v is None or v == "":
                cells.append(f"<c r=\"{ref}\"/>")
            elif isinstance(v, bool):
                cells.append(f"<c r=\"{ref}\" t=\"b\"><v>"
                             f"{1 if v else 0}</v></c>")
            elif isinstance(v, (int, float)):
                cells.append(f"<c r=\"{ref}\"><v>{v!r}</v></c>")
            else:
                cells.append(f"<c r=\"{ref}\" t=\"inlineStr\"><is><t>"
                             f"{_xml_escape(v)}</t></is></c>")
        sheet_rows.append(f"<row r=\"{ri}\">{''.join(cells)}</row>")
    sheet_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
        "<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\">"
        f"<cols>{cols_xml}</cols><sheetData>{''.join(sheet_rows)}</sheetData>"
        "</worksheet>")
    workbook_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
        "<workbook xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\" "
        "xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\">"
        "<sheets><sheet name=\"Matching\" sheetId=\"1\" r:id=\"rId1\"/></sheets>"
        "</workbook>")
    content_types = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
        "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">"
        "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>"
        "<Default Extension=\"xml\" ContentType=\"application/xml\"/>"
        "<Override PartName=\"/xl/workbook.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml\"/>"
        "<Override PartName=\"/xl/worksheets/sheet1.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml\"/>"
        "<Override PartName=\"/xl/styles.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml\"/>"
        "</Types>")
    rels = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
        "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"xl/workbook.xml\"/>"
        "</Relationships>")
    workbook_rels = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
        "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" Target=\"worksheets/sheet1.xml\"/>"
        "<Relationship Id=\"rId2\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles\" Target=\"styles.xml\"/>"
        "</Relationships>")
    styles = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
        "<styleSheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\">"
        "<fonts><font><sz val=\"11\"/><name val=\"Calibri\"/></font>"
        "<font><b/><sz val=\"11\"/><name val=\"Calibri\"/></font></fonts>"
        "<fills><fill><patternFill patternType=\"none\"/></fill></fills>"
        "<borders><border/></borders>"
        "<cellStyleXfs><xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" borderId=\"0\"/></cellStyleXfs>"
        "<cellXfs><xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" borderId=\"0\" xfId=\"0\"/>"
        "<xf numFmtId=\"0\" fontId=\"1\" fillId=\"0\" borderId=\"0\" xfId=\"0\" applyFont=\"1\"/></cellXfs>"
        "<cellStyles><cellStyle name=\"Normal\" xfId=\"0\" builtinId=\"0\"/></cellStyles>"
        "</styleSheet>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        zf.writestr("xl/styles.xml", styles)
    return buf.getvalue()


def result_page(output_dir, returncode, stdout_tail="", lang="en"):
    # Dashboard-style result (mp3d Tab 1/2/3/4 look): status banner +
    # tabbed cards for input images, 3D previews, files/downloads, QA logs.
    if returncode == 0:
        banner = f"<span class=\"status-ok\">{tr(lang, 'success')}</span>"
    else:
        banner = (f"<span class=\"status-err\">"
                  f"{tr(lang, 'failure', code=html.escape(str(returncode)))}</span>")
    report_text = ""
    report = output_dir / "report.txt"
    if report.is_file():
        report_text = report.read_text(encoding="utf-8", errors="replace")
    guidance_text = ""
    guidance = output_dir / "guidance.txt"
    if guidance.is_file():
        guidance_text = guidance.read_text(encoding="utf-8", errors="replace")
    questions_text = ""
    questions_file = output_dir / "questions.txt"
    if questions_file.is_file():
        questions_text = questions_file.read_text(encoding="utf-8",
                                                  errors="replace")
    # Questions exist: this is NOT a success, even though exit 0
    # and a valid solid exist. The banner says QUESTIONS, keyed off
    # questions.txt itself (not the report RESULT line), so reopening
    # an older result folder shows the same banner.
    if questions_text.strip():
        banner = (f"<span class=\"status-warn\">{tr(lang, 'questions_pending')}</span>")
    elif "ASK-FIRST" in report_text and not (output_dir / "model.fcstd").is_file():
        # Ask-first step with no questions: not a success either,
        # just ready to build. No model exists yet.
        banner = (f"<span class=\"status-warn\">{tr(lang, 'askfirst_banner')}</span>")
    elif returncode == 0 and "provisional" in report_text:
        # Old results (pre-QUESTIONS-PENDING) with a provisional PASS.
        banner = (f"<span class=\"status-warn\">{tr(lang, 'questions_pending')}</span>")

    # Continue form (ALWAYS shown): POST /answer reuses the previous
    # run's drawing/outline and starts a NEW run with the answers as
    # --text. It is not a resume of the old macro. Showing it only when
    # questions/guidance exist left completed folders with no way to
    # continue from them (Oct 30: user asked for folder-pick continue).
    # With questions/guidance it is the answer form; otherwise it is a
    # plain "continue this project with new instructions" form.
    import re as _re
    labels = _re.findall(r"(Q\d+)\s*:", questions_text)
    seen = []
    for label in labels:
        if label not in seen:
            seen.append(label)
    prefill = "\n".join(f"{label}: " for label in seen)
    gear_checked = ("checked" if "Gear reference: included"
                    in report_text else "")
    dir_query = html.escape(str(output_dir), quote=True)
    askfirst_note = ""
    if not (output_dir / "model.fcstd").is_file():
        askfirst_note = (f"<p class=\"note\">{tr(lang, 'answer_askfirst_note')}</p>")
    if questions_text.strip() or guidance_text.strip():
        _form_title = tr(lang, 'answer_title')
        _form_note = tr(lang, 'answer_note')
        _form_label = tr(lang, 'answer_label')
    else:
        _form_title = tr(lang, 'continue_title')
        _form_note = tr(lang, 'continue_note')
        _form_label = tr(lang, 'continue_label')
    answer_form = f"""
      <div class="card"><h3>{_form_title}</h3>
      <p class="note">{_form_note}</p>
      {askfirst_note}
      <form action="/answer" method="post" enctype="multipart/form-data">
      <input type="hidden" name="dir" value="{dir_query}">
      <input type="hidden" name="lang" value="{lang}">
      <label for="answers">{_form_label}</label>
      <textarea id="answers" name="answers" rows="10">{html.escape(prefill)}</textarea>
      <label for="freecadcmd_answer">freecadcmd</label>
      <input type="text" id="freecadcmd_answer" name="freecadcmd" value="freecadcmd">
      <label><input type="checkbox" name="gear" value="on" {gear_checked} style="width:auto;"> {tr(lang, 'gear_label')}</label>
      <label><input type="checkbox" name="dry_run" value="on" style="width:auto;"> {tr(lang, 'dry_label')}</label>
      <label for="api_key_answer">Meta API key</label>
      <input type="password" id="api_key_answer" name="api_key" autocomplete="off">
      <p class="note">{tr(lang, 'key_note')}</p>
      <button type="submit">{tr(lang, 'continue_button')}</button>
      <p class="note">{tr(lang, 'continue_button_note')}</p>
      </form></div>"""

    def view_link(name):
        query = urllib.parse.urlencode({"dir": str(output_dir), "file": name})
        return f"/view?{query}"
    image_files = []
    if output_dir.is_dir():
        for path in sorted(output_dir.iterdir()):
            if path.is_file() and path.suffix.lower() in (
                    ".png", ".jpg", ".jpeg", ".gif", ".webp"):
                image_files.append(path.name)
    input_images = [n for n in image_files
                    if n.startswith("input_drawing") or n.startswith("input_outline")]
    previews = [n for n in image_files if n.startswith("preview_")]

    # Pill summary from report.txt (verification line, if present).
    pills = ""
    for line in report_text.splitlines():
        if line.startswith("Verification:"):
            pills += (f"<span class=\"feat-pill\">"
                      f"{html.escape(line.strip())}</span>")
            break
    if returncode == 0:
        pills += f"<span class=\"feat-pill\">{tr(lang, 'pill_fcstd')}</span>"
    if previews:
        pills += (f"<span class=\"feat-pill\">"
                  f"{tr(lang, 'pill_previews', n=len(previews))}</span>")

    def img_card(name, caption):
        return (f"<div class=\"card\"><h3>{html.escape(name)}</h3>"
                f"<p class=\"note\">{caption}{tr(lang, 'click_full')}</p>"
                f"<img class=\"shot\" src=\"{view_link(name)}\" "
                f"alt=\"{html.escape(name)}\"></div>")

    if input_images:
        t1_cards = "".join(
            img_card(n, tr(lang, "input_caption"))
            for n in input_images)
    else:
        t1_cards = (f"<div class=\"card\"><p class=\"note\">"
                    f"{tr(lang, 'input_none')}</p></div>")
    if previews:
        t2_cards = "".join(
            img_card(n, tr(lang, "preview_caption"))
            for n in previews)
    else:
        t2_cards = (f"<div class=\"card\"><p class=\"note\">"
                    f"{tr(lang, 'preview_none')}</p></div>")
    t2_viewer = viewer_html(output_dir, lang)

    # Matching tab: numbered drawing + drawing/modeling/O-X table.
    matching_rows = []
    matching_path = output_dir / "matching.json"
    if matching_path.is_file():
        try:
            matching_rows = json.loads(matching_path.read_text(
                encoding="utf-8"))
        except Exception:
            matching_rows = []
    matching_table = ""
    # The measured column appears only after a measurement run
    # (a row with a non-None measured value); older results render
    # exactly as before.
    show_measured = any(row.get("measured") is not None
                        for row in matching_rows)
    if matching_rows:
        tr_rows = ""
        for ri, row in enumerate(matching_rows):
            res = row.get("result", "-")
            cls = {"O": "status-ok", "X": "status-err"}.get(
                res, "status-warn")
            def _fmt(v):
                if v is None:
                    return "—"
                if isinstance(v, bool):
                    return "True" if v else "False"
                if isinstance(v, float):
                    return f"{v:.2f}"
                return html.escape(str(v))
            measured_cell = ""
            if show_measured:
                mval = row.get("measured")
                method = row.get("measured_method") or ""
                if mval is None:
                    measured_cell = "<td>—</td>"
                else:
                    measured_cell = (
                        f"<td title=\"{html.escape(str(method))}\">"
                        f"{_fmt(mval)}</td>")
            tr_rows += (
                f"<tr><td><input type=\"checkbox\" class=\"rowcheck\" "
                f"name=\"rows\" value=\"{ri}\" checked></td>"
                f"<td>{html.escape(str(row.get('no', '—')))}</td>"
                f"<td>{html.escape(str(row.get('item', '')))}</td>"
                f"<td>{_fmt(row.get('drawing'))}</td>"
                f"<td>{_fmt(row.get('modeling'))}</td>"
                f"{measured_cell}"
                f"<td><span class=\"{cls}\">{html.escape(str(res))}</span></td></tr>")
        measured_th = (f"<th>{tr(lang, 'th_measured')}</th>"
                       if show_measured else "")
        matching_table = (
            f"<table class=\"files\"><tr><th>{tr(lang, 'th_select')}</th>"
            f"<th>{tr(lang, 'th_no')}</th>"
            f"<th>{tr(lang, 'th_item')}</th><th>{tr(lang, 'th_drawing')}</th>"
            f"<th>{tr(lang, 'th_modeling')}</th>{measured_th}"
            f"<th>{tr(lang, 'th_result')}</th></tr>"
            f"{tr_rows}</table>")
    else:
        matching_table = f"<p class=\"note\">{tr(lang, 'matching_none')}</p>"
    numbered_img = ""
    numbered_path = output_dir / "drawing_numbered.png"
    if numbered_path.is_file():
        numbered_img = (
            f"<div class=\"card\"><h3>{tr(lang, 'matching_title')}</h3>"
            f"<p class=\"note\">{tr(lang, 'matching_numbered_note')}</p>"
            f"<img class=\"shot\" src=\"{view_link('drawing_numbered.png')}\" "
            f"alt=\"numbered drawing\"></div>")
    else:
        numbered_img = (
            f"<div class=\"card\"><p class=\"note\">"
            f"{tr(lang, 'matching_no_numbered')}</p></div>")

    # Table-export form: wraps the table (checkboxes live inside
    # it) and saves only the checked rows as CSV or .xlsx.
    # Sibling of the measure form below, never nested in it:
    # nested <form> tags are invalid HTML and browsers drop the
    # inner form (the Oct 30 rerun bug).
    export_open = ""
    export_close = ""
    if matching_rows:
        export_open = (
            f"<form action=\"/export\" method=\"post\" "
            f"enctype=\"multipart/form-data\">"
            f"<input type=\"hidden\" name=\"dir\" value=\"{html.escape(str(output_dir))}\">"
            f"<input type=\"hidden\" name=\"lang\" value=\"{lang}\">")
        export_close = (
            f"<p class=\"note\">{tr(lang, 'export_note')}</p>"
            f"<p><label>{tr(lang, 'export_format')} "
            f"<select name=\"format\">"
            f"<option value=\"csv\">{tr(lang, 'fmt_csv')}</option>"
            f"<option value=\"xlsx\">{tr(lang, 'fmt_xlsx')}</option>"
            f"</select></label> "
            f"<button type=\"button\" onclick=\"document.querySelectorAll"
            f"('.rowcheck').forEach(c=>c.checked=true);return false;\">"
            f"{tr(lang, 'select_all')}</button> "
            f"<button type=\"button\" onclick=\"document.querySelectorAll"
            f"('.rowcheck').forEach(c=>c.checked=false);return false;\">"
            f"{tr(lang, 'deselect_all')}</button> "
            f"<button class=\"btn\" type=\"submit\">"
            f"{tr(lang, 'save_table')}</button></p></form>")

    # Real-measurement (실측) form: runs measure_step.py on this
    # folder's model.step and adds a Measured column to the table.
    # No API call, no rebuild. Only shown when a STEP exists.
    measure_block = ""
    step_path = output_dir / "model.step"
    if step_path.is_file():
        done_note = ""
        measurements_path = output_dir / "measurements.json"
        if measurements_path.is_file():
            try:
                _m = json.loads(measurements_path.read_text(
                    encoding="utf-8"))
                _at = _m.get("measured_at", "")
                done_note = (f"<p class=\"note\">{tr(lang, 'measure_done')}"
                             f"{' (' + _at + ')' if _at else ''}</p>")
            except Exception:
                done_note = f"<p class=\"note\">{tr(lang, 'measure_done')}</p>"
        measure_block = (
            f"<form action=\"/measure\" method=\"post\" "
            f"enctype=\"multipart/form-data\">"
            f"<input type=\"hidden\" name=\"dir\" value=\"{html.escape(str(output_dir))}\">"
            f"<input type=\"hidden\" name=\"lang\" value=\"{lang}\">"
            f"<label>freecadcmd <input type=\"text\" name=\"freecadcmd\" "
            f"value=\"freecadcmd\"></label> "
            f"<button class=\"btn\" type=\"submit\">"
            f"{tr(lang, 'measure_btn')}</button></form>"
            f"<p class=\"note\">{tr(lang, 'measure_note')}</p>"
            f"{done_note}")

    file_rows = ""
    if output_dir.is_dir():
        for path in sorted(output_dir.iterdir()):
            if path.is_file():
                query = urllib.parse.urlencode(
                    {"dir": str(output_dir), "file": path.name}
                )
                file_rows += (
                    f"<tr><td>{html.escape(path.name)}</td>"
                    f"<td>{path.stat().st_size}</td>"
                    f"<td><a href=\"/download?{query}\">{tr(lang, 'download')}</a> · "
                    f"<a href=\"/view?{query}\">{tr(lang, 'view_link')}</a></td></tr>"
                )
    lang_query = urllib.parse.urlencode({"dir": str(output_dir), "lang": "en"})
    lang_query_ko = urllib.parse.urlencode({"dir": str(output_dir), "lang": "ko"})
    body = f"""
<div class="layout">
  <div class="sidebar">
    <h2>&#11042; Drawing&rarr;CAD</h2>
    <p class="sub">orchestrator v0.1 &middot; {tr(lang, 'result_sidebar')}</p>
    <hr>
    <div class="card"><h3 style="font-size:14px;">{tr(lang, 'result_sidebar')}</h3><p>{banner}</p>
    <p class="note">{tr(lang, 'output_folder')}<br><code>{html.escape(str(output_dir))}</code></p>
    <p><a class="btn" href="/?lang={lang}">{tr(lang, 'back_form')}</a></p>
    <p class="note"><a href="/result?{lang_query}">English</a> · <a href="/result?{lang_query_ko}">한국어</a></p></div>
  </div>
  <div class="main">
    <h2 style="color:#7eb8f7;font-size:22px;margin:0;">{tr(lang, 'result_heading')}</h2>
    <p>{banner}</p>
    <p>{pills}</p>
    <div class="tabs">
      <button type="button" class="tab-btn active" data-tab="r1">&#128008; {tr(lang, 'tab_drawing')}</button>
      <button type="button" class="tab-btn" data-tab="r2">&#129521; {tr(lang, 'tab_params')}</button>
      <button type="button" class="tab-btn" data-tab="r3">&#128295; {tr(lang, 'tab_export')}</button>
      <button type="button" class="tab-btn" data-tab="r4">&#128269; {tr(lang, 'tab_qa')}</button>
      <button type="button" class="tab-btn" data-tab="r5">&#10003; {tr(lang, 'tab_matching')}</button>
    </div>
    <div class="tab-panel active" id="r1">
      <div class="card"><h3>🖼 {tr(lang, 'input_title')}</h3>
      <p class="note">{tr(lang, 'input_note')}</p></div>
      <div class="grid2">{t1_cards}</div>
    </div>
    <div class="tab-panel" id="r2">
      {t2_viewer}
      <div class="grid2">{t2_cards}</div>
    </div>
    <div class="tab-panel" id="r3">
      <div class="card"><h3>🔧 {tr(lang, 'files_title')}</h3>
      <table class="files"><tr><th>{tr(lang, 'th_file')}</th><th>{tr(lang, 'th_bytes')}</th><th>{tr(lang, 'th_link')}</th></tr>{file_rows}</table></div>
    </div>
    <div class="tab-panel" id="r5">
      {numbered_img}
      <div class="card"><h3>&#10003; {tr(lang, 'matching_title')}</h3>
      <p class="note">{tr(lang, 'matching_note')}</p>
      {export_open}{matching_table}{export_close}
      {measure_block}
      <p class="note">{tr(lang, 'matching_legend')}</p>
      <p class="note">{tr(lang, 'matching_disclaimer')}</p></div>
    </div>
    <div class="tab-panel" id="r4">
      <div class="card"><h3>❓ {tr(lang, 'questions_title')}</h3><pre>{html.escape(questions_text) if questions_text else tr(lang, 'questions_none')}</pre><p class="note">{tr(lang, 'questions_note')}</p></div>
      {answer_form}
      <div class="grid2">
        <div class="card"><h3>{tr(lang, 'report_title')}</h3><pre>{html.escape(report_text) if report_text else tr(lang, 'report_none')}</pre></div>
        <div class="card"><h3>{tr(lang, 'guidance_title')}</h3><pre>{html.escape(guidance_text) if guidance_text else tr(lang, 'guidance_none')}</pre></div>
      </div>
      <div class="card"><h3>{tr(lang, 'log_title')}</h3><pre>{html.escape(stdout_tail) if stdout_tail else tr(lang, 'log_none')}</pre></div>
    </div>
  </div>
</div>
<script>
(function(){{
  document.querySelectorAll('.tab-btn').forEach(function(b){{
    b.addEventListener('click', function(){{
      document.querySelectorAll('.tab-btn').forEach(function(x){{x.classList.remove('active');}});
      document.querySelectorAll('.tab-panel').forEach(function(x){{x.classList.remove('active');}});
      b.classList.add('active');
      document.getElementById(b.dataset.tab).classList.add('active');
    }});
  }});
  document.querySelectorAll('img.shot').forEach(function(img){{
    img.addEventListener('click', function(){{
      if (img.src) window.open(img.src, '_blank');
    }});
  }});
}})();
</script>
"""
    return page(tr(lang, "result_heading"), body, lang=lang)


class Handler(BaseHTTPRequestHandler):
    # Never log request bodies or query values that could carry secrets.
    # The form sends the key only in the POST body, which is never logged.
    def log_message(self, fmt, *args):
        sys.stderr.write(f"{self.address_string()} {fmt % args}\n")

    def _send_bytes(self, data, mime):
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            lang = pick_lang(urllib.parse.parse_qs(parsed.query).get("lang", [""])[0])
            data = form_page(lang)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if parsed.path == "/result":
            # Reopen a previous output folder without rerunning.
            # ?dir=<absolute path> only; resolved and must hold a report.
            query = urllib.parse.parse_qs(parsed.query)
            raw_dir = query.get("dir", [""])[0]
            lang = pick_lang(query.get("lang", [""])[0])
            # Tell the user WHY it cannot open (Oct 30: a bare
            # "Cannot open the result folder" hid an empty path
            # submission and a not-yet-existing new folder).
            if not raw_dir:
                self._send_html(400, error_page(tr(lang, "err_result_empty"), lang=lang))
                return
            output_dir = Path(raw_dir).resolve()
            if not output_dir.is_dir():
                self._send_html(400, error_page(tr(lang, "err_result_missing"), lang=lang))
                return
            if not ((output_dir / "report.txt").is_file()
                    or (output_dir / "guidance.txt").is_file()
                    or (output_dir / "model.step").is_file()):
                self._send_html(400, error_page(tr(lang, "err_result_nofiles"), lang=lang))
                return
            # Banner keys off questions.txt, so reopened results show
            # QUESTIONS even when the stored report says PASS.
            data = result_page(output_dir,
                               0 if (output_dir / "report.txt").is_file() else 1,
                               lang=lang)
            self._send_html(200, data)
            return
        if parsed.path == "/tris":
            # 3D viewer data: tris.json inside the output dir only, capped.
            query = urllib.parse.parse_qs(parsed.query)
            raw_dir = query.get("dir", [""])[0]
            output_dir = Path(raw_dir).resolve() if raw_dir else None
            if output_dir is None:
                self.send_error(400, "Bad dir")
                return
            payload, err = tris_payload(output_dir)
            if payload is None:
                self.send_error(404, f"tris unavailable: {err}")
                return
            data = json.dumps(payload).encode("utf-8")
            self._send_bytes(data, "application/json")
            return
        if parsed.path == "/sample":
            # Bundled sample drawings from image/ (read-only).
            query = urllib.parse.parse_qs(parsed.query)
            name = query.get("name", [""])[0]
            if not name or ".." in Path(name).parts or "/" in name or "\\" in name:
                self.send_error(400, "Bad name")
                return
            target = (SAMPLE_DIR / name).resolve()
            try:
                target.relative_to(SAMPLE_DIR.resolve())
            except ValueError:
                self.send_error(400, "Bad name")
                return
            if not target.is_file():
                self.send_error(404, "Not found")
                return
            mime, _enc = mimetypes.guess_type(str(target))
            if not (mime or "").startswith("image/"):
                self.send_error(400, "Not an image")
                return
            self._send_bytes(target.read_bytes(), mime)
            return
        if parsed.path == "/viewer3d.js":
            if not VIEWER_JS_PATH.is_file():
                self.send_error(404, "Not found")
                return
            self._send_bytes(VIEWER_JS_PATH.read_bytes(),
                             "application/javascript")
            return
        if parsed.path == "/outline-tool":
            # Serve the bundled snap tool (same-origin, opens in new tab).
            if not OUTLINE_TOOL_PATH.is_file():
                self.send_error(404, "Not found")
                return
            self._send_bytes(OUTLINE_TOOL_PATH.read_bytes(),
                             "text/html; charset=utf-8")
            return
        if parsed.path == "/view":
            # Inline image view (no attachment header), same safe-path
            # guard as /download, images only.
            query = urllib.parse.parse_qs(parsed.query)
            raw_dir = query.get("dir", [""])[0]
            raw_file = query.get("file", [""])[0]
            output_dir = Path(raw_dir).resolve() if raw_dir else None
            target = safe_download_path(output_dir, raw_file) if output_dir else None
            mime, _enc = mimetypes.guess_type(str(target)) if target else (None, None)
            if target is None or not (mime or "").startswith("image/"):
                lang = pick_lang(query.get("lang", [""])[0])
                data = error_page(tr(lang, "err_view_file"), lang=lang)
                self.send_response(400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if parsed.path == "/download":
            query = urllib.parse.parse_qs(parsed.query)
            raw_dir = query.get("dir", [""])[0]
            raw_file = query.get("file", [""])[0]
            output_dir = Path(raw_dir).resolve() if raw_dir else None
            target = safe_download_path(output_dir, raw_file) if output_dir else None
            if target is None:
                lang = pick_lang(query.get("lang", [""])[0])
                data = error_page(tr(lang, "err_download_path"), lang=lang)
                self.send_response(400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            mime, _enc = mimetypes.guess_type(str(target))
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime or "application/octet-stream")
            self.send_header(
                "Content-Disposition", f'attachment; filename="{target.name}"'
            )
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_error(404, "Not found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path not in ("/run", "/answer", "/measure", "/export"):
            self.send_error(404, "Not found")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        body = self.rfile.read(length) if length > 0 else b""
        content_type = self.headers.get("Content-Type", "")
        lang = "en"
        if "multipart/form-data" not in content_type or "boundary=" not in content_type:
            data = error_page(tr(lang, "err_form"), lang=lang)
            self._send_html(400, data)
            return
        boundary = content_type.split("boundary=", 1)[1].strip().strip('"').encode("ascii")
        try:
            fields, files = parse_multipart(body, boundary)
        except Exception:
            data = error_page(tr(lang, "err_parse"), lang=lang)
            self._send_html(400, data)
            return

        lang = pick_lang(fields.get("lang", ""))
        if parsed.path == "/measure":
            # Real measurement: no API call, no rebuild. Runs
            # run_pipeline.py --measure on the folder's model.step,
            # then shows the result page with the Measured column.
            raw_dir = fields.get("dir", "")
            try:
                output_dir = Path(raw_dir).resolve()
            except OSError:
                output_dir = None
            if output_dir is None or not output_dir.is_dir():
                data = error_page(tr(lang, "err_prev_dir"), lang=lang)
                self._send_html(400, data)
                return
            if not (output_dir / "model.step").is_file():
                data = error_page(tr(lang, "err_measure_nostep"), lang=lang)
                self._send_html(400, data)
                return
            freecadcmd_value = (fields.get("freecadcmd", "freecadcmd")
                                or "freecadcmd")
            if not freecadcmd_found(freecadcmd_value):
                data = error_page(tr(lang, "err_freecadcmd"), lang=lang)
                self._send_html(400, data)
                return
            command = [sys.executable, str(RUN_PIPELINE), "--measure",
                       "--output-dir", str(output_dir),
                       "--freecadcmd", freecadcmd_value]
            log_path = output_dir / "web_ui_measure.log"
            with open(log_path, "w", encoding="utf-8") as log_file:
                result = subprocess.run(
                    command, stdout=log_file, stderr=subprocess.STDOUT,
                    timeout=3600)
            if result.returncode != 0:
                data = error_page(tr(lang, "err_measure_failed"), lang=lang)
                self._send_html(400, data)
                return
            data = result_page(output_dir, 0, lang=lang)
            self._send_html(200, data)
            return
        if parsed.path == "/export":
            # Save only the checked matching-table rows as CSV or
            # .xlsx. CSV is UTF-8 with BOM so Excel on Windows
            # reads Korean correctly; it also uploads directly to
            # Google Sheets. .xlsx is built stdlib-only (no
            # openpyxl dependency). Numbers stay numeric so the
            # sheet can compute on them; empty means no value.
            raw_dir = fields.get("dir", "")
            try:
                output_dir = Path(raw_dir).resolve()
            except OSError:
                output_dir = None
            if output_dir is None or not output_dir.is_dir():
                data = error_page(tr(lang, "err_prev_dir"), lang=lang)
                self._send_html(400, data)
                return
            matching_path = output_dir / "matching.json"
            if not matching_path.is_file():
                data = error_page(tr(lang, "err_export_nomatch"), lang=lang)
                self._send_html(400, data)
                return
            try:
                all_rows = json.loads(matching_path.read_text(
                    encoding="utf-8"))
            except Exception:
                all_rows = []
            raw_sel = fields.get("rows", [])
            if isinstance(raw_sel, str):
                raw_sel = [raw_sel]
            try:
                idxs = sorted({int(x) for x in raw_sel})
            except ValueError:
                idxs = []
            selected = [all_rows[i] for i in idxs
                        if 0 <= i < len(all_rows)]
            if not selected:
                data = error_page(tr(lang, "err_export_empty"), lang=lang)
                self._send_html(400, data)
                return
            fmt = fields.get("format", "csv")
            if isinstance(fmt, list):
                fmt = fmt[0] if fmt else "csv"
            if fmt not in ("csv", "xlsx"):
                data = error_page(tr(lang, "err_export_format"), lang=lang)
                self._send_html(400, data)
                return
            show_measured = any(r.get("measured") is not None
                                for r in selected)
            headers = [tr(lang, "th_no"),
                       tr(lang, "th_item"), tr(lang, "th_drawing"),
                       tr(lang, "th_modeling")]
            if show_measured:
                headers.append(tr(lang, "th_measured"))
            headers.append(tr(lang, "th_result"))

            def _cell(v):
                if v is None:
                    return ""
                if isinstance(v, bool):
                    return "True" if v else "False"
                return v

            body_rows = []
            for r in selected:
                vals = [r.get("no", ""), r.get("item", ""),
                        _cell(r.get("drawing")),
                        _cell(r.get("modeling"))]
                if show_measured:
                    vals.append(_cell(r.get("measured")))
                vals.append(r.get("result", ""))
                body_rows.append(vals)
            safe_name = "".join(c for c in output_dir.name
                                if c.isalnum() or c in ("-", "_", "."))
            filename = f"matching_{safe_name or 'result'}.{fmt}"
            if fmt == "csv":
                import csv
                import io
                buf = io.StringIO()
                writer = csv.writer(buf)
                writer.writerow(headers)
                writer.writerows(body_rows)
                payload = buf.getvalue().encode("utf-8-sig")
                ctype = "text/csv; charset=utf-8"
            else:
                payload = build_xlsx(headers, body_rows)
                ctype = ("application/vnd.openxmlformats-officedocument"
                         ".spreadsheetml.sheet")
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Disposition",
                             f"attachment; filename=\"{filename}\"")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        qa_trail = ""
        if parsed.path == "/answer":
            # Translate the answer form into a /run-equivalent
            # submission, then fall through to the shared /run logic
            # below. Drawing/outline come from the previous output
            # folder (no re-upload); answers become --text. With
            # rerun=1 (picker "Rerun selected folder") no answers are
            # posted: empty answers are allowed and the previous
            # run's gear setting is kept.
            prev_dir = None
            raw_dir = fields.get("dir", "")
            if raw_dir:
                try:
                    prev_dir = Path(raw_dir).resolve()
                except OSError:
                    prev_dir = None
            if prev_dir is None or not prev_dir.is_dir():
                data = error_page(tr(lang, "err_prev_dir"), lang=lang)
                self._send_html(400, data)
                return
            answers = fields.get("answers", "").strip()
            # Ask-first with NO questions: Continue work means "build
            # now", so empty answers are allowed in that one case.
            prev_report = ""
            prev_report_path = prev_dir / "report.txt"
            if prev_report_path.is_file():
                prev_report = prev_report_path.read_text(
                    encoding="utf-8", errors="replace")
            # Rerun (picker "Rerun selected folder"): no answers box
            # is posted, and the picker form has no gear checkbox, so
            # repeat the previous run's gear setting from its report
            # (same marker the result page uses for its checkbox).
            rerun = fields.get("rerun") == "1"
            if rerun and "gear" not in fields:
                if "Gear reference: included" in prev_report:
                    fields["gear"] = "on"
            prev_questions = ""
            prev_questions_path = prev_dir / "questions.txt"
            if prev_questions_path.is_file():
                prev_questions = prev_questions_path.read_text(
                    encoding="utf-8", errors="replace").strip()
            prev_dims_text = ""
            prev_dims_path = prev_dir / "dimensions.json"
            if prev_dims_path.is_file():
                try:
                    _dims = json.loads(prev_dims_path.read_text(
                        encoding="utf-8"))
                    _lines = []
                    for _d in _dims:
                        _pos = ""
                        if _d.get("x") is not None and _d.get("y") is not None:
                            _pos = f" @ ({_d['x']}, {_d['y']})"
                        _view = f" [{_d['view']}]" if _d.get("view") else ""
                        _val = _d.get('value', '')
                        if _d.get("reference"):
                            _val = f"({_val})"
                        _lines.append(
                            f"{_d.get('id', 'D?')}: {_d.get('label', '')} = "
                            f"{_val} mm{_pos}{_view}")
                    prev_dims_text = "\n".join(_lines)
                except Exception:
                    prev_dims_text = ""
            askfirst_no_questions = (
                "ASK-FIRST" in prev_report and not prev_questions
                and not (prev_dir / "model.fcstd").is_file())
            if not answers and not askfirst_no_questions and not rerun:
                data = error_page(tr(lang, "err_answers_empty"), lang=lang)
                self._send_html(400, data)
                return
            drawings = sorted(prev_dir.glob("input_drawing.*"))
            if not drawings:
                data = error_page(tr(lang, "err_prev_no_drawing"), lang=lang)
                self._send_html(400, data)
                return
            drawing_path = drawings[0]
            files["drawing"] = (drawing_path.name, drawing_path.read_bytes())
            outlines = sorted(prev_dir.glob("input_outline.*"))
            if outlines:
                outline_path = outlines[0]
                files["outline"] = (outline_path.name,
                                    outline_path.read_bytes())
            # resolve_run_output_dir() timestamps this, since the
            # previous folder already holds a report/model.
            fields["output_dir"] = str(prev_dir)
            # Accumulate the FULL Q&A trail. Until now only the
            # immediate previous questions + new answers went into
            # the prompt, so earlier rounds' answers were lost and
            # users had to re-paste everything every round (Oct 30
            # home-run pain). The trail is append-only (one entry per
            # round, no duplication), goes into the prompt in full,
            # and is saved as qa_history.txt in the new folder.
            prev_history = ""
            prev_history_path = prev_dir / "qa_history.txt"
            if prev_history_path.is_file():
                prev_history = prev_history_path.read_text(
                    encoding="utf-8", errors="replace").strip()
            prev_guidance = ""
            prev_guidance_path = prev_dir / "guidance.txt"
            if prev_guidance_path.is_file():
                prev_guidance = prev_guidance_path.read_text(
                    encoding="utf-8", errors="replace").strip()
            if rerun:
                _entry = ("Rerun:\n" + answers) if answers else \
                    "Rerun with no new instructions."
            elif prev_questions:
                _entry = ("Questions:\n" + prev_questions
                          + "\nAnswers:\n" + answers)
            elif prev_guidance:
                _entry = ("Answers to the guidance question:\n" + answers)
            elif answers:
                _entry = "Continued work instructions:\n" + answers
            else:
                _entry = "Ask-first step asked no questions. Build now."
            qa_trail = ((prev_history + "\n" if prev_history else "")
                        + _entry)
            fields["notes"] = (
                "Q&A history (all previous questions and answers, "
                "in order):\n" + qa_trail
                + ("\nNumbered drawing dimensions:\n" + prev_dims_text
                   if prev_dims_text else "")
                + f"\n(Previous run folder: {prev_dir.name})")

        dry_run = fields.get("dry_run") == "on"
        api_key = fields.get("api_key", "")
        # Key sources: (1) the password field, (2) a local .env file
        # read by run_pipeline.py. Only if neither is present, stop.
        if not dry_run and not api_key and not dotenv_key_present():
            data = error_page(tr(lang, "err_key"), lang=lang)
            self._send_html(400, data)
            return
        # Pre-flight: freecadcmd must be findable before any API call,
        # EXCEPT ask-first runs (nothing is built, so FreeCAD is not
        # needed yet). run_pipeline.py checks this too, but the UI
        # stops earlier with an explanation, so no API credit is spent.
        freecadcmd_value = fields.get("freecadcmd", "freecadcmd") or "freecadcmd"
        ask_first = fields.get("ask_first") == "on"
        if not dry_run and not ask_first and not freecadcmd_found(freecadcmd_value):
            data = error_page(tr(lang, "err_freecadcmd"), lang=lang)
            self._send_html(400, data)
            return
        if "drawing" not in files or not files["drawing"][1]:
            data = error_page(tr(lang, "err_drawing"), lang=lang)
            self._send_html(400, data)
            return

        output_dir = resolve_run_output_dir(fields.get("output_dir", ""))
        output_dir.mkdir(parents=True, exist_ok=True)
        original_name, drawing_bytes = files["drawing"]
        suffix = Path(original_name).suffix or ".png"
        input_path = output_dir / f"input_drawing{suffix}"
        input_path.write_bytes(drawing_bytes)

        command = [
            sys.executable,
            str(RUN_PIPELINE),
            "--drawing", str(input_path),
            "--output-dir", str(output_dir),
            "--freecadcmd", fields.get("freecadcmd", "freecadcmd") or "freecadcmd",
        ]
        if "outline" in files and files["outline"][1]:
            outline_name, outline_bytes = files["outline"]
            outline_suffix = Path(outline_name).suffix or ".bin"
            outline_path = output_dir / f"input_outline{outline_suffix}"
            outline_path.write_bytes(outline_bytes)
            command += ["--outline", str(outline_path)]
        notes = fields.get("notes", "").strip()
        if notes:
            command += ["--text", notes]
        if fields.get("gear") == "on":
            command.append("--gear")
        if ask_first:
            command.append("--ask-first")
        if dry_run:
            command.append("--dry-run")

        # The key travels ONLY in this subprocess environment, never
        # on the command line, never in a log, never on a result page.
        # Empty field: the inherited key is popped so run_pipeline.py
        # falls back to a local .env file (if one exists).
        env = dict(os.environ)
        if api_key:
            env["META_API_KEY"] = api_key
        else:
            env.pop("META_API_KEY", None)

        log_path = output_dir / "web_ui_run.log"
        with open(log_path, "w", encoding="utf-8") as log_file:
            result = subprocess.run(
                command, stdout=log_file, stderr=subprocess.STDOUT, timeout=3600
            )
        # Never show the key: web_ui_run.log holds only the pipeline's
        # own output, which never prints the key, and this page shows
        # only report/guidance/file names, never the command or the key.
        if parsed.path == "/answer" and prev_dir is not None:
            if qa_trail:
                try:
                    (output_dir / "qa_history.txt").write_text(
                        qa_trail + "\n", encoding="utf-8")
                except OSError:
                    pass
            for _name in ("dimensions.json", "drawing_numbered.png"):
                _src = prev_dir / _name
                _dst = output_dir / _name
                if _src.is_file() and not _dst.is_file():
                    try:
                        shutil.copyfile(_src, _dst)
                    except OSError:
                        pass
        data = result_page(output_dir, result.returncode, lang=lang)
        self._send_html(200, data)

    def _send_html(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Drawing-to-Parametric-CAD local web UI.")
    parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000).")
    args = parser.parse_args(argv)
    if not RUN_PIPELINE.is_file():
        print(f"ERROR: run_pipeline.py not found next to web_ui.py: {RUN_PIPELINE}",
              file=sys.stderr)
        return 2
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Drawing-to-Parametric-CAD web UI: http://127.0.0.1:{args.port}/", flush=True)
    print("Press Ctrl+C to stop. This server listens on localhost only.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
