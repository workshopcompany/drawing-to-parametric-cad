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
    "Every dimension you are not 100% sure of from the drawing MUST be "
    "marked INFERRED in the macro AND must have a matching Q-line "
    "(Q1: ..., Q2: ...) in the macro header. A macro with INFERRED "
    "values and no Q-lines is incomplete - do not submit it. If the "
    "drawing shows a gear, knurl, thread, bore, notch, or chamfer you "
    "cannot dimension exactly, you MUST ask about it in a Q-line, "
    "even if you also build a provisional version. "
    "Q-lines are for OPEN questions only: a value already answered by "
    "the user, confirmed, or built exact is NOT a question - never list "
    "it as a Q-line, never restart numbering for it. Put "
    "already-answered/confirmed items in a separate 'Confirmed/built' "
    "note, not in Q-lines. "
    "Safety: do NOT use subprocess, socket, urllib, requests, shutil, "
    "eval, exec, open, os.system, os.environ, or AttachmentOffset. "
    "For file paths, plain string concatenation or os.path.join only, "
    "and save with doc.saveAs() / Part.export()."
)

ASK_FIRST_INSTRUCTION = (
    "ASK FIRST - do NOT write a macro, do NOT write code, do NOT build "
    "anything yet. Examine the drawing (and outline, if any) and list "
    "EVERYTHING that is ambiguous, undimensioned, conflicting, or "
    "unreadable, as numbered questions, one per line, in exactly this "
    "format: Q1: <what you provisionally read> - <what you need>. "
    "Q2: ... Ask about every gear, knurl, thread, bore, notch, "
    "chamfer, step, and flat you cannot dimension exactly from the "
    "drawing. If a dimension is missing, ask - do NOT guess, do NOT "
    "fill it with a provisional value in this step. If truly nothing "
    "is ambiguous, write exactly one line: NO QUESTIONS. Output ONLY "
    "the question list (or NO QUESTIONS) - no code fence, no macro, "
    "no explanation. "
    "After the questions, add a numbered dimension list for the "
    "dimensions you CAN read from the drawing, one per line, in "
    "exactly this format: D1: <what it is> = <value> mm @ (x, y) - "
    "where (x, y) is the APPROXIMATE position of that dimension on "
    "the drawing image as fractions 0-1, origin top-left (for "
    "example, D1: outer diameter = 22 mm @ (0.75, 0.20)). These "
    "positions are estimates for numbering badges on the drawing; "
    "if you cannot place a dimension, omit its @ (x, y) part."
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


def build_ask_prompt(principles_text, user_text, outline_text=""):
    """Ask-first prompt: questions only, no macro, no model yet."""
    parts = [principles_text]
    if user_text:
        parts.append(f"User text:\n{user_text}")
    if outline_text:
        parts.append(outline_text)
    parts.append(ASK_FIRST_INSTRUCTION)
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
    """Return a list of (line_number, pattern, line_text) hits.

    Comment text is NOT checked: a comment mentioning a blocked word
    (e.g. "# no AttachmentOffset use") does not execute, so it must
    not block a macro. Lesson from the Oct 30 home run: attempt 1 was
    blocked solely by such a comment, and the self-fix then dropped
    the pending-gear block with it. Only the code before the first
    '#' on each line is checked.
    """
    hits = []
    for lineno, line in enumerate(macro_text.splitlines(), start=1):
        code = line.split("#", 1)[0]
        for pattern, label in SAFETY_PATTERNS:
            if re.search(pattern, code):
                hits.append((lineno, label, line.strip()[:160]))
                break
    return hits


def _is_closed_status_line(text):
    """True if a Q-line is a status recap, not an open question.

    The LLM sometimes re-lists already-settled items in its question
    block (e.g. "Q1: Q26: answered and confirmed before, built exact")
    or points at another question ("Q28: ... see Q30"). Those are not
    open questions and must not reach questions.txt - only lines with
    a real unmet need stay. A line without "?" that says "confirmed"
    or points at another question is a recap, not a question.
    """
    low = text.lower()
    if "built exact" in low or "not repeated" in low or "already answered" in low:
        return True
    if "?" not in text and ("confirmed" in low or re.search(r"see\s+q\d+", low)):
        return True
    return False


def extract_questions(content, macro_text):
    """Extract unanswered design questions (Q1, Q2, ...) from a response.

    Looks for lines that START a question, after stripping markdown
    bullets/bold, macro comments ("# Q1 ..."), and prints
    ("print(\"Q1 ...\")"). Accepted labels: Q1, Question 1, with a
    colon, dot, dash, or closing paren after the number. Inline
    references such as "pending Q3/Q6" are NOT questions and are
    ignored. Lines that only recap a closed item (built exact,
    confirmed, already answered, or a "see Q<n>" pointer with no
    question mark) are skipped by _is_closed_status_line. Returns
    [(label, text), ...] sorted by number, deduped.
    """
    questions = {}
    for text in (content, macro_text):
        for line in text.splitlines():
            stripped = line.strip()
            stripped = re.sub(r"^[-*\u2022]\s+", "", stripped)
            stripped = stripped.replace("**", "").strip()
            m = re.match(r"#\s*(.+)", stripped)
            if m:
                stripped = m.group(1).strip()
            m = re.match(r'print\(\s*["\'](.+?)["\']\s*\)', stripped)
            if m:
                stripped = m.group(1).strip()
            m = re.match(r"(?:Q|Question)\s*(\d+)\s*[:.\-\)]\s*(.+)", stripped)
            if not m:
                continue
            label = f"Q{m.group(1)}"
            question = m.group(2).strip().rstrip('")').strip()
            if _is_closed_status_line(question):
                continue
            if label not in questions and len(question) > 3:
                questions[label] = question[:500]
    return [(label, questions[label])
            for label in sorted(questions, key=lambda q: int(q[1:]))]


def run_freecadcmd(freecadcmd, macro_path, log_path):
    with open(log_path, "w", encoding="utf-8") as log_file:
        result = subprocess.run(
            [freecadcmd, str(macro_path)],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            timeout=1800,
        )
    return result.returncode



# ---- Drawing <-> modeling matching ----
# "Drawing value" here means: the value the LLM read from the drawing
# and wrote into the macro (or, for ask-first D-dimensions, the value
# the LLM listed). It is NOT an independently measured drawing truth:
# if the LLM misread the drawing, both columns can be wrong together.
# The table therefore checks build-vs-intent (did FreeCAD actually
# build what the macro said?), plus the user-confirmed Q&A values
# when they are present in --text. Tolerance: 0.01 mm.
MATCH_TOL = 0.01


def _closest(values, target):
    if not values:
        return None
    return min(values, key=lambda v: abs(v - target))


def _match_row(no, item, drawing, modeling, tol=MATCH_TOL):
    if drawing is None:
        return {"no": no, "item": item, "drawing": None,
                "modeling": modeling, "result": "~"}
    if modeling is None:
        return {"no": no, "item": item, "drawing": drawing,
                "modeling": None, "result": "?"}
    if isinstance(drawing, bool):
        return {"no": no, "item": item, "drawing": drawing,
                "modeling": modeling,
                "result": "O" if modeling == drawing else "X"}
    diff = abs(float(modeling) - float(drawing))
    # 1e-9 epsilon: 22.01 - 22.0 is 0.010000000000002 in binary
    # floating point, which must still count as "within 0.01".
    return {"no": no, "item": item, "drawing": drawing,
            "modeling": modeling,
            "result": "O" if diff <= tol + 1e-9 else "X"}


def _keyword_target(name):
    """Map a dimension name/question to a measurement kind."""
    u = name.upper()
    if "RADIUS" in u:
        return "radius"
    if "DIA" in u or "DIAMETER" in u or "BORE" in u or "OUTER" in u:
        return "dia"
    if "LENGTH" in u or "TOTAL" in u or "AXIAL" in u:
        return "length"
    if "WIDTH" in u:
        return "width"
    if "HEIGHT" in u or "THICK" in u or "DEPTH" in u:
        return "height"
    return None


def _target_modeling(kind, verification):
    if kind == "radius":
        c = _closest(verification.get("cyl_diams", []), 0)
        # radius rows are converted to diameter before calling here
        return None
    if kind == "dia":
        return None  # handled by caller (needs the expected value)
    if kind == "length":
        return verification.get("size_x")
    if kind == "width":
        return verification.get("size_y")
    if kind == "height":
        return verification.get("size_z")
    return None


def parse_macro_dimensions(macro_text):
    """Parse top-level numeric assignments from a macro.

    Returns [(NAME, value), ...] deduped by NAME, first wins.
    Only names that look like dimensions are kept out of the
    blocklist; the caller decides which ones map to a measurement.
    """
    seen = {}
    block = {"MAX_TOKENS", "TOLERANCE", "TOL", "STEP_COUNT", "COUNT"}
    for line in macro_text.splitlines():
        m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*(?:#.*)?$", line)
        if not m:
            continue
        name, value = m.group(1).upper(), float(m.group(2))
        if name in block or name in seen:
            continue
        if not (0.01 <= value <= 1000):
            continue
        seen[name] = value
    return list(seen.items())


def parse_numbered_dimensions(text):
    """Parse ask-first / answer D-lines: D1: label = value @ (x, y).

    Position (x, y) is a 0-1 image fraction, origin top-left, and is
    APPROXIMATE (LLM vision estimate). Returns a list of dicts.
    """
    dims = []
    for line in text.splitlines():
        m = re.match(r"\s*(?:#\s*)?D(\d+)\s*[:\-\.]\s*(.+)", line.strip())
        if not m:
            continue
        rest = m.group(2).strip()
        pos = None
        pm = re.search(r"@\s*\(\s*([0-9]*\.?[0-9]+)\s*,\s*([0-9]*\.?[0-9]+)\s*\)", rest)
        if pm:
            try:
                pos = (float(pm.group(1)), float(pm.group(2)))
            except ValueError:
                pos = None
            rest = rest[:pm.start()].strip(" -:")
        vm = re.search(r"([0-9]+(?:\.[0-9]+)?)", rest)
        if not vm:
            continue
        try:
            value = float(vm.group(1))
        except ValueError:
            continue
        label = rest[:vm.start()].strip(" =:") or f"D{m.group(1)}"
        dims.append({"id": f"D{m.group(1)}", "label": label,
                     "value": value, "x": pos[0] if pos else None,
                     "y": pos[1] if pos else None})
    # Dedupe by id, first wins.
    out, seen_ids = [], set()
    for d in dims:
        if d["id"] not in seen_ids:
            seen_ids.add(d["id"])
            out.append(d)
    return out


def annotate_drawing(drawing_path, dims, out_path):
    """Draw numbered badges on a copy of the drawing (PIL, best-effort).

    Positions are LLM estimates, so badges are approximate: they mark
    roughly where the LLM thinks the dimension lives, not a measured
    location. Returns True if the image was written, False otherwise
    (PIL missing, unreadable image, or no positioned dimensions).
    """
    positioned = [d for d in dims if d.get("x") is not None
                  and d.get("y") is not None]
    if not positioned:
        return False
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return False
    try:
        img = Image.open(drawing_path).convert("RGB")
    except Exception:
        return False
    draw = ImageDraw.Draw(img)
    w, h = img.size
    r = max(14, min(w, h) // 40)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", r)
    except Exception:
        font = ImageFont.load_default()
    for d in positioned:
        x = min(max(d["x"], 0.0), 1.0) * w
        y = min(max(d["y"], 0.0), 1.0) * h
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(220, 38, 38),
                     outline=(255, 255, 255), width=2)
        label = d["id"]
        bbox = draw.textbbox((0, 0), label, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((x - tw / 2, y - th / 2), label, fill=(255, 255, 255),
                  font=font)
    try:
        img.save(out_path)
        return True
    except Exception:
        return False


def build_matching(verification, macro_text, user_text):
    """Build the drawing-vs-modeling table rows.

    Row order: D-dimensions (ask-first / answer text) first, then
    macro parameters not already covered, then always-present rows
    (solids, valid, bbox sizes, cylinder diameters, volume).
    """
    rows = []
    used_macro = set()
    # D-dimensions from --text (ask-first list carried via /answer,
    # or user notes written in D1: form).
    d_dims = parse_numbered_dimensions(user_text or "")
    for d in d_dims:
        kind = _keyword_target(d["label"])
        modeling = None
        if kind == "dia":
            modeling = _closest(verification.get("cyl_diams", []), d["value"])
        elif kind == "radius":
            modeling = _closest(verification.get("cyl_diams", []),
                                d["value"] * 2)
            if modeling is not None:
                modeling = modeling / 2
        elif kind in ("length", "width", "height"):
            modeling = _target_modeling(kind, verification)
        rows.append(_match_row(d["id"], d["label"], d["value"], modeling))
    # Macro parameters.
    for name, value in parse_macro_dimensions(macro_text):
        kind = _keyword_target(name)
        if kind is None:
            continue
        # Skip if a D-row already covers this kind+value.
        covered = False
        for d in d_dims:
            if _keyword_target(d["label"]) == kind and abs(d["value"] - value) <= MATCH_TOL:
                covered = True
                break
        if covered:
            continue
        modeling = None
        drawing = value
        if kind == "dia":
            modeling = _closest(verification.get("cyl_diams", []), value)
        elif kind == "radius":
            c = _closest(verification.get("cyl_diams", []), value * 2)
            modeling = (c / 2) if c is not None else None
            drawing = value
        elif kind in ("length", "width", "height"):
            modeling = _target_modeling(kind, verification)
        if modeling is None and kind not in ("dia", "radius"):
            continue
        rows.append(_match_row("—", name, drawing, modeling))
    # Always-present rows.
    rows.append(_match_row("—", "Solids (count)", 1, verification.get("solids")))
    rows.append(_match_row("—", "Valid solid", True, verification.get("valid")))
    for label, key in (("BBox size X", "size_x"), ("BBox size Y", "size_y"),
                       ("BBox size Z", "size_z")):
        rows.append(_match_row("—", label, None, verification.get(key)))
    cyl = verification.get("cyl_diams", [])
    rows.append(_match_row("—", "Cylinder diameters found", None,
                           ", ".join(f"{v:.2f}" for v in cyl) if cyl else None))
    rows.append(_match_row("—", "Volume (reference only)", None,
                           verification.get("volume")))
    return rows


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
        "cyl_diams = []\n"
        "for _f in shape.Faces:\n"
        "    try:\n"
        "        _s = _f.Surface\n"
        "        if _s.TypeId == 'Part::GeomCylinder':\n"
        "            cyl_diams.append(round(_s.Radius * 2, 4))\n"
        "    except Exception:\n"
        "        pass\n"
        "print(f\"VERDICT solids={len(shape.Solids)} valid={shape.isValid()} \"\n"
        "      f\"volume={shape.Volume:.4f} \"\n"
        "      f\"tess_x={min(xs):.4f}..{max(xs):.4f} \"\n"
        "      f\"tess_y={min(ys):.4f}..{max(ys):.4f} \"\n"
        "      f\"tess_z={min(zs):.4f}..{max(zs):.4f}\")\n"
        "print('CYLDIAMS ' + json.dumps(sorted(set(cyl_diams))))\n",
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
    tess_x = (float(match.group(4)), float(match.group(5)))
    tess_y = (float(match.group(6)), float(match.group(7)))
    tess_z = (float(match.group(8)), float(match.group(9)))
    cyl_match = re.search(r"CYLDIAMS (\[.*?\])", text)
    try:
        cyl_diams = json.loads(cyl_match.group(1)) if cyl_match else []
    except ValueError:
        cyl_diams = []
    return {
        "ok": True,
        "solids": solids,
        "valid": valid == "True",
        "volume": volume,
        "tess_x": tess_x,
        "tess_y": tess_y,
        "tess_z": tess_z,
        "size_x": tess_x[1] - tess_x[0],
        "size_y": tess_y[1] - tess_y[0],
        "size_z": tess_z[1] - tess_z[0],
        "cyl_diams": cyl_diams,
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
    parser.add_argument("--ask-first", action="store_true",
                        help="Ask questions FIRST and build nothing yet: "
                        "the LLM lists Q1... questions only, no macro, "
                        "no model. Answer via the web UI, then build.")
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
    if args.ask_first:
        # Ask-first replaces the build prompt entirely: questions
        # only, no macro, no model. The build happens on the next
        # run, with the answers as --text.
        base_prompt = build_ask_prompt(principles_text, args.text,
                                       outline_text)
        report_lines.append("Mode: ASK-FIRST - questions only, no model yet.")
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

    if args.ask_first:
        # Ask-first: one API call, questions only, NO freecadcmd
        # check (nothing is built, so FreeCAD is not needed yet),
        # NO macro, NO model, NO verification. If a problem arises
        # later during the build run, that run's questions are
        # surfaced the same way and the user is asked again.
        messages = build_messages(base_prompt, image_b64, mime_type,
                                  outline_image=outline_image)
        try:
            response_json = call_api(api_key, args.model,
                                     args.max_tokens, messages)
        except RuntimeError as exc:
            report_lines.append(f"RESULT: FAIL - ask-first API error: {exc}")
            write_report(output_dir / "report.txt", report_lines)
            print("\n".join(report_lines))
            return 1
        raw_path = output_dir / "raw_response.txt"
        raw_path.write_text(json.dumps(response_json, indent=2,
                                       ensure_ascii=False),
                            encoding="utf-8")
        try:
            content = extract_content(response_json)
        except RuntimeError as exc:
            report_lines.append(f"RESULT: FAIL - ask-first response error: {exc}")
            write_report(output_dir / "report.txt", report_lines)
            print("\n".join(report_lines))
            return 1
        questions = extract_questions(content, "")
        # Numbered dimensions: D1... with approximate positions,
        # saved for the web UI matching tab (numbered drawing +
        # table). Positions are LLM estimates, not measurements.
        try:
            d_dims = parse_numbered_dimensions(content)
            if d_dims:
                (output_dir / "dimensions.json").write_text(
                    json.dumps(d_dims, indent=2, ensure_ascii=False),
                    encoding="utf-8")
                report_lines.append(
                    f"Numbered dimensions: {len(d_dims)} "
                    f"(see dimensions.json, drawing_numbered.png)")
                if annotate_drawing(drawing_path, d_dims,
                                    output_dir / "drawing_numbered.png"):
                    report_lines.append(
                        "Numbered drawing: drawing_numbered.png "
                        "(badge positions are approximate)")
                else:
                    report_lines.append(
                        "Numbered drawing: not created (no positioned "
                        "dimensions, or PIL unavailable)")
        except Exception as exc:
            report_lines.append(f"Numbered dimensions: unavailable ({exc})")
        if questions:
            questions_text = "\n".join(f"{label}: {text}"
                                       for label, text in questions)
            (output_dir / "questions.txt").write_text(
                questions_text + "\n", encoding="utf-8")
            report_lines.append(
                "Questions (unanswered, from ask-first step): "
                + "; ".join(f"{label}: {text}"
                            for label, text in questions))
            report_lines.append(
                "RESULT: QUESTIONS PENDING (ask-first - no model built "
                "yet, answer questions.txt and continue)")
        elif "NO QUESTIONS" in content.upper():
            report_lines.append(
                "RESULT: ASK-FIRST NO QUESTIONS (no model built yet, "
                "press Continue work to build)")
        else:
            # Unformatted questions: do NOT silently pass. Keep the
            # whole answer as questions so the user can answer it.
            fallback = content.strip()[:4000]
            (output_dir / "questions.txt").write_text(
                f"Q1: {fallback}\n", encoding="utf-8")
            report_lines.append(
                "Questions (unanswered, from ask-first step, "
                "unformatted): " + fallback.replace("\n", " ")[:500])
            report_lines.append(
                "RESULT: QUESTIONS PENDING (ask-first - no model built "
                "yet, answer questions.txt and continue)")
        write_report(output_dir / "report.txt", report_lines)
        print("\n".join(report_lines))
        return 0

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
                + "user-confirmed answer. Do not drop any Q-lines or "
                + "question blocks from the previous attempt; carry "
                + "all unanswered questions forward in the new macro "
                + "header. Regenerate the full macro. "
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
            # Also write questions.txt: otherwise the web UI shows
            # "(None - this macro asked no questions)" and NO Continue
            # form, a dead end (Oct 30 home run: full Q1-Q12 answers
            # in, FAIL design question out, no way to continue).
            _qs = extract_questions(content, "")
            if _qs:
                _qt = "\n".join(f"{label}: {text}"
                                 for label, text in _qs)
            else:
                _qt = content.strip()
            (output_dir / "questions.txt").write_text(
                _qt + "\n", encoding="utf-8")
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

        # Surface design questions NOW, not only in macro comments /
        # run.log prints where the result page never shows them.
        # A macro that invents provisional values while asking Q1-Q9
        # must not later read as a clean PASS.
        questions = extract_questions(content, macro_text)
        if questions:
            questions_text = "\n".join(f"{label}: {text}"
                                       for label, text in questions)
            (output_dir / "questions.txt").write_text(
                questions_text + "\n", encoding="utf-8")
            report_lines.append(
                "Questions (unanswered, from macro): "
                + "; ".join(f"{label}: {text}"
                            for label, text in questions))

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

        # MODELING COMPLETE (not "success"): the only gate passed
        # here is solids == 1 and valid True on the STEP file.
        # Volume is reference only, never a gate. Drawing-vs-modeling
        # matching is computed separately below and shown as a table;
        # it is NOT folded into this gate, so a complete-but-wrong
        # model still reads as "modeling complete", never "success".
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
        # Chain: render_preview.py (matplotlib) first, then
        # render_preview_pil.py (Pillow+numpy, always present here).
        preview_iso = output_dir / "preview_iso.png"
        preview_main = output_dir / "preview_main.png"
        tris_path = output_dir / "tris.json"
        render_scripts = [
            Path(__file__).resolve().parent / "render_preview.py",
            Path(__file__).resolve().parent / "render_preview_pil.py",
        ]
        preview_ok = False
        preview_note = ""
        for render_script in render_scripts:
            if not render_script.is_file():
                continue
            try:
                preview_result = subprocess.run(
                    [sys.executable, str(render_script), str(tris_path),
                     str(preview_iso), str(preview_main)],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=300, text=True)
                if preview_iso.is_file() and preview_main.is_file():
                    report_lines.append(
                        f"Previews: {preview_iso}, {preview_main} "
                        f"(via {render_script.name})")
                    preview_ok = True
                    break
                preview_note = (
                    f"{render_script.name} exit {preview_result.returncode}, "
                    f"output: {preview_result.stdout[-300:]}")
            except Exception as exc:
                preview_note = f"{render_script.name}: {exc}"
        if not preview_ok:
            report_lines.append(f"Previews: unavailable ({preview_note})")
        # Drawing-vs-modeling matching table (matching.json + report
        # lines). Drawing values are the LLM's reading from the
        # drawing (macro parameters, plus D-dimensions from --text
        # when present); modeling values are measured from STEP.
        try:
            matching_rows = build_matching(verification, macro_text,
                                           args.text)
            (output_dir / "matching.json").write_text(
                json.dumps(matching_rows, indent=2, ensure_ascii=False),
                encoding="utf-8")
            for row in matching_rows:
                report_lines.append(
                    f"Matching: {row['no']} | {row['item']} | "
                    f"drawing={row['drawing']} | "
                    f"modeling={row['modeling']} | {row['result']}")
        except Exception as exc:
            report_lines.append(f"Matching: unavailable ({exc})")
        if questions:
            # Still exit 0 (a valid solid was built and its files
            # are kept), but this is NOT a success: provisional
            # values were used while these questions were
            # unanswered. The RESULT line therefore says MODELING
            # COMPLETE with QUESTIONS PENDING, never SUCCESS, and
            # the web UI banner says the same (it keys off
            # questions.txt, not this line).
            report_lines.append(
                "RESULT: MODELING COMPLETE - QUESTIONS PENDING "
                "(not a success, answer questions.txt and continue)")
        else:
            report_lines.append("RESULT: MODELING COMPLETE")
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
