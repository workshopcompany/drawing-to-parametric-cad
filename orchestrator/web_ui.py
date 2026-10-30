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
import html
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

PAGE_CSS = (
    "body{font-family:sans-serif;max-width:760px;margin:2em auto;padding:0 1em;}"
    "label{display:block;margin:1em 0 0.3em;font-weight:bold;}"
    "input[type=text],input[type=password],textarea{width:100%;box-sizing:border-box;}"
    "textarea{height:6em;}button{margin-top:1.5em;padding:0.6em 1.5em;}"
    "pre{white-space:pre-wrap;background:#f4f4f4;padding:1em;overflow:auto;}"
    ".note{color:#555;}"
)

FOOTER = (
    "<hr><p class=\"note\">실행 방법 — Windows: <code>python web_ui.py</code> / "
    "Mac·Linux: <code>python3 web_ui.py</code> — 그 뒤 브라우저에서 "
    "http://127.0.0.1:8000/ 을 여세요.<br>"
    "이 UI는 사용자의 PC에서만 돌아가며, Muse가 이 PC를 조종하게 하지 않습니다. "
    "FreeCAD도 대신하지 않습니다. FreeCAD 1.1.4가 필요하고, freecadcmd가 PATH에 "
    "없으면 위 freecadcmd 칸에 경로를 입력하세요.</p>"
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
        f"<title>{html.escape(title)}</title>"
        f"<style>{PAGE_CSS}</style></head><body>"
        f"<h1>{html.escape(title)}</h1>{body}{FOOTER}</body></html>"
    ).encode("utf-8")


def form_page():
    body = """
<form action="/run" method="post" enctype="multipart/form-data">
<label for="drawing">도면 이미지</label>
<input type="file" id="drawing" name="drawing" accept="image/*" required>
<label for="outline">윤곽 첨부 (선택)</label>
<input type="file" id="outline" name="outline" accept="image/*,.json,.txt">
<p class="note">윤곽 스냅 도구(outline_snap_tool.html)에서 뽑은 JSON, 또는 윤곽 이미지. JSON은 요약해서 LLM 프롬프트에 넣고, 이미지는 두 번째 이미지로 LLM에 보냅니다. 원본은 출력 폴더에 outline_input.* 으로 보관됩니다.</p>
<label for="notes">부품 설명 (선택)</label>
<textarea id="notes" name="notes" placeholder="예: 기어, 모듈 0.5, 30T"></textarea>
<label><input type="checkbox" name="gear" value="on"> 기어 부품 (체크하면 --gear, 기어 참조 포함)</label>
<label for="output_dir">출력 폴더</label>
<input type="text" id="output_dir" name="output_dir" value="./my_run_output">
<p class="note">서버를 시작한 폴더 기준 상대 경로입니다. 결과(.fcstd, .step, 보고서)가 이 폴더에 생깁니다.</p>
<label for="freecadcmd">freecadcmd</label>
<input type="text" id="freecadcmd" name="freecadcmd" value="freecadcmd">
<p class="note">FreeCAD 1.1.4가 PATH에 없으면, 전체 경로를 입력하세요. Windows 예: C:\\Program Files\\FreeCAD 1.1.4\\bin\\freecadcmd.exe (설치 폴더에 따라 다릅니다). 이 경로가 틀리면 API 호출 전에 여기서 멈춥니다.</p>
<label><input type="checkbox" name="dry_run" value="on"> dry-run (API 호출 없이 프롬프트 조립만 확인)</label>
<p class="note">처음엔 dry-run으로 프롬프트 조립부터 확인하세요.</p>
<label for="api_key">Meta API 키</label>
<input type="password" id="api_key" name="api_key" autocomplete="off">
<p class="note">키는 저장되지 않고, 이번 실행에만 사용됩니다. 채팅이나 코드에 붙여넣지 마세요. 키 칸을 비우면, 레포 폴더의 .env 파일에 있는 키를 사용합니다.</p>
<p class="note">.env 키: __DOTENV_STATUS__</p>
<button type="submit">실행</button>
</form>
<p class="note">실제 실행은 몇 분 걸릴 수 있습니다. 실행이 끝날 때까지 브라우저를 닫지 마세요.</p>
"""
    status = "있음" if dotenv_key_present() else "없음 (키 칸에 입력하거나, 레포 폴더에 .env 파일을 만드세요)"
    body = body.replace("__DOTENV_STATUS__", status)
    return page("Drawing-to-Parametric-CAD", body)


def error_page(message):
    body = f"<p>{html.escape(message)}</p><p><a href=\"/\">← 폼으로 돌아가기</a></p>"
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


def result_page(output_dir, returncode, stdout_tail=""):
    lines = []
    if returncode == 0:
        lines.append("<p><strong>실행 결과: 성공 (종료 코드 0)</strong></p>")
    else:
        lines.append(
            f"<p><strong>실행 결과: 실패 (종료 코드 {returncode})</strong></p>"
        )
    lines.append(f"<p>출력 폴더: {html.escape(str(output_dir))}</p>")
    report = output_dir / "report.txt"
    if report.is_file():
        lines.append("<h2>report.txt</h2><pre>")
        lines.append(html.escape(report.read_text(encoding="utf-8", errors="replace")))
        lines.append("</pre>")
    guidance = output_dir / "guidance.txt"
    if guidance.is_file():
        lines.append("<h2>guidance.txt</h2><pre>")
        lines.append(html.escape(guidance.read_text(encoding="utf-8", errors="replace")))
        lines.append("</pre>")
    # Visual section: input images and model previews, shown inline
    # in the browser (via /view, not as downloads).
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
    if input_images:
        lines.append("<h2>입력 이미지 (브라우저에서 보기)</h2>")
        for name in input_images:
            lines.append(
                f"<p>{html.escape(name)}<br>"
                f"<img src=\"{view_link(name)}\" "
                f"alt=\"{html.escape(name)}\" style=\"max-width:100%;\"></p>")
    if previews:
        lines.append("<h2>결과 프리뷰 (눈으로 보기)</h2>")
        lines.append("<p class=\"note\">STEP 테셀레이션에서 만든 음영 프리뷰입니다. "
                     "치수 도면이 아니라 형상 확인용입니다.</p>")
        for name in previews:
            lines.append(
                f"<p>{html.escape(name)}<br>"
                f"<img src=\"{view_link(name)}\" "
                f"alt=\"{html.escape(name)}\" style=\"max-width:100%;\"></p>")
    lines.append("<h2>출력 파일</h2><ul>")
    if output_dir.is_dir():
        for path in sorted(output_dir.iterdir()):
            if path.is_file():
                query = urllib.parse.urlencode(
                    {"dir": str(output_dir), "file": path.name}
                )
                lines.append(
                    f"<li><a href=\"/download?{query}\">{html.escape(path.name)}</a> "
                    f"({path.stat().st_size} bytes)</li>"
                )
    lines.append("</ul>")
    lines.append("<p><a href=\"/\">← 폼으로 돌아가기</a></p>")
    if stdout_tail:
        lines.append("<h2>실행 로그 (끝부분)</h2><pre>")
        lines.append(html.escape(stdout_tail))
        lines.append("</pre>")
    return page("실행 결과", "".join(lines))


class Handler(BaseHTTPRequestHandler):
    # Never log request bodies or query values that could carry secrets.
    # The form sends the key only in the POST body, which is never logged.
    def log_message(self, fmt, *args):
        sys.stderr.write(f"{self.address_string()} {fmt % args}\n")

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
        if parsed.path != "/run":
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

        output_dir = resolve_output_dir(fields.get("output_dir", ""))
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
