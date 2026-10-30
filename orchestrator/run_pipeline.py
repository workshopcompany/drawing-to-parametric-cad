#!/usr/bin/env python3
"""Drawing-to-Parametric-CAD orchestrator v0.1 (prototype).

What this is: the glue that currently lives in chat, packaged as one
minimal CLI script. It does NOT generate CAD itself and it does NOT
replace FreeCAD. It:
  1. assembles a prompt (principles + user text + drawing image),
  2. calls the Meta Model API (OpenAI-compatible) to generate a
     FreeCAD macro,
  3. saves the FULL raw API response before extracting any code,
  4. safety-checks the macro, runs it with freecadcmd,
  5. self-fixes code/API errors only, up to 3 attempts total,
  6. verifies the resulting STEP independently of the macro log.

Usage (real run, from the orchestrator/ folder):
  export META_API_KEY="..."
  python3 run_pipeline.py --drawing my_drawing.png --text "part notes" \
      --output-dir ./my_run_output

Usage (no API call, prompt assembly + path checks only):
  python3 run_pipeline.py --drawing my_drawing.png \
      --output-dir ./my_run_output --dry-run

Requirements:
  - FreeCAD 1.1.4 (freecadcmd in PATH, or pass --freecadcmd).
  - META_API_KEY from the Meta developer portal, in the environment
    only. This script never prints, logs, or hardcodes the key.
  - The principles file (default: MACRO_PRINCIPLES_EN.md next to this
    script). The gear reference file is included ONLY when --gear is
    passed; it is never auto-included for non-gear parts.

Checking the output in the FreeCAD GUI:
  Open <output-dir>/model.fcstd, check Body -> Sketch -> Pad/Pocket
  order, that each sketch is FullyConstrained, and that changing one
  sketch dimension and recomputing still gives one valid solid.
  STEP is an export only; the .fcstd file is the primary artifact.
  Volume is reference only, never a pass/fail gate.

Known gap (NOT automated yet):
  2D drawing extraction from .fcstd via TechDraw is not in this
  script. For now, make TechDraw pages manually in the FreeCAD GUI.

Exit codes: 0 = PASS, 1 = FAIL / guidance written, 2 = usage or
environment error (missing key, missing file, missing freecadcmd).
"""

import argparse
import base64
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

API_URL = "https://api.meta.ai/v1/chat/completions"
DEFAULT_MODEL = "muse-spark-1.3"
DEFAULT_MAX_TOKENS = 64000

MACRO_INSTRUCTION = (
    "Generate a FreeCAD macro that builds this part, with per-feature "
    "checks and diagnostic saves, following the principles. If a problem "
    "arises, guide with feature name, geometry index, exact error, cause, "
    "and a specific question - do NOT invent dimensions. "
    "Safety: do NOT use subprocess, socket, urllib, requests, shutil, "
    "eval, exec, open, os.system, os.environ, or AttachmentOffset. "
    "For file paths, plain string concatenation or os.path.join only, "
    "and save with doc.saveAs() / Part.export()."
)

# Safety: patterns rejected in a generated macro. The orchestrator itself
# may use the standard library; this list applies ONLY to macro text.
# Lesson from the Oct 29 home run (attempts 1-2 blocked before running):
# a blanket ban on ANY "os." / "sys." is a false positive — os.path.join
# and os.makedirs for output paths, and a bare "import sys", are benign
# and common in LLM macros. Only dangerous uses are blocked now.
SAFETY_PATTERNS = [
    (r"\bos\.(system|popen|remove|unlink|rmdir|removedirs|rename|replace|chmod|environ|getenv)\b", "dangerous os call"),
    (r"\bsubprocess\b", "subprocess"),
    (r"\bsocket\b", "socket"),
    (r"\burllib\b", "urllib"),
    (r"\brequests\b", "requests"),
    (r"\bshutil\b", "shutil"),
    (r"\beval\s*\(", "eval call"),
    (r"\bexec\s*\(", "exec call"),
    (r"\bopen\s*\(", "open call"),
    (r"\.write\s*\(", "write call"),
    (r"AttachmentOffset", "AttachmentOffset"),
]


def die(message, code=2):
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(code)


