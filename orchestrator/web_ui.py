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
  1. Shows one Korean form: drawing upload, part notes, gear checkbox,
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

FOOTER = (
    "<hr><p class=\"note\">실행 방법 — Windows: <code>python web_ui.py</code> / "
    "Mac·Linux: <code>python3 web_ui.py</code> — 그 뒤 브라우저에서 "
    "http://127.0.0.1:8000/ 을 여세요.<br>"
    "이 UI는 사용자의 PC(127.0.0.1)에서만 돌아가며, Muse가 이 PC를 조종하게 하지 않습니다. "
    "FreeCAD도 대신하지 않습니다. FreeCAD 1.1.4가 필요하고, freecadcmd가 PATH에 "
    "없으면 실행 설정 칸에 전체 경로를 입력하세요.<br>"
    "스타일 참조: mp3d-cad-system 대시보드(다크 테마 · 사이드바 · 2단 카드 · 탭 결과).</p>"
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


def page(title, body):
    return (
        "<!DOCTYPE html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{html.escape(title)}</title>"
        f"<style>{PAGE_CSS}</style></head><body>"
        f"{body}{FOOTER}</body></html>"
    ).encode("utf-8")


def form_page():
    status = ("있음" if dotenv_key_present()
              else "없음 (키 칸에 입력하거나, 레포 폴더에 .env 파일을 만드세요)")
    body = f"""
<form action="/run" method="post" enctype="multipart/form-data" id="runForm">
<div class="layout">
  <div class="sidebar">
    <h2>&#11042; Drawing&rarr;CAD</h2>
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
      {form_gallery_html()}
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
    return page("Drawing-to-Parametric-CAD", body)


def error_page(message):
    body = (f"<div class=\"layout\"><div class=\"sidebar\">"
            f"<h2>&#11042; Drawing&rarr;CAD</h2>"
            f"<p class=\"sub\">orchestrator v0.1</p><hr>"
            f"<p><a class=\"btn\" href=\"/\">← 폼으로 돌아가기</a></p></div>"
            f"<div class=\"main\"><h2 style=\"color:#f87171;\">오류</h2>"
            f"<div class=\"card\"><p>{html.escape(message)}</p></div></div></div>")
    return page("오류", body)


def parse_multipart(body, boundary):
    """Minimal multipart/form-data parser (stdlib only).

    Returns (fields, files): fields maps name -> str, files maps
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
            fields[name] = content.decode("utf-8", errors="replace")
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
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = Path(f"{path}_{stamp}")
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
                    if "RESULT: PASS" in text:
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


def sample_gallery_html():
    """Clickable bundled sample drawings served via /sample?name=."""
    samples = list_sample_images()
    if not samples:
        return ("<div class=\"card\"><h3>번들 샘플 도면</h3>"
                "<p class=\"note\">image/ 폴더에 샘플이 없습니다.</p></div>")
    cards = []
    for item in samples:
        name = item["name"]
        query = urllib.parse.urlencode({"name": name})
        cards.append(
            f"<div class=\"card\"><h3>{html.escape(name)}</h3>"
            f"<img class=\"shot\" src=\"/sample?{query}\" alt=\"{html.escape(name)}\">"
            f"<p class=\"note\"><a href=\"/sample?{query}\" target=\"_blank\">원본 크기</a> · "
            "실행 시 도면으로 쓰려면 이 파일을 왼쪽에서 직접 고르세요.</p></div>")
    return ("<div class=\"card\"><h3>번들 샘플 도면 (클릭하면 원본 크기)</h3>"
            "<p class=\"note\">image/ 폴더에 들어있는 도면입니다. 서버 파일이라 업로드 없이 바로 눈으로 확인됩니다.</p></div>"
            "<div class=\"grid2\">" + "".join(cards) + "</div>")


def recent_html():
    """Recent runs table (server-side, no JS fetch needed) + JS fallback box."""
    rows = ""
    for item in list_result_dirs():
        badge = ({"ok": "<span class=\"status-ok\">PASS</span>",
                  "fail": "<span class=\"status-err\">FAIL</span>"}.get(
                      item["status"], "<span class=\"status-warn\">?</span>"))
        query = urllib.parse.urlencode({"dir": item["dir"]})
        rows += (f"<tr><td>{html.escape(item['name'])}</td><td>{badge}</td>"
                 f"<td><a href=\"/result?{query}\">열기</a></td></tr>")
    if rows:
        table = (f"<table class=\"files\"><tr><th>출력 폴더</th><th>상태</th>"
                 f"<th>바로 보기</th></tr>{rows}</table>")
    else:
        table = "<p class=\"note\">최근 실행 기록이 없습니다. 위에서 도면을 골라 실행하세요.</p>"
    outline_link = ""
    try:
        if OUTLINE_TOOL_PATH.is_file():
            outline_link = ("<p class=\"note\">윤곽을 직접 그리고 싶으면 "
                            "<a href=\"/outline-tool\" target=\"_blank\">윤곽 스냅 도구 열기</a>"
                            " → JSON 다운 → 왼쪽 윤곽 첨부에 올리세요.</p>")
    except OSError:
        pass
    return (f"<div class=\"card\"><h3>&#128193; 최근 실행 결과 바로 보기</h3>"
            f"<p class=\"note\">재실행 없이 눈으로 확인. 새 결과도 아래 목록에 바로 뜹니다.</p>"
            f"{table}{outline_link}"
            "<div id=\"recentBox\" class=\"note\" style=\"display:none;\"></div></div>")


def form_gallery_html():
    """t1 bottom: recent runs + bundled samples (server-side, no JS needed)."""
    return recent_html() + sample_gallery_html()


def viewer_html(output_dir):
    """Interactive canvas viewer block (viewer3d.js + /tris data)."""
    query = urllib.parse.urlencode({"dir": str(output_dir)})
    tris, err = tris_payload(output_dir)
    if tris is None:
        why = {"missing": "<code>tris.json</code> 없음 (freecadcmd 결과가 아닙니다).",
               "too-large": "<code>tris.json</code> 8MB 초과 — 브라우저 보호를 위해 뷰어 생략.",
               "scope": "범위 밖 경로.", "bad-shape": "<code>tris.json</code> 형식 오류."}.get(err, html.escape(err))
        return ("<div class=\"card\"><h3>&#129521; 돌려보는 3D 뷰어</h3>"
                f"<p class=\"note\">뷰어 없음 ({why} 아래 PNG 프리뷰를 보세요).</p></div>")
    js_query = urllib.parse.urlencode({"v": str(VIEWER_JS_PATH.stat().st_mtime)}) \
        if VIEWER_JS_PATH.is_file() else "v=1"
    return f"""
      <div class="card"><h3>&#129521; 돌려보는 3D 뷰어 (tris.json)</h3>
      <p class="note">드래그 회전 · 휠 줌 · 버튼 시점 전환. CDN 없이 이 페이지 안에서만 돕니다.
      facet {html.escape(str(len(tris['facets'])))}개 · 아래 PNG는 같은 형상의 정지 이미지입니다.</p>
      <div class="viewer-wrap"><canvas id="viewer3d" width="900" height="420"></canvas>
      <div class="viewer-bar" id="viewerBar">로딩 중…</div></div>
      <div class="viewer-tools">
        <button type="button" data-view="iso">ISO</button>
        <button type="button" data-view="main">정면(큰 면)</button>
        <button type="button" data-view="top">위</button>
        <button type="button" data-view="side">옆</button>
      </div>
      <div class="kv" id="viewerMeta"></div></div>
      <script>window.TRIS_URL='/tris?{query}';</script>
      <script src="/viewer3d.js?{js_query}"></script>"""


def result_page(output_dir, returncode, stdout_tail=""):
    # Dashboard-style result (mp3d Tab 1/2/3/4 look): status banner +
    # tabbed cards for input images, 3D previews, files/downloads, QA logs.
    if returncode == 0:
        banner = "<span class=\"status-ok\">✅ 성공 (종료 코드 0)</span>"
    else:
        banner = (f"<span class=\"status-err\">❌ 실패 "
                  f"(종료 코드 {html.escape(str(returncode))})</span>")
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
    # A provisional PASS is still exit 0, but the banner must say so:
    # provisional values were used while questions were unanswered.
    if returncode == 0 and "provisional" in report_text:
        banner = ("<span class=\"status-warn\">⚠️ 성공 (임시 — 질문 대기 중, "
                  "questions.txt 확인)</span>")

    # Answer form (only when questions exist): POST /answer reuses the
    # previous run's drawing/outline and starts a NEW run with the
    # answers as --text. It is not a resume of the old macro.
    answer_form = ""
    if questions_text.strip():
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
        answer_form = f"""
      <div class="card"><h3>✏️ 질문에 답변하고 다시 실행</h3>
      <p class="note">아래에 답을 적으면, 도면/윤곽은 이 결과에서 자동으로 가져오고
      답변을 넣은 새 실행이 시작됩니다. 이전 매크로를 이어서 고치는 게 아니라,
      처음부터 새로 만드는 실행입니다. 출력은 시간 붙은 새 폴더에 생깁니다.
      이전 부품 설명은 자동으로 안 넘어가니, 필요하면 답변에 같이 적으세요.</p>
      <form action="/answer" method="post" enctype="multipart/form-data">
      <input type="hidden" name="dir" value="{dir_query}">
      <label for="answers">답변 (질문별로 적으세요)</label>
      <textarea id="answers" name="answers" rows="10">{html.escape(prefill)}</textarea>
      <label for="freecadcmd_answer">freecadcmd</label>
      <input type="text" id="freecadcmd_answer" name="freecadcmd" value="freecadcmd">
      <label><input type="checkbox" name="gear" value="on" {gear_checked} style="width:auto;"> 기어 부품</label>
      <label><input type="checkbox" name="dry_run" value="on" style="width:auto;"> dry-run (프롬프트 조립만 확인)</label>
      <label for="api_key_answer">Meta API 키</label>
      <input type="password" id="api_key_answer" name="api_key" autocomplete="off">
      <p class="note">키는 저장되지 않고 이번 실행에만 사용. 비우면 레포 폴더 .env 키 사용.</p>
      <button type="submit">답변하고 다시 실행</button>
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
        pills += "<span class=\"feat-pill\">.fcstd 본체</span>"
    if previews:
        pills += (f"<span class=\"feat-pill\">프리뷰 "
                  f"{html.escape(str(len(previews)))}장</span>")

    def img_card(name, caption):
        return (f"<div class=\"card\"><h3>{html.escape(name)}</h3>"
                f"<p class=\"note\">{caption} 클릭하면 원본 크기로 새 탭에 열립니다.</p>"
                f"<img class=\"shot\" src=\"{view_link(name)}\" "
                f"alt=\"{html.escape(name)}\"></div>")

    if input_images:
        t1_cards = "".join(
            img_card(n, "입력 도면 / 윤곽 (브라우저 보기)")
            for n in input_images)
    else:
        t1_cards = ("<div class=\"card\"><p class=\"note\">"
                    "입력 이미지가 없습니다.</p></div>")
    if previews:
        t2_cards = "".join(
            img_card(n, "STEP 테셀레이션 음영 프리뷰 — 형상 확인용")
            for n in previews)
    else:
        t2_cards = ("<div class=\"card\"><p class=\"note\">결과 프리뷰가 없습니다 "
                    "(렌더 실패 — .fcstd / STEP 파일 자체는 위 목록을 확인).</p></div>")
    t2_viewer = viewer_html(output_dir)

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
                    f"<td><a href=\"/download?{query}\">다운로드</a> · "
                    f"<a href=\"/view?{query}\">보기</a></td></tr>"
                )
    body = f"""
<div class="layout">
  <div class="sidebar">
    <h2>&#11042; Drawing&rarr;CAD</h2>
    <p class="sub">orchestrator v0.1 &middot; 실행 결과</p>
    <hr>
    <div class="card"><h3 style="font-size:14px;">실행 결과</h3><p>{banner}</p>
    <p class="note">출력 폴더<br><code>{html.escape(str(output_dir))}</code></p>
    <p><a class="btn" href="/">← 폼으로 돌아가기</a></p></div>
  </div>
  <div class="main">
    <h2 style="color:#7eb8f7;font-size:22px;margin:0;">실행 결과</h2>
    <p>{banner}</p>
    <p>{pills}</p>
    <div class="tabs">
      <button type="button" class="tab-btn active" data-tab="r1">&#128008; 도면 인식</button>
      <button type="button" class="tab-btn" data-tab="r2">&#129521; 파라미터 &amp; 3D</button>
      <button type="button" class="tab-btn" data-tab="r3">&#128295; FreeCAD 내보내기</button>
      <button type="button" class="tab-btn" data-tab="r4">&#128269; QA 로그</button>
    </div>
    <div class="tab-panel active" id="r1">
      <div class="card"><h3>🖼 원본 / 입력 이미지</h3>
      <p class="note">출력 폴더의 <code>input_drawing.*</code> / <code>input_outline.*</code> 을 브라우저에서 바로 봅니다.</p></div>
      <div class="grid2">{t1_cards}</div>
    </div>
    <div class="tab-panel" id="r2">
      {t2_viewer}
      <div class="grid2">{t2_cards}</div>
    </div>
    <div class="tab-panel" id="r3">
      <div class="card"><h3>🔧 출력 파일</h3>
      <table class="files"><tr><th>파일</th><th>bytes</th><th>링크</th></tr>{file_rows}</table></div>
    </div>
    <div class="tab-panel" id="r4">
      <div class="card"><h3>❓ questions.txt (미답변 질문)</h3><pre>{html.escape(questions_text) if questions_text else "(없음 — 이번 매크로에 질문이 없습니다)"}</pre><p class="note">매크로 주석/출력에서 뽑은 질문입니다. 임시값으로 만든 결과라면, 답을 주고 다시 실행하세요.</p></div>
      {answer_form}
      <div class="grid2">
        <div class="card"><h3>report.txt</h3><pre>{html.escape(report_text) if report_text else "(없음)"}</pre></div>
        <div class="card"><h3>guidance.txt</h3><pre>{html.escape(guidance_text) if guidance_text else "(없음 — 성공 시 생기지 않습니다)"}</pre></div>
      </div>
      <div class="card"><h3>실행 로그 (끝부분)</h3><pre>{html.escape(stdout_tail) if stdout_tail else "(없음)"}</pre></div>
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
    return page("실행 결과", body)


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
            data = form_page()
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
            output_dir = Path(raw_dir).resolve() if raw_dir else None
            ok = (output_dir is not None and output_dir.is_dir()
                  and ((output_dir / "report.txt").is_file()
                       or (output_dir / "guidance.txt").is_file()
                       or (output_dir / "model.step").is_file()))
            if not ok:
                self._send_html(400, error_page("결과 폴더를 열 수 없습니다."))
                return
            data = result_page(output_dir, 0 if (output_dir / "report.txt").is_file()
                               and "RESULT: PASS" in (output_dir / "report.txt").read_text(
                                   encoding="utf-8", errors="replace") else 1)
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
                data = error_page("브라우저에서 볼 수 없는 파일입니다.")
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
                data = error_page("다운로드할 수 없는 경로입니다.")
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
        if parsed.path not in ("/run", "/answer"):
            self.send_error(404, "Not found")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        body = self.rfile.read(length) if length > 0 else b""
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type or "boundary=" not in content_type:
            data = error_page("폼 형식이 올바르지 않습니다. 폼에서 다시 제출하세요.")
            self._send_html(400, data)
            return
        boundary = content_type.split("boundary=", 1)[1].strip().strip('"').encode("ascii")
        try:
            fields, files = parse_multipart(body, boundary)
        except Exception:
            data = error_page("업로드 파싱에 실패했습니다. 다시 제출하세요.")
            self._send_html(400, data)
            return

        if parsed.path == "/answer":
            # Translate the answer form into a /run-equivalent
            # submission, then fall through to the shared /run logic
            # below. Drawing/outline come from the previous output
            # folder (no re-upload); answers become --text.
            prev_dir = None
            raw_dir = fields.get("dir", "")
            if raw_dir:
                try:
                    prev_dir = Path(raw_dir).resolve()
                except OSError:
                    prev_dir = None
            if prev_dir is None or not prev_dir.is_dir():
                data = error_page("이전 결과 폴더를 찾을 수 없습니다.")
                self._send_html(400, data)
                return
            answers = fields.get("answers", "").strip()
            if not answers:
                data = error_page("답변을 입력하세요.")
                self._send_html(400, data)
                return
            drawings = sorted(prev_dir.glob("input_drawing.*"))
            if not drawings:
                data = error_page("이전 결과에 도면(input_drawing.*)이 없습니다.")
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
            fields["notes"] = (
                "Answers to the previous run's questions:\n"
                + answers
                + f"\n(Previous run folder: {prev_dir.name})")

        dry_run = fields.get("dry_run") == "on"
        api_key = fields.get("api_key", "")
        # Key sources: (1) the password field, (2) a local .env file
        # read by run_pipeline.py. Only if neither is present, stop.
        if not dry_run and not api_key and not dotenv_key_present():
            data = error_page("API 키를 입력하거나, dry-run을 선택하거나, "
                              "레포 폴더에 .env 파일을 만드세요.")
            self._send_html(400, data)
            return
        # Pre-flight: freecadcmd must be findable before any API call.
        # run_pipeline.py checks this too, but the UI stops earlier
        # with a Korean explanation, so no API credit is spent.
        freecadcmd_value = fields.get("freecadcmd", "freecadcmd") or "freecadcmd"
        if not dry_run and not freecadcmd_found(freecadcmd_value):
            data = error_page(
                "freecadcmd를 찾을 수 없습니다. FreeCAD 1.1.4가 설치돼 있는지 "
                "확인하고, freecadcmd 칸에 전체 경로를 입력하세요. "
                "Windows 예: C:\\Program Files\\FreeCAD 1.1.4\\bin\\freecadcmd.exe "
                "(설치 폴더에 따라 다릅니다). 이 단계에서 API는 호출되지 "
                "않았습니다.")
            self._send_html(400, data)
            return
        if "drawing" not in files or not files["drawing"][1]:
            data = error_page("도면 이미지를 선택하세요.")
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
        data = result_page(output_dir, result.returncode)
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