def load_dotenv_key():
    """Return META_API_KEY from a local .env file, or None.

    Search order: .env in the current working directory, then .env
    next to this script. Only the META_API_KEY line is read; the
    value is returned to the caller and never printed or logged.
    A .env file must NEVER be committed to GitHub (.gitignore
    blocks it) — it is a local-only convenience, an alternative
    to setting the environment variable in the shell.
    """
    candidates = [Path.cwd() / ".env", Path(__file__).resolve().parent / ".env"]
    for dotenv in candidates:
        try:
            text = dotenv.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() == "META_API_KEY":
                value = value.strip().strip('"').strip("'")
                if value:
                    return value
    return None


def load_text(path, label):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        die(f"cannot read {label} {path}: {exc}")


def summarize_outline_json(data, max_chars=6000):
    """Compact a snap-tool outline JSON for the prompt.

    Full sample lists (e.g. 1202 loop points) are NOT sent verbatim:
    they would cost ~18k tokens. Instead the summary keeps the
    structure (segment/slot/root keys), scalar values, and a sampled
    subset (every Nth point, max 200 points) of any long point list,
    plus its bounding box. The full original file is copied to the
    output folder as outline_input.* for the record.
    """
    lines = ["User-captured outline (snap tool output, summarized):"]
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, list):
                if value and isinstance(value[0], (list, tuple)):
                    xs = [p[0] for p in value if len(p) >= 1]
                    ys = [p[1] for p in value if len(p) >= 2]
                    step = max(1, len(value) // 200)
                    sample = value[::step][:200]
                    lines.append(
                        f"- {key}: {len(value)} points, "
                        f"bbox X {min(xs):.4f}..{max(xs):.4f}, "
                        f"Y {min(ys):.4f}..{max(ys):.4f}, "
                        f"sample (every {step}th, max 200): {sample}")
                else:
                    lines.append(f"- {key}: {value}")
            elif isinstance(value, dict):
                lines.append(f"- {key}: {value}")
            else:
                lines.append(f"- {key}: {value}")
    else:
        lines.append(str(data)[:max_chars])
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n... (outline summary truncated)"
    return text


def build_prompt(principles_text, gear_text, user_text, output_dir, outline_text=""):
    parts = [principles_text]
    if gear_text:
        parts.append(gear_text)
    if user_text:
        parts.append(f"User text:\n{user_text}")
    if outline_text:
        parts.append(outline_text)
    parts.append(MACRO_INSTRUCTION)
    # Tell the macro where its own outputs must go. These paths are
    # runtime values from --output-dir, never hardcoded in this script.
    parts.append(
        "Save the finished model to "
        f"{output_dir / 'model.fcstd'} and the STEP export to "
        f"{output_dir / 'model.step'}."
    )
    return "\n\n".join(parts)


def build_messages(prompt_text, image_b64, mime_type, extra=None,
                   outline_image=None):
    user_content = [
        {"type": "text", "text": prompt_text},
        {
            "type": "image_url",
            # Standalone equivalent of Muse's image_url direct send:
            # the drawing is sent as a base64 data URL in the
            # OpenAI-compatible message format.
            "image_url": {"url": f"data:{mime_type};base64,{image_b64}"},
        },
    ]
    if outline_image is not None:
        outline_b64, outline_mime = outline_image
        user_content.append(
            {"type": "text",
             "text": "Outline image (user-captured outline, second image):"})
        user_content.append(
            {"type": "image_url",
             "image_url": {"url": f"data:{outline_mime};base64,{outline_b64}"}})
    if extra:
        user_content.insert(0, {"type": "text", "text": extra})
    return [
        {
            "role": "user",
            "content": user_content,
        }
    ]


def call_api(api_key, model, max_tokens, messages):
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"API HTTP {exc.code}: {body}") from exc
    except OSError as exc:
        raise RuntimeError(f"API request failed: {exc}") from exc


def extract_content(response_json):
    try:
        message = response_json["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"unexpected API response shape: {exc}") from exc
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        return "\n".join(texts)
    return ""


def extract_macro(content):
    """Select the fence containing FreeCAD/PartDesign code.

    Examines the WHOLE response, not just the first fence.
    Returns None when no such fence exists.
    """
    fences = re.findall(r"```[^\n]*\n(.*?)```", content, re.DOTALL)
    for fence in fences:
        if "import FreeCAD" in fence or "PartDesign" in fence:
            return fence.strip() + "\n"
    return None


def looks_like_question(content):
    """Heuristic for a design-question response instead of code."""
    if extract_macro(content) is not None:
        return False
    lowered = content.lower()
    return ("?" in content) and any(
        word in lowered
        for word in ("question", "confirm", "clarify", "please tell", "which")
    )


def safety_check(macro_text):
    """Return a list of (line_number, pattern, line_text) hits."""
    hits = []
    for lineno, line in enumerate(macro_text.splitlines(), start=1):
        for pattern, label in SAFETY_PATTERNS:
            if re.search(pattern, line):
                hits.append((lineno, label, line.strip()[:160]))
                break
    return hits


def run_freecadcmd(freecadcmd, macro_path, log_path):
    with open(log_path, "w", encoding="utf-8") as log_file:
        result = subprocess.run(
            [freecadcmd, str(macro_path)],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            timeout=1800,
        )
    return result.returncode


def verify_step(freecadcmd, step_path, output_dir):
    """Independent STEP check. Returns a dict of measured values.

    NOTE: for B-spline models, Shape.BoundBox inflates from control
    poles, so the bbox here is computed from tessellation vertices,
    not from BoundBox alone. Volume is reported for reference only
    and is never a gate; the gates are solids == 1 and valid.
    """
    snippet = output_dir / "verify_step.py"
    snippet.write_text(
        "import Part, json\n"
        f"step_path = {str(step_path)!r}\n"
        f"tris_path = {str(output_dir / 'tris.json')!r}\n"
        "try:\n"
        "    shape = Part.read(step_path)\n"
        "    if isinstance(shape, (list, tuple)):\n"
        "        shape = shape[0]\n"
        "except Exception:\n"
        "    shape = Part.Shape()\n"
        "    shape.read(step_path)\n"
        "verts, _facets = shape.tessellate(0.01)\n"
        "with open(tris_path, 'w', encoding='utf-8') as fh:\n"
        "    json.dump({'verts': [[v.x, v.y, v.z] for v in verts],\n"
        "               'facets': [list(f) for f in _facets]}, fh)\n"
        "xs = [v.x for v in verts]; ys = [v.y for v in verts]; zs = [v.z for v in verts]\n"
        "print(f\"VERDICT solids={len(shape.Solids)} valid={shape.isValid()} \"\n"
        "      f\"volume={shape.Volume:.4f} \"\n"
        "      f\"tess_x={min(xs):.4f}..{max(xs):.4f} \"\n"
        "      f\"tess_y={min(ys):.4f}..{max(ys):.4f} \"\n"
        "      f\"tess_z={min(zs):.4f}..{max(zs):.4f}\")\n",
        encoding="utf-8",
    )
    log_path = output_dir / "verify.log"
    with open(log_path, "w", encoding="utf-8") as log_file:
        result = subprocess.run(
            [freecadcmd, str(snippet)],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            timeout=600,
        )
    text = log_path.read_text(encoding="utf-8", errors="replace")
    match = re.search(
        r"VERDICT solids=(\d+) valid=(\w+) volume=([\d.]+) "
        r"tess_x=([-\d.]+)\.\.([-\d.]+) "
        r"tess_y=([-\d.]+)\.\.([-\d.]+) "
        r"tess_z=([-\d.]+)\.\.([-\d.]+)",
        text,
    )
    if match is None or result.returncode != 0:
        return {"ok": False, "raw": text[-1000:]}
    solids, valid, volume = int(match.group(1)), match.group(2), float(match.group(3))
    return {
        "ok": True,
        "solids": solids,
        "valid": valid == "True",
        "volume": volume,
        "tess_x": (float(match.group(4)), float(match.group(5))),
        "tess_y": (float(match.group(6)), float(match.group(7))),
        "tess_z": (float(match.group(8)), float(match.group(9))),
    }


def append_log(path, text):
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def write_report(path, lines):
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Drawing-to-Parametric-CAD orchestrator v0.1: "
        "drawing + principles -> Meta API macro -> freecadcmd -> "
        "verified .fcstd + STEP. See the top-of-file docstring."
    )
    parser.add_argument("--drawing", required=True,
                        help="Drawing image file (read, never copied into the repo).")
    parser.add_argument("--outline", default="",
                        help="Optional outline attachment (snap-tool JSON or "
                        "outline image). JSON is summarized for the prompt "
                        "(full file copied to output folder); an image is "
                        "sent to the LLM as a second image.")
    parser.add_argument("--text", default="",
                        help="Optional user text / notes about the part.")
    script_dir = Path(__file__).resolve().parent
    parser.add_argument("--principles", default=str(script_dir / "MACRO_PRINCIPLES_EN.md"),
                        help="Principles file (default: MACRO_PRINCIPLES_EN.md next to this script).")
    parser.add_argument("--gear", action="store_true",
                        help="Part contains a gear: include the gear reference file.")
    parser.add_argument("--gear-reference",
                        default=str(script_dir / "GEAR_CREATION_REFERENCE.md"),
                        help="Gear reference file, used ONLY with --gear.")
    parser.add_argument("--output-dir", required=True,
                        help="Directory for ALL orchestrator outputs.")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"Meta model (default: {DEFAULT_MODEL}).")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS,
                        help=f"Max tokens (default: {DEFAULT_MAX_TOKENS}).")
    parser.add_argument("--freecadcmd", default="freecadcmd",
                        help="freecadcmd executable (default: freecadcmd in PATH).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Assemble the prompt and check paths only; do NOT call the API.")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_lines = ["Drawing-to-Parametric-CAD orchestrator v0.1"]
    self_fix_log = output_dir / "self_fix_log.txt"
    if self_fix_log.exists():
        self_fix_log.unlink()

    drawing_path = Path(args.drawing)
    if not drawing_path.is_file():
        die(f"drawing file not found: {drawing_path}")
    principles_text = load_text(args.principles, "principles file")

    gear_text = ""
    if args.gear:
        gear_text = load_text(args.gear_reference, "gear reference file")
        report_lines.append("Gear reference: included (--gear passed).")
    else:
        report_lines.append("Gear reference: excluded (no --gear flag).")

    mime_type, _enc = mimetypes.guess_type(str(drawing_path))
    if mime_type is None:
        mime_type = "application/octet-stream"
    image_b64 = base64.b64encode(drawing_path.read_bytes()).decode("ascii")

    # Optional outline attachment: JSON -> summarized prompt section;
    # image -> second image sent to the LLM. The original file is
    # always copied to the output folder for the record.
    outline_text = ""
    outline_image = None
    if args.outline:
        outline_path = Path(args.outline)
        if not outline_path.is_file():
            die(f"outline file not found: {outline_path}")
        outline_suffix = outline_path.suffix or ".bin"
        outline_copy = output_dir / f"outline_input{outline_suffix}"
        outline_copy.write_bytes(outline_path.read_bytes())
        outline_mime, _enc = mimetypes.guess_type(str(outline_path))
        if outline_suffix.lower() == ".json":
            try:
                outline_data = json.loads(outline_path.read_text(encoding="utf-8"))
                outline_text = summarize_outline_json(outline_data)
                report_lines.append(
                    f"Outline: {outline_path} (JSON, summarized for prompt, "
                    f"full copy at {outline_copy})")
            except (OSError, ValueError) as exc:
                die(f"cannot parse outline JSON {outline_path}: {exc}")
        elif (outline_mime or "").startswith("image/"):
            outline_image = (
                base64.b64encode(outline_path.read_bytes()).decode("ascii"),
                outline_mime)
            report_lines.append(
                f"Outline: {outline_path} (image, sent to LLM as second image, "
                f"copy at {outline_copy})")
        else:
            outline_text = (
                "User-captured outline (text file, first 8000 chars):\n"
                + outline_path.read_text(encoding="utf-8", errors="replace")[:8000])
            report_lines.append(
                f"Outline: {outline_path} (text, copy at {outline_copy})")

    base_prompt = build_prompt(principles_text, gear_text, args.text,
                               output_dir, outline_text)
    report_lines.append(f"Drawing: {drawing_path}")
    report_lines.append(f"Principles: {args.principles}")
    report_lines.append(f"Model: {args.model}, max_tokens: {args.max_tokens}")
    report_lines.append(f"Output dir: {output_dir}")

    if args.dry_run:
        prompt_path = output_dir / "prompt_dryrun.txt"
        prompt_path.write_text(base_prompt, encoding="utf-8")
        report_lines.append("Mode: DRY RUN - API was NOT called.")
        report_lines.append(f"Dry-run prompt written to: {prompt_path}")
        report_lines.append(f"Prompt length: {len(base_prompt)} characters.")
        report_lines.append("RESULT: DRY RUN OK")
        write_report(output_dir / "report.txt", report_lines)
        print("\n".join(report_lines))
        return 0

    # Key priority: (1) META_API_KEY environment variable, (2) a
    # local .env file (current folder, then next to this script).
    # The key is never printed, logged, or read from any other
    # store by this script.
    api_key = os.environ.get("META_API_KEY") or load_dotenv_key()
    if not api_key:
        die("META_API_KEY is not set. Set it in the environment "
            "(from the Meta developer portal), or create a local "
            ".env file next to this script with one line "
            "META_API_KEY=your-key (never commit .env), and retry. "
            "This script never asks for the key in chat and never "
            "prints it.")

    if shutil.which(args.freecadcmd) is None and not Path(args.freecadcmd).is_file():
        die(f"freecadcmd not found: {args.freecadcmd} "
            "(install FreeCAD 1.1.4 or pass --freecadcmd). "
            "On Windows, pass the full path to bin\\freecadcmd.exe "
            "in your FreeCAD install folder, or add that bin folder "
            "to PATH. This check runs BEFORE any API call, so no "
            "API credit is spent on this failure.")

    fcstd_path = output_dir / "model.fcstd"
    step_path = output_dir / "model.step"
    last_error = ""
    last_feature = "unknown (see run.log and macro.py)"
    for attempt in range(1, 4):
        append_log(self_fix_log,
                   f"Attempt {attempt}/3 started.")
        if attempt == 1:
            prompt_text = base_prompt
        else:
            prompt_text = (
                base_prompt
                + "\n\nPrevious attempt failed with this exact error:\n"
                + last_error
                + "\nFix ONLY the code/API error described above. "
                + "Do not change any dimension, outline, angle, or "
                + "user-confirmed answer. Regenerate the full macro. "
                + "Safety reminder: do NOT use subprocess, socket, "
                + "urllib, requests, shutil, eval, exec, open, "
                + "os.system, os.environ, or AttachmentOffset. "
                + "os.path.join / os.makedirs for output paths are "
                + "allowed; save with doc.saveAs() / Part.export()."
            )
        messages = build_messages(prompt_text, image_b64, mime_type,
                                  outline_image=outline_image)
        try:
            response_json = call_api(api_key, args.model, args.max_tokens, messages)
        except RuntimeError as exc:
            last_error = str(exc)
            append_log(self_fix_log,
                       f"Attempt {attempt}: API error: {last_error}")
            continue
        # Save FULL raw response BEFORE any extraction.
        raw_path = output_dir / "raw_response.txt"
        raw_path.write_text(json.dumps(response_json, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        (output_dir / f"raw_response_attempt{attempt}.txt").write_text(
            json.dumps(response_json, indent=2, ensure_ascii=False), encoding="utf-8")
        try:
            content = extract_content(response_json)
        except RuntimeError as exc:
            last_error = str(exc)
            append_log(self_fix_log,
                       f"Attempt {attempt}: response extraction error: {last_error}")
            continue
        if looks_like_question(content):
            # Design question: NOT self-fixed, NOT invented around.
            guidance = (
                "GUIDANCE: the API asked a design question instead of "
                "generating a macro. No dimension was invented.\n"
                f"Feature/geometry: {last_feature}\n"
                "Question (verbatim from API response):\n"
                f"{content}\n"
            )
            (output_dir / "guidance.txt").write_text(guidance, encoding="utf-8")
            report_lines.append("RESULT: FAIL - design question, see guidance.txt")
            write_report(output_dir / "report.txt", report_lines)
            print(guidance)
            return 1
        macro_text = extract_macro(content)
        if macro_text is None:
            last_error = "No FreeCAD/PartDesign code fence found in API response."
            append_log(self_fix_log,
                       f"Attempt {attempt}: {last_error}")
            continue
        macro_path = output_dir / "macro.py"
        macro_path.write_text(macro_text, encoding="utf-8")
        (output_dir / f"macro_attempt{attempt}.py").write_text(macro_text, encoding="utf-8")

        hits = safety_check(macro_text)
        safety_line = f"Attempt {attempt}: safety hits: {hits if hits else 'none'}"
        report_lines.append(safety_line)
        append_log(self_fix_log, safety_line)
        if hits:
            last_error = f"Safety check failed: {hits}"
            append_log(self_fix_log,
                       f"Attempt {attempt}: macro NOT run. {last_error}")
            continue

        run_log = output_dir / "run.log"
        try:
            returncode = run_freecadcmd(args.freecadcmd, macro_path, run_log)
        except OSError as exc:
            last_error = f"freecadcmd run failed: {exc}"
            append_log(self_fix_log, f"Attempt {attempt}: {last_error}")
            continue
        (output_dir / f"run_attempt{attempt}.log").write_text(
            run_log.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        append_log(self_fix_log,
                   f"Attempt {attempt}: freecadcmd exit {returncode}.")
        if returncode != 0:
            tail = run_log.read_text(encoding="utf-8", errors="replace")[-1000:]
            last_error = f"freecadcmd exit {returncode}. Log tail:\n{tail}"
            append_log(self_fix_log, f"Attempt {attempt}: {last_error}")
            continue
        if not fcstd_path.is_file() or not step_path.is_file():
            last_error = (
                "Run finished but output files are missing under output-dir: "
                f"model.fcstd exists={fcstd_path.is_file()}, "
                f"model.step exists={step_path.is_file()}. "
                "The macro must save to the output-dir paths in the prompt."
            )
            append_log(self_fix_log, f"Attempt {attempt}: {last_error}")
            continue

        verification = verify_step(args.freecadcmd, step_path, output_dir)
        report_lines.append(f"Attempt {attempt}: verification: {verification}")
        append_log(self_fix_log,
                   f"Attempt {attempt}: verification: {verification}")
        if not verification.get("ok"):
            last_error = "STEP verification snippet failed (see verify.log)."
            continue
        if verification["solids"] != 1 or not verification["valid"]:
            last_error = (
                "STEP verification FAIL: solids must be exactly 1 and "
                f"valid True; got solids={verification['solids']}, "
                f"valid={verification['valid']}. A macro log PASS alone "
                "is not a pass."
            )
            append_log(self_fix_log, f"Attempt {attempt}: {last_error}")
            continue

        # PASS: volume is reference only, never a gate.
        report_lines.append(f"Model: {fcstd_path}")
        report_lines.append(f"STEP: {step_path}")
        report_lines.append(f"Macro: {macro_path}")
        report_lines.append(f"Raw response: {raw_path}")
        report_lines.append(
            f"Verification: solids={verification['solids']}, "
            f"valid={verification['valid']}, "
            f"volume={verification['volume']:.4f} (reference only), "
            f"tess bbox X {verification['tess_x']}, "
            f"Y {verification['tess_y']}, Z {verification['tess_z']}.")
        # Visual previews (best-effort, never a gate): shaded PNGs
        # from the STEP tessellation, shown in the web UI result page.
        # A missing matplotlib or a render failure must NOT fail the
        # run — the .fcstd / STEP files are the result.
        preview_iso = output_dir / "preview_iso.png"
        preview_main = output_dir / "preview_main.png"
        tris_path = output_dir / "tris.json"
        render_script = Path(__file__).resolve().parent / "render_preview.py"
        try:
            preview_result = subprocess.run(
                [sys.executable, str(render_script), str(tris_path),
                 str(preview_iso), str(preview_main)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=300, text=True)
            if preview_iso.is_file() and preview_main.is_file():
                report_lines.append(
                    f"Previews: {preview_iso}, {preview_main}")
            else:
                report_lines.append(
                    "Previews: unavailable "
                    f"(render exit {preview_result.returncode}, "
                    f"output: {preview_result.stdout[-300:]})")
        except Exception as exc:
            report_lines.append(f"Previews: unavailable ({exc})")
        report_lines.append("RESULT: PASS")
        write_report(output_dir / "report.txt", report_lines)
        print("\n".join(report_lines))
        return 0

    # 3rd failure: STOP, guide, do NOT run a 4th time.
    guidance = (
        "GUIDANCE (3rd failure, stopped - no 4th run):\n"
        f"Feature/geometry: {last_feature}\n"
        f"Exact error: {last_error}\n"
        "Cause hypothesis: see self_fix_log.txt for the per-attempt "
        "errors; the last error above is the current cause.\n"
        "What was tried: 3 attempts total (first generation + up to "
        "2 regenerations with the exact error fed back). "
        "See self_fix_log.txt.\n"
        "Question/alternative: fix the error above in the macro, or "
        "answer the design question if the error is a missing or "
        "ambiguous dimension. Do not retry without that fix/answer.\n"
    )
    (output_dir / "guidance.txt").write_text(guidance, encoding="utf-8")
    report_lines.append("RESULT: FAIL - 3rd failure, see guidance.txt")
    write_report(output_dir / "report.txt", report_lines)
    print(guidance)
    return 1


if __name__ == "__main__":
    sys.exit(main())
