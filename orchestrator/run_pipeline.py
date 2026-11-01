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
  5. self-fixes code/API errors only, up to 4 attempts total,
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
import ast
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
from datetime import datetime
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
    "and save with doc.saveAs() / Part.export(). "
    "Dimension-to-feature mapping (REQUIRED, no exceptions): at the "
    "very top of the macro, before any build code, define a FEATURE_MAP "
    "dict literal keyed by the D-numbers from the dimension list "
    "(D1, D2, ...). One entry per dimension you build, for example: "
    "FEATURE_MAP = {\"D8\": {\"feature\": \"Pad_Step\", \"sketch\": "
    "\"Sketch_Step\", \"kind\": \"diameter\", \"view\": \"front\", "
    "\"region\": None, \"datum\": None}}. "
    "feature = the PartDesign feature name that creates this dimension; "
    "sketch = the sketch that defines it (or None); kind = one of "
    "pad_length (Pad/Pocket Length), diameter, radius, "
    "sketch_constraint (a value inside the sketch), feature_extent "
    "(size of the feature's own shape; add \"axis\": \"X\"/\"Y\"/\"Z\"), "
    "span (distance between two places; add \"datum\": "
    "\"<Feature>.top\" or \"<Feature>.bottom\" and \"region\" when only "
    "part of the feature counts, e.g. \"left\" for a left tip; for a "
    "LOCAL extremum such as a hook tip dip, add \"localmin\": true "
    "so the value is the lowest interior local minimum of the "
    "feature's curves in the region, not a face bbox). "
    "For sketch_constraint dimensions, name the driving constraint "
    "after the D-number with sketch.renameConstraint(index, \"D<n>\") "
    "right after adding it, so the value can be read back exactly. "
    "Every built dimension MUST have a FEATURE_MAP entry; a dimension "
    "without one will show ? in the table, never a guessed value. "
    "Feature order (REQUIRED): build ALL Pad and Pocket features "
    "first, in body order, and put ALL finishing operations "
    "(Chamfer, Fillet, Round) LAST, after every Pad/Pocket. Never "
    "apply a Chamfer/Fillet in the middle of the tree (for example "
    "right after a Pad_Body) and then keep building Pockets after "
    "it: a mid-tree Chamfer changes the tip and later features can "
    "lose earlier Pads. A Chamfer/Fillet Base must be the "
    "immediately preceding feature (the current tip), never an "
    "earlier Pad/Pocket -- basing a Chamfer on an earlier Pad drops "
    "every Pad built after that Pad from the result."
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
    "if you cannot place a dimension, omit its @ (x, y) part. "
    "After the position, add the view in square brackets: [front] "
    "for the front view, [section] for a section view, [side] for "
    "the side view, [top] for the top view (for example, D1: outer "
    "diameter = 22 mm @ (0.75, 0.20) [front]). Omit the bracket if "
    "you cannot tell the view. Reference dimensions (shown in "
    "parentheses on the drawing) keep their parentheses around the "
    "value, for example D2: lower reference = (1.97) mm @ (0.20, 0.80)."
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


def build_prompt(principles_text, gear_text, user_text, output_dir, outline_text="",
                 reference_text=""):
    parts = [principles_text]
    if gear_text:
        parts.append(gear_text)
    if user_text:
        parts.append(f"User text:\n{user_text}")
    if outline_text:
        parts.append(outline_text)
    parts.append(MACRO_INSTRUCTION)
    # Reference position (documented, consistent): a retry-only
    # "Reference" part goes HERE, after the instruction and before
    # the output paths. Prompt order is otherwise unchanged:
    # principles -> gear ref -> user text -> outline -> instruction
    # -> Reference (retry only) -> output paths. The reference is
    # never prepended ahead of the principles and never appended
    # after the output paths, so the LLM always sees it in the
    # same place on every retry.
    if reference_text:
        parts.append(reference_text)
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
    # Fenceless code: a response that IS a macro (starts with a
    # FreeCAD header or contains "import FreeCAD") must not be
    # misread as prose or as a question. Return the code from its
    # first code line onward; freecadcmd / the safety check will
    # judge it from there, and a syntax failure self-fixes like
    # any other code failure instead of polluting questions.txt.
    if "import FreeCAD" in content:
        starts = [i for i in (content.find("# FreeCAD macro"),
                              content.find("import FreeCAD")) if i >= 0]
        if starts:
            return content[min(starts):].strip() + "\n"
    return None


def extract_feature_map(macro_text):
    """Parse the FEATURE_MAP dict literal from macro text.

    Returns (mapping, warning_or_None). mapping maps "D<n>" -> entry
    dict. Accepts a dict literal keyed by D-number, or a list of
    entry dicts each carrying "no". The search walks the whole AST,
    so the dict is found even inside a try block. Anything else
    (missing, unparseable, wrong shape) returns ({}, warning) and
    never raises: a missing map degrades to ? rows, not a crash.
    """
    try:
        tree = ast.parse(macro_text or "")
    except SyntaxError:
        return {}, "FEATURE_MAP: macro does not parse"
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "FEATURE_MAP":
                try:
                    value = ast.literal_eval(node.value)
                except (ValueError, SyntaxError):
                    return {}, "FEATURE_MAP: not a literal"
                entries = {}
                if isinstance(value, dict):
                    for key, entry in value.items():
                        if isinstance(entry, dict):
                            entries[str(key)] = entry
                elif isinstance(value, list):
                    for entry in value:
                        if isinstance(entry, dict) and entry.get("no"):
                            clean = dict(entry)
                            clean.pop("no", None)
                            entries[str(entry["no"])] = clean
                else:
                    return {}, "FEATURE_MAP: wrong shape"
                return entries, None
    return {}, "FEATURE_MAP: not present in macro"


def extract_feature_map_from_response(content):
    """Extract FEATURE_MAP from a raw LLM response (remap only).

    BUG (Oct 31, 2026 home remap failure): the remap prompt tells
    the LLM to answer in a code fence, but extract_feature_map()
    runs ast.parse() on the whole text, so a fenced answer fails
    with "macro does not parse" and the remap always fails -- the
    LLM followed the instruction exactly and the extractor
    rejected it. This helper strips fences first, then accepts
    either a FEATURE_MAP = {...} assignment or a bare {...} dict
    literal, both validated the same way afterwards.
    """
    text = content or ""
    fences = re.findall(r"```[^\n]*\n(.*?)```", text, re.DOTALL)
    if fences:
        text = fences[0]
    mapping, warn = extract_feature_map(text)
    if mapping:
        return mapping, None
    if warn == "FEATURE_MAP: macro does not parse":
        # A prose/no-map answer is not a parse problem, it is just
        # missing -- say so, so remap_log.txt does not mislead.
        warn = "FEATURE_MAP: not present in response"
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            value = ast.literal_eval(stripped)
        except (ValueError, SyntaxError):
            value = None
        if isinstance(value, dict):
            entries = {str(k): v for k, v in value.items()
                       if isinstance(v, dict)}
            if entries:
                return entries, None
    return {}, warn


def looks_like_question(content):
    """Heuristic for a design-question response instead of code.

    Code is NEVER a question: a response containing FreeCAD code
    markers (even without a fence, and even if it also contains
    "?" or the word "question" inside log strings) is a macro
    response, not a design question. Without this check, a
    fenceless macro was misclassified and dumped whole into
    questions.txt (Oct 30, 2026 home file).
    """
    if _is_code_like(content):
        return False
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


# ---- questions.txt contract (Oct 30, 2026, questions-window macro dump) ----
# Root cause, confirmed from a real home questions.txt (16,299 chars):
# the LLM returned a macro WITHOUT a code fence. extract_macro()
# requires a fence, so it returned None; looks_like_question() then
# saw "?" and the word "question" inside log("QUESTION: ...") strings
# and misclassified the whole macro as a design question; the
# design-question fallback wrote the entire response verbatim into
# questions.txt, and the web UI displayed it as "questions".
# The fix is a contract, not one more filter:
#  * questions.txt is written ONLY by write_questions(), and only
#    with validated Q-lines. Code, prose, and whole responses NEVER
#    go there; they belong in raw_response.txt / guidance.txt.
#  * A response containing FreeCAD code is code, not a question,
#    fence or no fence (see looks_like_question / extract_macro).
#  * A new run starts with no questions.txt, and a clean final
#    attempt deletes any earlier attempt's questions.txt, so a
#    stale file can never drive the banner.
_CODE_MARKERS = ("```", "import freecad", "partdesign", "import part",
                 "sketcher", "involutegear", "app.newdocument",
                 "body.newobject")


def _is_code_like(text):
    """True if text looks like FreeCAD code, not a question."""
    low = (text or "").lower()
    return any(m in low for m in _CODE_MARKERS)


def write_questions(output_dir, questions):
    """Write ONLY validated Q-lines to questions.txt.

    questions is [(label, text), ...] from extract_questions().
    A line is kept only if its label is Q<n>, its text is a single
    line, 1-500 chars, and contains no code marker. Anything else
    is dropped. When nothing valid remains, any existing
    questions.txt is DELETED (stale questions must not survive a
    clean attempt) and False is returned. Returns True iff a
    non-empty, validated questions.txt was written.
    """
    valid = []
    for label, text in (questions or []):
        if not re.fullmatch(r"Q\d+", label or ""):
            continue
        txt = (text or "").strip()
        if not txt or len(txt) > 500 or "\n" in txt or "\r" in txt:
            continue
        if _is_code_like(txt):
            continue
        valid.append((label, txt))
    path = Path(output_dir) / "questions.txt"
    if not valid:
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass
        return False
    path.write_text("\n".join(f"{label}: {text}" for label, text in valid)
                    + "\n", encoding="utf-8")
    return True


def run_freecadcmd(freecadcmd, macro_path, log_path):
    with open(log_path, "w", encoding="utf-8") as log_file:
        result = subprocess.run(
            [freecadcmd, str(macro_path)],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            timeout=1800,
        )
    return result.returncode



# ---- Diagnose -> category reference -> retry staging ----
# Total attempt budget. Attempt 1 is the first generation; attempts
# 2-4 are self-fixes. On the LAST attempt (4) all category files are
# attached as fallback, whatever the diagnosis says.
MAX_ATTEMPTS = 4

# Category -> reference file, relative to the orchestrator folder
# (this script's directory). Fixed interface: do not rename keys or
# move these paths without updating the parallel reference writer.
# gear reuses the existing GEAR_CREATION_REFERENCE.md; the other
# files live under references/ and may not exist yet when a retry
# runs -- load_reference_texts() skips a missing file gracefully
# (note, never crash) instead of failing the retry.
CATEGORY_REFERENCES = {
    "gear": "GEAR_CREATION_REFERENCE.md",
    "sketch_wire": "references/sketch_wire.md",
    "constraint_solver": "references/constraint_solver.md",
    "solid_pad": "references/solid_pad.md",
    "thread_tap": "references/thread_tap.md",
    "outline_curve": "references/outline_curve.md",
}
ALL_CATEGORIES = ["sketch_wire", "constraint_solver", "solid_pad",
                  "thread_tap", "outline_curve", "gear"]

# Cause-category keywords, checked in priority order. These match
# the DIAGNOSIS (cause), not a bare symptom word: e.g. "wire not
# closed" is a sketch_wire cause, while a solved coordinate that
# moved/flipped is a constraint_solver cause even when the visible
# symptom is also a bad wire. Order matters: gear/thread/outline
# causes are more specific than the generic pad/wire causes below.
_CATEGORY_RULES = [
    ("gear", ("involute", "gear tooth", "gear teeth", "tooth profile")),
    ("thread_tap", ("tap", "thread", "tap drill", "tap-drill",
                    "drill diameter")),
    ("outline_curve", ("spline", "b-spline", "bspline", "bezier",
                        "outline curve", "outline point", "curve fit")),
    ("sketch_wire", ("wire not closed", "wire is not closed",
                     "open wire", "not a closed wire", "unclosed wire",
                     "wire gap", "sketch not closed", "profile not closed",
                     "not closed")),
    ("constraint_solver", ("redundant constraint", "conflicting constraint",
                           "over-constrained", "over constrained",
                           "under-constrained", "under constrained",
                           "solver", "constraint", "moved", "drift",
                           "flipped", "distancex", "distancey",
                           "fully constrained")),
    ("solid_pad", ("pad", "pocket", "invalid solid", "multiple solids",
                   "null shape", "fusion", "fuse", "boolean",
                   "no solid", "empty solid")),
]


def clean_model_outputs(output_dir):
    """Delete model.fcstd/model.step before an attempt.

    Without this, verification after a failed attempt that saved
    nothing would read the PREVIOUS attempt's STEP and misattribute
    that old result to the new attempt. Returns the names deleted.
    Only the two model outputs are removed; logs, macros, raw
    responses, and self_fix_log.txt are preserved.
    """
    deleted = []
    for name in ("model.fcstd", "model.step"):
        path = Path(output_dir) / name
        try:
            if path.is_file():
                path.unlink()
                deleted.append(name)
        except OSError:
            pass
    return deleted


def inspect_fcstd_features(fcstd_path):
    """Best-effort feature list from a .fcstd file (stdlib only).

    A .fcstd is a zip; Document.xml inside lists objects with
    Name/Type attributes. Returns [(name, type), ...] or [] when
    the file is missing, unreadable, or has no parseable objects.
    Never raises: this is diagnostic context, not a gate.
    """
    try:
        import zipfile
        import xml.etree.ElementTree as ET
        with zipfile.ZipFile(str(fcstd_path)) as zf:
            xml_text = zf.read("Document.xml").decode("utf-8",
                                                      errors="replace")
        root = ET.fromstring(xml_text)
        out = []
        for obj in root.iter("Object"):
            name = obj.get("name") or obj.get("Name")
            typ = obj.get("type") or obj.get("Type")
            if name:
                out.append((name, typ or ""))
        return out
    except Exception:
        return []


def _first_match(patterns, text):
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match
    return None


def classify_diagnosis(diagnosis_text):
    """Map a diagnosis to one category, or None when unclear.

    Takes the full diagnosis text (cause hypothesis included), so
    the mapping keys off cause, not a single symptom word. Returns
    None when no rule matches: the caller then attaches the full
    reference set instead of guessing a category.
    """
    low = (diagnosis_text or "").lower()
    for category, keywords in _CATEGORY_RULES:
        if any(kw in low for kw in keywords):
            return category
    return None


# ---------------------------------------------------------------------------
# Feature history + per-feature volume gate (Oct 31, 2026, 140309 run).
# Root cause found in that run: the final STEP gate (solids==1, valid)
# passes even when a Pocket cuts air. check_feature() in the macro
# only checks solids/valid, so Flat / Recess / Bore / Tap-Clear
# pockets with volume delta exactly 0 still printed PASS, and the
# run was declared MODELING COMPLETE with no bore, no flat and no
# recess in the actual shape. The matching table then read the
# sketch diameter (intended value) and reported O for the bore.
#
# This gate is mechanical and drawing-independent: it parses the
# CHECK lines the macro already prints (feature, solids, valid,
# volume), computes the volume delta per feature in order, and
# verdicts each feature from that delta -- never from the LLM's
# own PASS claim. A Pocket must remove material, a Pad must add
# material. A 0-delta Pocket is a direction failure, full stop.
#
# The resulting records are written to feature_history.json and
# carried into the next attempt's prompt verbatim. That is the
# conversation-like history: OK features are locked (copy them
# exactly, do not re-guess them), FAIL features are changed only,
# and a direction that already gave delta 0 for a feature must
# never be repeated. If a feature later proves wrong, its verdict
# is flipped OK -> FAIL with a new reason; records are never
# silently overwritten, so the retry cannot oscillate.
#
# Limitation, stated plainly: a volume delta alone cannot catch a
# pocket that cuts the wrong place with the right volume (the
# 140309 tap threads cut outward with the same -24 mm^3 as the
# correct inward cut). That needs a STEP face-position check, which
# is NOT part of this change; volume + history is the first gate,
# not the whole drawing comparison.
# CHECK-line format is LLM-written and varies per macro, so the
# pattern must accept every format actually seen in home runs:
# "solids=1 valid=True vol=123.456" (140309 macro) AND
# "solids 1 valid True volume 123.456" (161949 / 163341 macros).
# A format-specific pattern silently parses 0 lines and the gate
# is skipped -- exactly what happened in the 161949 / 163341 runs,
# where the gate code was present but found no CHECK lines.
_CHECK_RE = re.compile(
    r"CHECK\s+(\S+)\s+solids[= ](\d+)\s+valid[= ](\w+)\s+"
    r"(?:vol|volume)[= ]([0-9.]+)")


def parse_check_lines(run_log_text):
    """Parse macro CHECK lines, first occurrence per feature, in order."""
    checks, seen = [], set()
    for match in _CHECK_RE.finditer(run_log_text or ""):
        name = match.group(1)
        if name in seen:
            continue
        seen.add(name)
        checks.append({
            "feature": name,
            "solids": int(match.group(2)),
            "valid": match.group(3) == "True",
            "volume": float(match.group(4)),
        })
    return checks


def evaluate_feature_history(checks):
    """Verdict each feature from its volume delta vs the previous one.

    Pad: delta must be > 0.01. Pocket: delta must be < -0.01.
    Chamfer: only validity gates it (a concave chamfer can legitimately
    add volume, so volume direction is not a gate for chamfers).
    Any other feature: solids==1 and valid.
    Returns records with volume_before, delta, verdict, reason.
    """
    records, prev_vol = [], 0.0
    for check in checks:
        vol, delta = check["volume"], check["volume"] - prev_vol
        prev_vol = vol
        name = check["feature"]
        if not check["valid"] or check["solids"] != 1:
            verdict, reason = "FAIL", "solids/valid check failed"
        elif name.startswith("Pad"):
            verdict = "OK" if delta > 0.01 else "FAIL"
            reason = ("" if verdict == "OK" else
                      "Pad volume did not increase - pad cut air or "
                      "sketch is not on material")
        elif name.startswith("Pocket"):
            verdict = "OK" if delta < -0.01 else "FAIL"
            reason = ("" if verdict == "OK" else
                      "Pocket volume unchanged (0-cut) - direction "
                      "likely reversed; flip Reversed for this Pocket "
                      "only, do not change its dimensions")
        elif name.startswith("Chamfer"):
            verdict = "OK" if check["valid"] else "FAIL"
            reason = ("" if verdict == "OK" else
                      "Chamfer made the solid invalid - drop this "
                      "Chamfer feature, do not keep an invalid solid "
                      "for a finishing chamfer")
        else:
            verdict, reason = "OK", ""
        records.append({
            "feature": name, "solids": check["solids"],
            "valid": check["valid"], "volume": vol,
            "volume_before": round(vol - delta, 4),
            "delta": round(delta, 4), "verdict": verdict,
            "reason": reason,
        })
    # Finishing-order gate: Chamfer/Fillet must be LAST. A Chamfer
    # followed by any later Pad/Pocket is a FAIL even when its own
    # volume delta looks fine -- in the 163341 run a mid-tree
    # Chamfer based on Pad_Body dropped the Pad_Ring boss from the
    # result (bbox X 15 -> 13.5) and every Pocket after it was
    # built on the wrong tip. Fillet/Round names are checked too.
    for i, rec in enumerate(records):
        if rec["feature"].startswith(("Chamfer", "Fillet", "Round")):
            later = [r["feature"] for r in records[i + 1:]
                     if r["feature"].startswith(("Pad", "Pocket"))]
            if later:
                rec["verdict"] = "FAIL"
                rec["reason"] = (
                    "Finishing operation must be LAST: this "
                    "Chamfer/Fillet appears before later Pad/Pocket "
                    f"features ({', '.join(later)}). Move all "
                    "Chamfer/Fillet features to the end of the tree, "
                    "after every Pad/Pocket, and base each one on "
                    "the immediately preceding feature (tip), never "
                    "on an earlier Pad/Pocket.")
    return records


def feature_history_report(records):
    """Compact one-line-per-feature history, for logs and prompts."""
    lines = []
    for rec in records:
        line = (f"{rec['feature']}: vol {rec['volume_before']} -> "
                f"{rec['volume']} delta {rec['delta']} "
                f"verdict {rec['verdict']}")
        if rec["reason"]:
            line += f" reason: {rec['reason']}"
        lines.append(line)
    return "\n".join(lines)


def build_diagnosis(run_log_text="", verification=None, last_error="",
                    fcstd_path=None):
    """Build a structured diagnosis from the ACTUAL artifact.

    Sources, in order: the failed attempt's freecadcmd log, its
    verification output, and (best-effort) the .fcstd feature list.
    Never from the error message alone: when the log carries no
    feature/geometry detail, those fields say so explicitly instead
    of inventing one. Returns a dict with a ready-to-log `report`
    string plus the individual fields and the selected `category`
    (or None when unclear).
    """
    log_text = run_log_text or ""
    combined = "\n".join([log_text, last_error or ""])
    if verification:
        combined += f"\nverification: {verification}"
    # Exact error: last log line mentioning an error/failure, else
    # the orchestrator's last_error (truncated, verbatim).
    exact_error = ""
    for line in reversed(log_text.splitlines()):
        if re.search(r"error|exception|failed|failure|traceback",
                     line, re.IGNORECASE):
            exact_error = line.strip()[:500]
            break
    if not exact_error:
        exact_error = (last_error or "no error text recorded")[:500]
    # Feature name: first recognisable feature token near an error
    # line, else the first feature token anywhere in the log.
    feature = "not identifiable from log"
    error_lines = [ln for ln in log_text.splitlines()
                   if re.search(r"error|exception|failed", ln,
                                re.IGNORECASE)]
    feature_match = _first_match(
        [r"\b(Sketch\w*|Pad\w*|Pocket\w*|Fillet\w*|Chamfer\w*|"
         r"InvoluteGear\w*|Thread\w*|Tap\w*)\b"],
        "\n".join(error_lines) or log_text)
    if feature_match:
        feature = feature_match.group(1)
    # Geometry index, if the log names one.
    geometry_index = "not identifiable from log"
    geo_match = re.search(
        r"(?:geometry|geoid|geo)[ _#]*(\d+)", combined, re.IGNORECASE)
    if geo_match:
        geometry_index = geo_match.group(1)
    # Gap size vs tolerance, only when numbers are actually present.
    gap = "not stated in log"
    gap_match = re.search(r"gap[^0-9]{0,30}([0-9]+(?:\.[0-9]+)?)\s*mm?",
                          combined, re.IGNORECASE)
    tol_match = re.search(r"tolerance[^0-9]{0,30}([0-9]+(?:\.[0-9]+)?)",
                          combined, re.IGNORECASE)
    if gap_match:
        gap = f"gap {gap_match.group(1)} mm"
        gap += (f" vs tolerance {tol_match.group(1)} mm"
                if tol_match else " vs tolerance not stated")
    elif verification and isinstance(verification, dict):
        gap = (f"verification: solids={verification.get('solids')}, "
               f"valid={verification.get('valid')} "
               f"(gate: solids==1 and valid True)")
    # Feature list from the partial .fcstd, when one survived.
    fcstd_note = ""
    if fcstd_path is not None and Path(fcstd_path).is_file():
        feats = inspect_fcstd_features(fcstd_path)
        if feats:
            fcstd_note = ("fcstd features: " +
                          ", ".join(f"{n} ({t})" for n, t in feats[:20]))
    # Cause hypothesis: category-driven, never a bare symptom repeat.
    cause_hypotheses = {
        "gear": "gear tooth profile / InvoluteGear setup cause",
        "thread_tap": "tap/thread tool or drill-diameter cause",
        "outline_curve": "outline curve / spline fitting cause",
        "sketch_wire": "sketch wire closure cause (open/unclosed wire)",
        "constraint_solver": "sketch constraint/solver cause "
                             "(redundant, conflicting, or drifted constraint)",
        "solid_pad": "pad/pocket/solid formation cause "
                     "(invalid, multiple, or null solid)",
    }
    category = classify_diagnosis(combined)
    if category:
        cause = cause_hypotheses[category]
    else:
        cause = ("unclear from log + verification - no single cause "
                 "category matched; full reference set attached")
    report = (
        "Diagnosis (from actual artifact, not error message alone):\n"
        f"- Feature: {feature}\n"
        f"- Geometry index: {geometry_index}\n"
        f"- Exact error: {exact_error}\n"
        f"- Gap size vs tolerance: {gap}\n"
        f"- Cause hypothesis: {cause}\n"
        + (f"- {fcstd_note}\n" if fcstd_note else "")
        + f"- Category: {category or 'unclear -> full set'}"
    )
    return {"feature": feature, "geometry_index": geometry_index,
            "exact_error": exact_error, "gap": gap,
            "cause_hypothesis": cause, "category": category,
            "report": report}


def load_reference_texts(categories, script_dir=None):
    """Load reference files for categories; skip missing gracefully.

    Returns (reference_block, notes): reference_block is the single
    clearly-marked "Reference" part for the prompt (empty string
    when every file is missing), notes lists one line per category
    for self_fix_log.txt. A missing file is never a crash and never
    blocks the retry -- the parallel reference writer may not have
    finished that file yet.
    """
    base = Path(script_dir) if script_dir else Path(__file__).resolve().parent
    blocks, notes = [], []
    for category in categories:
        rel = CATEGORY_REFERENCES.get(category)
        if rel is None:
            notes.append(f"Reference {category}: unknown category, skipped.")
            continue
        path = base / rel
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            notes.append(f"Reference {category}: missing ({rel}), skipped.")
            continue
        blocks.append(f"--- Reference: {category} ({rel}) ---\n{text.strip()}")
        notes.append(f"Reference {category}: attached ({rel}).")
    if not blocks:
        return "", notes
    block = ("Reference (diagnosis-matched, retry only - find the "
             "section matching the exact error, quote it, then apply "
             "it; do not invent a reference):\n\n" + "\n\n".join(blocks))
    return block, notes


def select_retry_categories(diagnosis, attempt):
    """Categories to attach on a retry attempt.

    Attempt MAX_ATTEMPTS always gets the full set as fallback. An
    earlier retry gets its single diagnosed category, or the full
    set when the diagnosis yields no clear category.
    """
    if attempt >= MAX_ATTEMPTS:
        return list(ALL_CATEGORIES)
    category = (diagnosis or {}).get("category")
    return [category] if category else list(ALL_CATEGORIES)



# ---- Drawing <-> modeling matching ----
# "Drawing value" here means: the value the LLM read from the drawing
# and wrote into the macro (or, for ask-first D-dimensions, the value
# the LLM listed). It is NOT an independently measured drawing truth:
# if the LLM misread the drawing, both columns can be wrong together.
# The table therefore checks build-vs-intent (did FreeCAD actually
# build what the macro said?), plus the user-confirmed Q&A values
# when they are present in --text. Tolerance: 0.01 mm.
# Matching rules (Oct 30, 2026): D-rows resolve via macro parameter
# (shared name token) first, then cylinder faces for dia/radius,
# then size X for total lengths only. Width/height words are never
# compared to whole-part bbox sizes (view-dependent, often local);
# without a macro parameter they show ?, never a bogus X. Reference
# dimensions show "? (참조치수)". D-lines may carry a [view] tag
# (front/section/side/top), stored in dimensions.json and shown in
# the table; view-aware measurement is future work, not bbox logic.
MATCH_TOL = 0.01


def _near_cyl(values, target):
    """Closest cylinder diameter, or None if no cylinder is near
    this size at all. A far-away 'closest' is not the same feature
    that differs: a 1.60 cylinder is not a 2.80 'diameter' that is
    wrong, it is simply no such cylinder, so it must be ? (not X).
    Threshold: within 25% of the target counts as the same feature.
    """
    if not values:
        return None
    c = min(values, key=lambda v: abs(v - target))
    if abs(c - target) > 0.25 * target:
        return None
    return c


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


def _dim_tokens(text):
    """Split a dimension label or parameter name into tokens."""
    parts = re.split(r"[^A-Za-z0-9]+", (text or "").upper())
    stop = {"THE", "OF", "A", "AN", "AND", "FOR", "AT", "ON", "TO", "BY"}
    return {p for p in parts if len(p) >= 2 and p not in stop}


# Words too generic to identify a feature by themselves: "left" is
# shared by an offset and a tip height, "height" by a section height
# and a base height. A shared generic word plus a DIFFERENT value
# is not a match at all (that bug matched offsets to tip heights).
_GENERIC_TOKENS = {"WIDTH", "HEIGHT", "LENGTH", "DEPTH", "THICK",
                   "SIZE", "DIA", "DIAMETER", "RADIUS", "TOP", "BOTTOM",
                   "UPPER", "LOWER", "LEFT", "RIGHT", "FRONT", "BACK",
                   "SIDE", "SECTION", "PART", "OVERALL", "TOTAL",
                   "FIRST", "SECOND", "MIDDLE", "CENTER", "CENTRE",
                   "VIEW"}


def _find_macro_param(label, value, macro_params):
    """Find the macro parameter most likely to be this dimension.

    Returns (name, param_value) or None, in two tiers:
    - Strong: a shared SPECIFIC token (e.g. SLOT, TIP, CROWN).
      The parameter IS the feature, so a differing value is an
      honest X (found, wrong size). Closest strong value wins.
    - Weak: only generic tokens shared, but the value agrees within
      tolerance. Treated as the same feature (O); a generic word
      plus a different value is never evidence, so weak matches
      can only produce O, never X.
    A coincidental equal value with no shared token never matches.
    """
    lt = _dim_tokens(label)
    strong = lt - _GENERIC_TOKENS
    best_strong = None
    best_weak = None
    for name, pvalue in macro_params:
        nt = _dim_tokens(name)
        diff = abs(pvalue - value)
        if strong & nt:
            if best_strong is None or diff < best_strong[2]:
                best_strong = (name, pvalue, diff)
        elif (lt & nt) and diff <= MATCH_TOL + 1e-9:
            if best_weak is None or diff < best_weak[2]:
                best_weak = (name, pvalue, diff)
    if best_strong is not None:
        return best_strong[:2]
    if best_weak is not None:
        return best_weak[:2]
    return None


def _is_reference_dim(d):
    if d.get("reference"):
        return True
    label = d.get("label", "")
    return "REFERENCE" in label.upper() or "참조" in label


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


_VIEW_ALIASES = {"FRONT": "front", "SECTION": "section", "SIDE": "side",
                 "TOP": "top", "정면": "front", "단면": "section",
                 "측면": "side", "평면": "top"}


def parse_numbered_dimensions(text):
    """Parse ask-first / answer D-lines:
    D1: label = value mm @ (x, y) [view].

    Position (x, y) is a 0-1 image fraction, origin top-left, and is
    APPROXIMATE (LLM vision estimate). The [view] tag (front /
    section / side / top) is optional; old lines without it still
    parse with view None. A value in parentheses, e.g. = (1.97) mm,
    is a reference dimension (non-driving) and sets reference True.
    Returns a list of dicts.
    """
    dims = []
    for line in text.splitlines():
        m = re.match(r"\s*(?:#\s*)?D(\d+)\s*[:\-\.]\s*(.+)", line.strip())
        if not m:
            continue
        rest = m.group(2).strip()
        view = None
        vm_view = re.search(
            r"\[\s*(front|section|side|top|정면|단면|측면|평면)\s*\]",
            rest, re.IGNORECASE)
        if vm_view:
            view = _VIEW_ALIASES.get(vm_view.group(1).upper(),
                                     vm_view.group(1).lower())
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
        reference = vm.start() > 0 and rest[vm.start() - 1] == "("
        label = rest[:vm.start()].strip()
        if label.endswith("("):
            label = label[:-1].strip()
        label = label.strip(" =:") or f"D{m.group(1)}"
        if "REFERENCE" in label.upper() or "참조" in label:
            reference = True
        dims.append({"id": f"D{m.group(1)}", "label": label,
                     "value": value, "x": pos[0] if pos else None,
                     "y": pos[1] if pos else None,
                     "view": view, "reference": reference})
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


def _features_by_name(features_data):
    """features.json -> {feature name: record} (empty dict if unusable)."""
    if isinstance(features_data, dict):
        items = features_data.get("features") or []
    elif isinstance(features_data, list):
        items = features_data
    else:
        items = []
    return {f.get("name"): f for f in items if isinstance(f, dict)
            and f.get("name")}


def _region_cut(faces, view, region):
    """Single-axis region rule -> (axis_index, threshold, keep_below).

    Returns None when no region/view applies. Axes: front (X-Z),
    side (Y-Z), top/section (X-Y). left/right/top/bottom =
    half-split by face-center mean; leftmost/rightmost/topmost/
    bottommost = outer-quarter band of the face bbox range.
    keep_below True means keep coords < threshold, else >.
    """
    if not region or not view:
        return None
    axes = {"front": ("x", "z"), "side": ("y", "z"),
            "top": ("x", "y"), "section": ("x", "y")}
    if view not in axes:
        return None
    h_axis, v_axis = axes[view]
    hi = {"x": 0, "y": 1, "z": 2}[h_axis]
    vi = {"x": 0, "y": 1, "z": 2}[v_axis]
    usable = [f for f in faces if f.get("center")]
    if not usable:
        return None
    if region in ("left", "right", "top", "bottom"):
        mh = sum(f["center"][hi] for f in usable) / len(usable)
        mv = sum(f["center"][vi] for f in usable) / len(usable)
        if region == "left":
            return (hi, mh, True)
        if region == "right":
            return (hi, mh, False)
        if region == "bottom":
            return (vi, mv, True)
        return (vi, mv, False)
    if region in ("leftmost", "rightmost", "topmost", "bottommost"):
        bboxes = [f["bbox"] for f in usable if f.get("bbox")]
        if not bboxes:
            return None
        if region in ("leftmost", "rightmost"):
            lo = min(b[h_axis][0] for b in bboxes)
            hi_v = max(b[h_axis][1] for b in bboxes)
            if region == "leftmost":
                return (hi, lo + 0.25 * (hi_v - lo), True)
            return (hi, hi_v - 0.25 * (hi_v - lo), False)
        lo = min(b[v_axis][0] for b in bboxes)
        hi_v = max(b[v_axis][1] for b in bboxes)
        if region == "topmost":
            return (vi, hi_v - 0.25 * (hi_v - lo), False)
        return (vi, lo + 0.25 * (hi_v - lo), True)
    return None


def _region_filter_faces(faces, view, region):
    """Split a feature's faces by view-plane centroid vs feature extent.

    No view or no region -> unfiltered. Faces without a center are
    dropped when filtering.
    """
    cut = _region_cut(faces, view, region)
    if cut is None:
        return faces
    ai, thr, below = cut
    usable = [f for f in faces if f.get("center")]
    if below:
        return [f for f in usable if f["center"][ai] < thr]
    return [f for f in usable if f["center"][ai] > thr]


def _region_filter_points(points, faces, view, region):
    """Filter 3D points by the same region rule as faces.

    The cut is computed from the feature's faces (the region is
    defined on the whole feature), then applied to point coords.
    """
    cut = _region_cut(faces, view, region)
    if cut is None:
        return points
    ai, thr, below = cut
    if below:
        return [pt for pt in points if pt[ai] < thr]
    return [pt for pt in points if pt[ai] > thr]


def resolve_mapping_value(d_id, entry, by_name):
    """Read one dimension's modeling value from the .fcstd dump.

    Returns (value_or_None, method_string). Value None means
    "cannot be read" -> ? row, never a guessed number. Only the
    mapped feature's own data is used: no macro-text hunting, no
    whole-part bbox, no cylinder competition.
    """
    if not isinstance(entry, dict):
        return None, "mapping entry not a dict"
    fname = entry.get("feature")
    if not fname:
        return None, "mapping has no feature"
    feat = by_name.get(fname)
    if feat is None:
        return None, f"feature {fname} not found in .fcstd"
    kind = (entry.get("kind") or "").strip()
    faces = feat.get("created_faces") or []
    if kind == "pad_length":
        v = feat.get("length")
        if v is not None:
            return float(v), f"{fname} Length"
        return None, f"{fname} has no Length"
    if kind == "chamfer_size":
        v = feat.get("size")
        if v is not None:
            return float(v), f"{fname} Size"
        return None, f"{fname} has no Size"
    if kind in ("diameter", "radius"):
        sel = _region_filter_faces(faces, entry.get("view"),
                                   entry.get("region"))
        diams = sorted({round(2 * f["radius"], 4) for f in sel
                        if f.get("radius") is not None})
        if len(diams) == 1:
            d = diams[0]
            if kind == "diameter":
                return d, f"{fname} cylinder diameter"
            return round(d / 2, 4), f"{fname} cylinder radius"
        return None, (f"{fname}: {len(diams)} cylinder diameters "
                      "(ambiguous)")
    if kind == "sketch_constraint":
        sk_name = entry.get("sketch") or feat.get("sketch")
        sk = by_name.get(sk_name) if sk_name else None
        if sk is None:
            return None, f"sketch {sk_name} not found in .fcstd"
        for c in sk.get("constraints", []):
            if c.get("name") == d_id:
                v = c.get("value")
                if v is not None:
                    return float(v), f"{sk_name} constraint {d_id}"
                return None, f"{sk_name} constraint {d_id} has no value"
        return None, f"{sk_name} has no constraint named {d_id}"
    if kind == "feature_extent":
        axis = (entry.get("axis") or "").upper()
        if axis not in ("X", "Y", "Z"):
            return None, "feature_extent needs axis X/Y/Z"
        key = axis.lower()
        sel = _region_filter_faces(faces, entry.get("view"),
                                   entry.get("region"))
        vals = [f["bbox"][key] for f in sel if f.get("bbox")]
        if not vals:
            return None, f"{fname}: no faces for extent {axis}"
        lo = min(v[0] for v in vals)
        hi = max(v[1] for v in vals)
        return round(hi - lo, 4), f"{fname} extent {axis}"
    if kind == "span":
        axis = (entry.get("axis") or "").upper()
        if axis not in ("X", "Y", "Z"):
            axis = {"front": "Z", "side": "Z", "top": "Y",
                    "section": "Y"}.get(entry.get("view"), "Z")
        key = axis.lower()
        sel = _region_filter_faces(faces, entry.get("view"),
                                   entry.get("region"))
        extremum = (entry.get("extremum") or "max").lower()
        top = None
        if entry.get("localmin"):
            # Hook-tip dip: lowest interior local minimum of the
            # feature's ORDERED curve samples in the region. A
            # band min/max would catch the band edge (where the
            # curve enters the band), not the dip; unordered
            # tessellation vertices cannot tell them apart.
            cands = []
            ai3 = {"X": 0, "Y": 1, "Z": 2}[axis]
            for f in sel:
                pts = _region_filter_points(f.get("curve") or [],
                                            faces, entry.get("view"),
                                            entry.get("region"))
                for i in range(1, len(pts) - 1):
                    a = pts[i][ai3]
                    if a <= pts[i-1][ai3] and a <= pts[i+1][ai3] and \
                            (a < pts[i-1][ai3] or a < pts[i+1][ai3]):
                        cands.append(a)
            if cands:
                top = min(cands)
            else:
                return None, f"{fname}: no local minimum in region"
        if top is None:
            vals = [f["bbox"][key] for f in sel if f.get("bbox")]
            if not vals:
                return None, f"{fname}: no faces for span {axis}"
            top = (max(v[1] for v in vals) if extremum != "min"
                   else min(v[0] for v in vals))
        datum = entry.get("datum")
        if not datum or "." not in str(datum):
            return None, "span needs datum '<Feature>.top|.bottom'"
        dfeat_name, dside = str(datum).rsplit(".", 1)
        dfeat = by_name.get(dfeat_name)
        if dfeat is None:
            return None, f"datum feature {dfeat_name} not found"
        dvals = [f["bbox"][key] for f in (dfeat.get("created_faces") or [])
                 if f.get("bbox")]
        if not dvals:
            return None, f"datum feature {dfeat_name} has no faces"
        if dside == "top":
            dval = max(v[1] for v in dvals)
        elif dside == "bottom":
            dval = min(v[0] for v in dvals)
        else:
            return None, f"datum side must be .top or .bottom, got {datum}"
        return round(top - dval, 4), f"{fname} span {axis} from {datum}"
    return None, f"unknown kind {kind!r}"


def _always_rows(verification):
    """Always-present rows (solids, valid, bbox, cylinders, volume)."""
    rows = []
    rows.append(_match_row("—", "Solids (count)", 1,
                           verification.get("solids")))
    rows.append(_match_row("—", "Valid solid", True,
                           verification.get("valid")))
    for label, key in (("BBox size X", "size_x"), ("BBox size Y", "size_y"),
                       ("BBox size Z", "size_z")):
        rows.append(_match_row("—", label, None, verification.get(key)))
    cyl = verification.get("cyl_diams", [])
    rows.append(_match_row("—", "Cylinder diameters found", None,
                           ", ".join(f"{v:.2f}" for v in cyl) if cyl else None))
    rows.append(_match_row("—", "Volume (reference only)", None,
                           verification.get("volume")))
    return rows


def _feature_candidate_values(feat, by_name):
    """All modeling values one solid feature can supply, for the
    value-uniqueness inference fallback (step 3 of the modeling
    order). Sources: Length, Size, created-face cylinder diameters,
    created-face extents per axis, and its sketch's circle
    diameters. Sketches are merged into their solid feature, never
    counted as a separate feature, so a sketch circle and the
    solid's cylinder of the same size do not create a false
    ambiguity."""
    vals = []
    if feat.get("length") is not None:
        vals.append((float(feat["length"]), "Length"))
    if feat.get("size") is not None:
        vals.append((float(feat["size"]), "Size"))
    faces = feat.get("created_faces") or []
    for fc in faces:
        if fc.get("radius") is not None:
            vals.append((round(2 * fc["radius"], 4),
                         "cylinder diameter"))
    for ax in ("x", "y", "z"):
        rngs = [fc["bbox"][ax] for fc in faces
                if fc.get("bbox") and fc["bbox"].get(ax)]
        if rngs:
            vals.append((round(max(v[1] for v in rngs)
                               - min(v[0] for v in rngs), 4),
                         f"extent {ax.upper()}"))
    sk_name = feat.get("sketch")
    if isinstance(sk_name, str):
        sk = by_name.get(sk_name)
        if sk:
            for g in sk.get("geometry") or []:
                if g.get("type") == "Circle" \
                        and g.get("radius") is not None:
                    vals.append((round(2 * g["radius"], 4),
                                 "sketch circle diameter"))
    return vals


def infer_unique_modeling_value(d_value, features):
    """Step 3 (inference) of the modeling order, deterministic.

    Returns (value, method) when EXACTLY ONE solid feature in the
    .fcstd dump has a candidate value within MATCH_TOL of the
    drawing value, else (None, None). One hit per feature: a
    feature that supplies the value several ways still counts
    once. Ambiguous values (1.5 in both Pad_Boss and
    Pocket_Recess; 7.93 in Pocket_Bore and the tap pockets) stay
    blank -- those are what the Q&A step (step 2) must resolve
    by feature name, because value alone cannot tell them apart
    and a value-picked row could hide a wrong feature (a boss
    built 2.0 with a recess at 1.5 would otherwise read O).
    The method string is labelled "inferred", never "anchored".
    """
    by_name = _features_by_name(features)
    hits = []
    for name, feat in by_name.items():
        if feat.get("type") == "Sketcher::SketchObject":
            continue
        if not feat.get("created_faces") \
                and feat.get("length") is None \
                and feat.get("size") is None:
            continue
        for v, src in _feature_candidate_values(feat, by_name):
            if abs(v - d_value) <= MATCH_TOL:
                hits.append((name, v, src))
                break
    if len(hits) == 1:
        name, v, src = hits[0]
        return v, (f"inferred: {name} {src} "
                   f"(unique value match)")
    return None, None


def build_matching(verification, macro_text, user_text, mapping=None,
                   features=None):
    """Build the drawing-vs-modeling table rows.

    Two paths. When mapping is not None (a FEATURE_MAP dict, possibly
    empty), the mapping path runs: each D-row is read from the .fcstd
    feature dump ONLY (resolve_mapping_value); a D-row with no
    mapping entry, a missing feature, or an unreadable kind shows ?.
    Macro-text hunting, whole-part bbox rules, and cylinder
    competition are NOT used on this path. When mapping is None
    (old folders without mapping.json), the legacy path below runs
    unchanged, so old tables are never downgraded by a refresh.

    Row order: D-dimensions (ask-first / answer text) first, then
    macro parameters not already covered, then always-present rows
    (solids, valid, bbox sizes, cylinder diameters, volume).

    Legacy resolution order per D-row (first hit wins):
    1. Reference dimension -> "? (참조치수)" (non-driving, never X).
    2. Macro parameter, two tiers (see _find_macro_param): a shared
       specific word makes it the feature (O/X by tolerance); a
       shared generic word plus an agreeing value makes it O only.
    3. Diameter/radius -> STEP cylinder faces, but only if a
       cylinder near that size exists at all (else ?).
    4. Total/overall/axial length -> whole-part size X.
    5. Anything else -> ?. Width/height words are deliberately NOT
       compared to whole-part bbox sizes: they are view-dependent
       and often local (a tip height, a slot width), and comparing
       them to a bbox size produced the bogus-X table. A row whose
       comparison is itself invalid shows ?, never X.
    """
    if mapping is not None:
        by_name = _features_by_name(features)
        rows = []
        for d in parse_numbered_dimensions(user_text or ""):
            item = d["label"]
            if d.get("view"):
                item = f"{item} [{d['view']}]"
            if _is_reference_dim(d):
                rows.append({"no": d["id"], "item": item,
                             "drawing": d["value"], "modeling": None,
                             "result": "? (참조치수)",
                             "view": d.get("view")})
                continue
            entry = mapping.get(d["id"])
            _is_note_row = ("NOTE" in d["label"].upper()
                            or "TOLERANCE" in d["label"].upper()
                            or "GENERAL CHAMFER" in d["label"].upper())
            if entry is None and _is_note_row:
                rows.append({"no": d["id"], "item": item,
                             "drawing": d["value"], "modeling": None,
                             "result": "?", "view": d.get("view"),
                             "modeling_method": "NOTE row (rule, not geometry)"})
                continue
            if entry is None:
                # Step 3 (inference): anchored is absent, so a
                # unique value match may fill the row, labelled.
                iv, im = infer_unique_modeling_value(d["value"],
                                                     features)
                if iv is not None:
                    row = _match_row(d["id"], item, d["value"], iv)
                    row["view"] = d.get("view")
                    row["modeling_method"] = im
                    rows.append(row)
                    continue
                rows.append({"no": d["id"], "item": item,
                             "drawing": d["value"], "modeling": None,
                             "result": "?", "view": d.get("view"),
                             "modeling_method": "no FEATURE_MAP entry"})
                continue
            value, method = resolve_mapping_value(d["id"], entry, by_name)
            if value is None and not _is_note_row:
                # Anchored entry exists but does not resolve
                # (e.g. a multi-diameter feature): inference may
                # still fill it when the value is unique across
                # features. An anchored X is never overridden --
                # inference only runs when anchored gives nothing.
                iv, im = infer_unique_modeling_value(d["value"],
                                                     features)
                if iv is not None:
                    value, method = iv, im
            row = _match_row(d["id"], item, d["value"], value)
            row["view"] = d.get("view")
            row["modeling_method"] = method
            rows.append(row)
        rows.extend(_always_rows(verification))
        return rows
    rows = []
    used_macro = set()
    macro_params = parse_macro_dimensions(macro_text)
    # D-dimensions from --text (ask-first list carried via /answer,
    # or user notes written in D1: form).
    d_dims = parse_numbered_dimensions(user_text or "")
    for d in d_dims:
        item = d["label"]
        if d.get("view"):
            item = f"{item} [{d['view']}]"
        if _is_reference_dim(d):
            rows.append({"no": d["id"], "item": item,
                         "drawing": d["value"], "modeling": None,
                         "result": "? (참조치수)", "view": d.get("view")})
            continue
        pm = _find_macro_param(d["label"], d["value"], macro_params)
        if pm is not None:
            used_macro.add(pm[0])
            row = _match_row(d["id"], item, d["value"], pm[1])
            row["view"] = d.get("view")
            rows.append(row)
            continue
        kind = _keyword_target(d["label"])
        modeling = None
        if kind == "dia":
            modeling = _near_cyl(verification.get("cyl_diams", []),
                                 d["value"])
        elif kind == "radius":
            c = _near_cyl(verification.get("cyl_diams", []),
                          d["value"] * 2)
            modeling = (c / 2) if c is not None else None
        elif kind == "length":
            u = d["label"].upper()
            if "TOTAL" in u or "OVERALL" in u or "AXIAL" in u:
                modeling = verification.get("size_x")
        row = _match_row(d["id"], item, d["value"], modeling)
        row["view"] = d.get("view")
        rows.append(row)
    # Macro parameters.
    for name, value in macro_params:
        if name in used_macro:
            continue
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
        if kind == "dia":
            modeling = _near_cyl(verification.get("cyl_diams", []), value)
        elif kind == "radius":
            c = _near_cyl(verification.get("cyl_diams", []), value * 2)
            modeling = (c / 2) if c is not None else None
        elif kind == "length":
            u = name.upper()
            if "TOTAL" in u or "OVERALL" in u or "AXIAL" in u:
                modeling = verification.get("size_x")
            else:
                continue  # local length: not bbox-comparable
        else:  # width/height: view-dependent/local, not bbox-comparable
            continue
        rows.append(_match_row("—", name, value, modeling))
    # Always-present rows.
    rows.extend(_always_rows(verification))
    return rows


def _preferred_axis(label, kind, view):
    """(Preferred axis, restricted?) for a measurement.

    Depth/thickness words always mean the out-of-front-plane axis
    (Y). Otherwise the view decides (front: width X, height Z;
    side: width Y, height Z; top: width X, height Y). Section views
    have an unknown cutting plane, so no restriction (kind-only
    fallback axis is used for ranking only). Flats and unknown
    kinds get no preference. Restricted rows only accept candidates
    on the preferred axis or axis-free/angled ones; other axes are
    excluded outright, because a height measured as an X distance
    (a parallel-face coincidence) is not a measurement of it.
    """
    u = (label or "").upper()
    if "DEPTH" in u or "THICK" in u:
        return "Y", True
    view_map = {"front": {"width": "X", "height": "Z", "length": "X"},
                "side": {"width": "Y", "height": "Z", "length": "X"},
                "top": {"width": "X", "height": "Y", "length": "X"}}
    if view in view_map and kind in view_map[view]:
        return view_map[view][kind], True
    return {"height": "Z", "width": "X", "length": "X"}.get(kind), False


def match_measured(label, value, view, measurements):
    """Match one D-row to the real-measurement battery.

    Returns (measured_value, method) or (None, None). The measured
    column shows the VALUE only, no verdict: the user judges it
    against the drawing value (general tolerance ±0.1, not the
    strict 0.01 table tolerance).
    - Diameter/radius rows use cylinder faces only.
    - Every other size row also lets cylinder diameters compete
      on closeness (tight 0.05 band, axis-free): a width of a
      round feature IS its diameter, and without this an axial
      length or a position won instead (14.5 for a 16 step,
      9.5 for a 10 boss). Diameter only, never radius: a flat
      0.75 must not match a 1.50 cylinder halved.
    - Offset/position/tolerance rows are not measured in v1:
      they are positions, not sizes.
    - Every other size row takes the best battery value (face
      distances, edge lengths, vertex deltas, section extents).
      Rows with a view-determined axis (front/side/top, or
      depth/thickness words) only accept candidates on that axis
      or axis-free/angled ones; other axes are excluded outright,
      because a height measured as an X distance (a parallel-face
      coincidence) is not a measurement of it. Within the allowed
      set, ranking is axis first, then closeness, but only within
      each pool's band: axis-aligned face, section, and bbox values
      use max(0.1, 10% of value); exact or numerous values (edges,
      vertex deltas, angled face pairs) use 0.05, because dense
      pools "find" coincidences under a loose band (a
      peak-minus-slot-end delta posing as a tip height, an angled
      face pair 1.049 posing as a 0.97 height), while genuine
      dimensions agree closely (peak height 1.739 vs 1.70 is
      within 0.05).
    The method string says what was measured, so any remaining
    wrong-axis coincidence stays visible.
    """
    if not measurements:
        return None, None
    u = (label or "").upper()
    if ("OFFSET" in u or "POSITION" in u or "TOLERANCE" in u
            or "PARALLEL" in u or "//" in label):
        return None, None
    kind = _keyword_target(label)
    if kind == "dia":
        c = _near_cyl(measurements.get("cyl_diams", []), value)
        return (c, "cylinder diameter") if c is not None else (None, None)
    if kind == "radius":
        c = _near_cyl(measurements.get("cyl_diams", []), value * 2)
        return (c / 2, "cylinder radius") if c is not None else (None, None)
    pref, restricted = _preferred_axis(label, kind, view)

    def rank(axis):
        if pref is None or axis is None or axis == "angled":
            return 1
        if axis == pref:
            return 0
        return 2

    def allowed(axis):
        # Restricted rows: only the preferred axis, plus axis-free
        # and angled candidates (a slot's width is measured
        # perpendicular to the slot, so angled faces/edges stay).
        if not restricted:
            return True
        return axis is None or axis == "angled" or axis == pref

    wide_band = max(0.1, 0.1 * value)
    exact_band = 0.05  # exact CAD values (edges, vertex deltas)
    cands = []
    for d in measurements.get("face_distances", []):
        axis = d.get("axis")
        ax = None if axis == "angled" else axis
        if allowed(ax):
            # Angled pairs are numerous (slot/diagonal faces at odd
            # angles), so they get the tight band like exact values;
            # axis-aligned pairs are few and keep the wide band.
            band = exact_band if axis == "angled" else wide_band
            cands.append((d["value"], f"parallel faces ({axis or '?'})",
                          rank(ax), band))
    for e in measurements.get("edge_lengths", []):
        axis = e.get("axis")
        ax = None if axis == "angled" else axis
        if allowed(ax):
            cands.append((e["value"], f"edge length ({axis or '?'})",
                          rank(ax), exact_band))
    for axis, diffs in (measurements.get("vertex_deltas") or {}).items():
        if allowed(axis):
            for diff in diffs:
                cands.append((diff, f"vertex Δ{axis}", rank(axis),
                              exact_band))
    for s in measurements.get("sections", []):
        if allowed("X"):
            cands.append((s["x_extent"],
                          f"section X extent @ z={s['z']}",
                          rank("X"), wide_band))
        if allowed("Y"):
            cands.append((s["y_extent"],
                          f"section Y extent @ z={s['z']}",
                          rank("Y"), wide_band))
    for axis, ext in (measurements.get("bbox_extents") or {}).items():
        if allowed(axis):
            cands.append((ext, f"bbox {axis} extent", rank(axis),
                          wide_band))
    # Cylinder diameters also compete for non-dia rows: a "width"
    # of a round feature IS its diameter (gear step dia 16, boss
    # dia 10), but width rows skip the dia route above, so an
    # axial length (14.5) or a position (9.5) won by closeness
    # instead. Cylinders are axis-free (rank 1) with the tight
    # exact band: a diameter is an exact CAD value, and a loose
    # band would let a near cylinder pose as an unrelated size.
    # Diameter only, never radius: a flat 0.75 must not match a
    # 1.50 cylinder halved. Appended last, so on an exact tie an
    # existing pool wins and the value/verdict stay put.
    for c in sorted(set(measurements.get("cyl_diams", []))):
        cands.append((c, "cylinder diameter", 1, exact_band))
    if not cands:
        return None, None
    # Rank within bands, in two tiers: preferred-axis and
    # angled/axis-free candidates compete on closeness alone (an
    # exact angled slot width beats a near X distance), while
    # other-axis candidates only win if tier A is empty (a
    # Z height beats an exact X coincidence). Filtering to the
    # bands first matters: a far-away preferred-axis value must
    # never beat an exact angled face.
    near = [c for c in cands if abs(c[0] - value) <= c[3] + 1e-9]
    if not near:
        return None, None
    best = min(near, key=lambda c: (0 if c[2] in (0, 1) else 1,
                                    abs(c[0] - value)))
    return best[0], best[1]


def attribute_step_faces(features_data, step_faces):
    """Match final-STEP faces to .fcstd features' created faces.

    Returns {feature_name: [step_face_index, ...]}. A STEP face
    matches a created face when: same surface type, center within
    0.01 mm, area within 1% (or 0.01 abs), and for cylinders radius
    within 0.001, for planes normals parallel (|dot| > 0.999).
    Features claim in REVERSE tree order (latest creator first),
    each STEP face claimed at most once, best center distance
    wins. A created face that vanished from the final shape (fused
    away, e.g. a step back face buried by the body) simply matches
    nothing, which is the honest answer for it.
    """
    items = [(f.get("name"), f) for f in
             (features_data.get("features") if isinstance(features_data,
                                                          dict) else [])
             if isinstance(f, dict) and f.get("name")]
    claimed = set()
    attribution = {}
    for fname, feat in reversed(items):
        got = []
        for created in feat.get("created_faces") or []:
            cc = created.get("center")
            if cc is None:
                continue
            best = None
            for si, sf in enumerate(step_faces):
                if si in claimed:
                    continue
                if sf.get("type") != created.get("type"):
                    continue
                sc = sf.get("center")
                if sc is None:
                    continue
                dist = ((sc[0] - cc[0]) ** 2 + (sc[1] - cc[1]) ** 2
                        + (sc[2] - cc[2]) ** 2) ** 0.5
                if dist > 0.01:
                    continue
                ca, sa = created.get("area"), sf.get("area")
                if ca is None or sa is None:
                    continue
                if abs(ca - sa) > max(0.01, 0.01 * abs(ca)):
                    continue
                if created.get("type") == "Cylinder":
                    cr, sr = created.get("radius"), sf.get("radius")
                    if cr is None or sr is None or abs(cr - sr) > 0.001:
                        continue
                elif created.get("type") == "Plane":
                    cn, sn = created.get("normal"), sf.get("normal")
                    if cn is None or sn is None:
                        continue
                    dot = abs(sum(cn[i] * sn[i] for i in range(3)))
                    if dot < 0.999:
                        continue
                if best is None or dist < best[0]:
                    best = (dist, si)
            if best is not None:
                claimed.add(best[1])
                got.append(best[1])
        if got:
            attribution[fname] = got
    return attribution


def _attributed_faces(fname, attribution, step_faces):
    idxs = attribution.get(fname) or []
    return [step_faces[i] for i in idxs if 0 <= i < len(step_faces)]


def measure_anchored(d_id, entry, by_name, attribution, step_faces):
    """Measure one dimension on the STEP file via its mapped feature.

    Returns (value_or_None, method_string). The method names the
    feature and the rule, so every measured value is auditable.
    Value None means "cannot be measured this way" -> ? (never a
    battery guess). Only the mapped feature's attributed STEP faces
    are used: no value-proximity competition across the part.
    """
    if not isinstance(entry, dict):
        return None, "mapping entry not a dict"
    fname = entry.get("feature")
    if not fname:
        return None, "mapping has no feature"
    feat = by_name.get(fname)
    if feat is None:
        return None, f"feature {fname} not found in .fcstd"
    faces = _attributed_faces(fname, attribution, step_faces)
    kind = (entry.get("kind") or "").strip()
    # NOTE: no global "no attributed faces" return here. Relocation
    # kinds (diameter/radius/pad_length/chamfer_size) read the
    # feature's own created data + the full STEP face list, so they
    # work even when attribution is empty (trimmed/merged faces).
    # Attributed-only kinds (extent/span/sketch_constraint) check
    # for empty faces in their own branches.
    if kind in ("diameter", "radius"):
        # Relocation, like pad_length end planes: a later feature
        # may trim the feature's cylinder (body side cut by the
        # chamfer), so attribution by area can lose it -- but a
        # cylinder of the radius this feature was built with still
        # exists in the STEP. The radii come from the feature's
        # own created faces, never from the drawing value, so this
        # is not bag-picking. Region filter applies first when the
        # entry names one (e.g. left R0.75 vs right R0.8 arcs).
        sel = _region_filter_faces(feat.get("created_faces") or [],
                                   entry.get("view"),
                                   entry.get("region"))
        radii = {round(f["radius"], 4) for f in sel
                 if f.get("radius") is not None}
        if not radii:
            return None, f"{fname}: no cylinder radii in created faces"
        step_sel = _region_filter_faces(step_faces, entry.get("view"),
                                        entry.get("region"))
        diams = sorted({round(2 * f["radius"], 4) for f in step_sel
                        if f.get("radius") is not None
                        and any(abs(f["radius"] - r) < 0.001
                                for r in radii)})
        if len(diams) == 1:
            d = diams[0]
            if kind == "diameter":
                return d, f"{fname} cylinder diameter"
            return round(d / 2, 4), f"{fname} cylinder radius"
        return None, (f"{fname}: {len(diams)} cylinder diameters "
                      "for its radii (ambiguous)")
    if kind == "pad_length":
        normal = feat.get("sketch_normal")
        if not normal:
            return None, f"{fname}: no sketch normal"
        ai = max(range(3), key=lambda i: abs(normal[i]))
        if abs(normal[ai]) < 0.9:
            return None, f"{fname}: sketch normal not axis-aligned"
        axis = "XYZ"[ai]
        # End planes: the feature's OWN created planes (from
        # .fcstd) relocated in the STEP. A later feature may trim
        # an end plane (recess ring cut from the body back, crown
        # root fused into the base), changing its area, so
        # attribution by area can lose it -- but the plane itself
        # (same normal + offset) still exists in the STEP,
        # possibly under another feature's name. Relocation finds
        # it by offset, not by owner: the offsets are the
        # feature's own, so this is not bag-picking.
        created_offsets = sorted({round(f["center"][ai], 3)
                                  for f in feat.get("created_faces", [])
                                  if f.get("type") == "Plane"
                                  and f.get("normal")
                                  and abs(f["normal"][ai]) > 0.999
                                  and f.get("center")})
        if len(created_offsets) < 2:
            return None, (f"{fname}: {len(created_offsets)} end "
                          "planes (need 2)")
        lo, hi = created_offsets[0], created_offsets[-1]
        missing = [t for t in (lo, hi)
                   if not any(sf.get("type") == "Plane"
                              and sf.get("normal")
                              and abs(sf["normal"][ai]) > 0.999
                              and sf.get("center")
                              and abs(sf["center"][ai] - t) < 0.01
                              for sf in step_faces)]
        if missing:
            return None, f"{fname}: end plane {missing[0]} missing in STEP"
        return round(hi - lo, 4), f"{fname} end planes ({axis})"
    if kind == "feature_extent":
        if not faces:
            return None, f"no STEP faces attributed to {fname}"
        axis = (entry.get("axis") or "").upper()
        if axis not in ("X", "Y", "Z"):
            return None, "feature_extent needs axis X/Y/Z"
        key = axis.lower()
        sel = _region_filter_faces(faces, entry.get("view"),
                                   entry.get("region"))
        vals = [f["bbox"][key] for f in sel if f.get("bbox")]
        if not vals:
            return None, f"{fname}: no faces for extent {axis}"
        return (round(max(v[1] for v in vals) - min(v[0] for v in vals),
                      4),
                f"{fname} extent {axis}")
    if kind == "span":
        if not faces:
            return None, f"no STEP faces attributed to {fname}"
        axis = (entry.get("axis") or "").upper()
        if axis not in ("X", "Y", "Z"):
            axis = {"front": "Z", "side": "Z", "top": "Y",
                    "section": "Y"}.get(entry.get("view"), "Z")
        key = axis.lower()
        sel = _region_filter_faces(faces, entry.get("view"),
                                   entry.get("region"))
        extremum = (entry.get("extremum") or "max").lower()
        top = None
        if entry.get("localmin"):
            # Hook-tip dip: lowest interior local minimum of the
            # feature's ORDERED curve samples in the region. A
            # band min/max would catch the band edge (where the
            # curve enters the band), not the dip; unordered
            # tessellation vertices cannot tell them apart.
            cands = []
            ai3 = {"X": 0, "Y": 1, "Z": 2}[axis]
            for f in sel:
                pts = _region_filter_points(f.get("curve") or [],
                                            faces, entry.get("view"),
                                            entry.get("region"))
                for i in range(1, len(pts) - 1):
                    a = pts[i][ai3]
                    if a <= pts[i-1][ai3] and a <= pts[i+1][ai3] and \
                            (a < pts[i-1][ai3] or a < pts[i+1][ai3]):
                        cands.append(a)
            if cands:
                top = min(cands)
            else:
                return None, f"{fname}: no local minimum in region"
        if top is None:
            vals = [f["bbox"][key] for f in sel if f.get("bbox")]
            if not vals:
                return None, f"{fname}: no faces for span {axis}"
            top = (max(v[1] for v in vals) if extremum != "min"
                   else min(v[0] for v in vals))
        datum = entry.get("datum")
        if not datum or "." not in str(datum):
            return None, "span needs datum '<Feature>.top|.bottom'"
        dfeat_name, dside = str(datum).rsplit(".", 1)
        if dside not in ("top", "bottom"):
            return None, f"datum side must be .top or .bottom, got {datum}"
        # Datum value: the datum feature's own created planes along
        # the span axis, relocated in the STEP (same end-plane
        # relocation as pad_length: a trimmed datum plane still
        # exists at its offset). Fallback: attributed bbox.
        ai2 = {"X": 0, "Y": 1, "Z": 2}[axis]
        dfeat = by_name.get(dfeat_name)
        dval = None
        if dfeat is not None:
            doffsets = sorted({round(f["center"][ai2], 3)
                               for f in dfeat.get("created_faces", [])
                               if f.get("type") == "Plane"
                               and f.get("normal")
                               and abs(f["normal"][ai2]) > 0.999
                               and f.get("center")})
            found = [o for o in doffsets
                     if any(sf.get("type") == "Plane"
                            and sf.get("normal")
                            and abs(sf["normal"][ai2]) > 0.999
                            and sf.get("center")
                            and abs(sf["center"][ai2] - o) < 0.01
                            for sf in step_faces)]
            if found:
                dval = max(found) if dside == "top" else min(found)
        if dval is None:
            dfaces = _attributed_faces(dfeat_name, attribution, step_faces)
            dvals = [f["bbox"][key] for f in dfaces if f.get("bbox")]
            if not dvals:
                return None, (f"datum feature {dfeat_name} has no "
                              "attributed faces")
            dval = max(v[1] for v in dvals) if dside == "top" \
                else min(v[0] for v in dvals)
        return round(top - dval, 4), f"{fname} span {axis} from {datum}"
    if kind == "chamfer_size":
        return None, f"{fname} chamfer faces not measured in v1"
    if kind == "sketch_constraint":
        if not faces:
            return None, f"no STEP faces attributed to {fname}"
        sk_name = entry.get("sketch") or feat.get("sketch")
        sk = by_name.get(sk_name) if sk_name else None
        if sk is None:
            return None, f"sketch {sk_name} not found in .fcstd"
        cons = [c for c in sk.get("constraints", [])
                if c.get("name") == d_id]
        if not cons:
            return None, f"{sk_name} has no constraint named {d_id}"
        c = cons[0]
        geom = {g.get("index"): g for g in sk.get("geometry", [])}
        g1 = geom.get(c.get("first"))
        g2 = geom.get(c.get("second"))
        if c.get("type") in ("Diameter", "Radius") and g1 and \
                g1.get("type") in ("Circle", "ArcOfCircle"):
            diams = sorted({round(2 * f["radius"], 4) for f in faces
                            if f.get("radius") is not None})
            if len(diams) == 1:
                d = diams[0]
                if c["type"] == "Diameter":
                    return d, f"{fname} cylinder diameter"
                return round(d / 2, 4), f"{fname} cylinder radius"
            return None, (f"{fname}: {len(diams)} cylinder diameters "
                          "(ambiguous)")
        # Direction constraint: DistanceX/Y uses the sketch axes;
        # Distance between two lines uses line_dir x extrusion.
        if c.get("type") in ("DistanceX", "DistanceY"):
            key = "sketch_x" if c["type"] == "DistanceX" else "sketch_y"
            n = sk.get(key)
            if not n:
                return None, f"{sk_name}: no {key}"
        else:
            line = g1 if g1 and g1.get("type") == "LineSegment" else g2
            normal = feat.get("sketch_normal") or sk.get("sketch_normal")
            if line is None or not line.get("start") \
                    or not line.get("end") or not normal:
                return None, (f"{sk_name} constraint {d_id}: no line "
                              "geometry")
            ld = [line["end"][i] - line["start"][i] for i in range(3)]
            ln = (ld[0] ** 2 + ld[1] ** 2 + ld[2] ** 2) ** 0.5
            if ln < 1e-9:
                return None, (f"{sk_name} constraint {d_id}: "
                              "zero-length line")
            ld = [x / ln for x in ld]
            n = [ld[1] * normal[2] - ld[2] * normal[1],
                 ld[2] * normal[0] - ld[0] * normal[2],
                 ld[0] * normal[1] - ld[1] * normal[0]]
            nn = (n[0] ** 2 + n[1] ** 2 + n[2] ** 2) ** 0.5
            if nn < 1e-9:
                return None, (f"{sk_name} constraint {d_id}: line "
                              "parallel to extrusion")
            n = [x / nn for x in n]
        planes = [f for f in faces
                  if f.get("type") == "Plane" and f.get("normal")
                  and abs(sum(f["normal"][i] * n[i]
                              for i in range(3))) > 0.999]
        offsets = sorted({round(sum(f["center"][i] * n[i]
                                  for i in range(3)), 3)
                          for f in planes if f.get("center")})
        if len(offsets) == 2:
            return (round(offsets[1] - offsets[0], 4),
                    f"{fname} faces normal to sketch line")
        # Fallback: a later feature may trim a wall (slot wall cut
        # by a hole), so attribution by area loses it -- but the
        # wall pieces still exist in the STEP. Relocate by the
        # SKETCH frame: STEP planes with the expected normal whose
        # center lies inside the sketch profile's (u, v) bbox.
        # Other features' parallel walls (base sides) fall outside
        # it. (The feature's created bbox does NOT work here: a
        # through pocket "creates" the split top/bottom caps, so
        # its created bbox spans the whole base.)
        sk2 = by_name.get(sk_name) if sk_name else None
        if sk2 is not None and sk2.get("sketch_origin") \
                and sk2.get("sketch_x") and sk2.get("sketch_y"):
            org, xa, ya = (sk2["sketch_origin"], sk2["sketch_x"],
                           sk2["sketch_y"])

            def _uv(pt):
                d = [pt[i] - org[i] for i in range(3)]
                return (sum(d[i] * xa[i] for i in range(3)),
                        sum(d[i] * ya[i] for i in range(3)))
            us, vs = [], []
            for g in sk2.get("geometry", []):
                for key in ("start", "end"):
                    if g.get(key):
                        u, v = _uv(g[key])
                        us.append(u)
                        vs.append(v)
                if g.get("center") is not None \
                        and g.get("radius") is not None:
                    cu, cv = _uv(g["center"])
                    us += [cu - g["radius"], cu + g["radius"]]
                    vs += [cv - g["radius"], cv + g["radius"]]
            if us and vs:
                ulo, uhi = min(us) - 0.01, max(us) + 0.01
                vlo, vhi = min(vs) - 0.01, max(vs) + 0.01
                planes2 = []
                for f in step_faces:
                    if f.get("type") != "Plane" or not f.get("normal"):
                        continue
                    if abs(sum(f["normal"][i] * n[i]
                               for i in range(3))) <= 0.999:
                        continue
                    if not f.get("center"):
                        continue
                    u, v = _uv(f["center"])
                    if ulo <= u <= uhi and vlo <= v <= vhi:
                        planes2.append(f)
                offsets2 = sorted({round(sum(f["center"][i] * n[i]
                                           for i in range(3)), 3)
                                   for f in planes2})
                if len(offsets2) == 2:
                    return (round(offsets2[1] - offsets2[0], 4),
                            f"{fname} faces normal to sketch line "
                            "(region)")
        return None, (f"{fname}: {len(offsets)} faces normal to "
                      "sketch line (need 2)")
    return None, f"unknown kind {kind!r}"


def run_measure_mode(output_dir, freecadcmd):
    """Measure an existing result folder's STEP, update matching.json.

    Runs measure_step.py (next to this script) under freecadcmd on
    <output_dir>/model.step, then fills the measured column of the
    D-rows in matching.json and appends a summary to report.txt.
    Returns 0 on success (even if some rows get no measurement),
    1 on hard failure (no STEP, missing measure script, freecadcmd
    failure, no measurements file).
    """
    script_dir = Path(__file__).resolve().parent
    measure_script = script_dir / "measure_step.py"
    step_path = output_dir / "model.step"
    if not step_path.is_file():
        print(f"MEASURE FAIL: no model.step in {output_dir}")
        return 1
    if not measure_script.is_file():
        print(f"MEASURE FAIL: measure_step.py not found next to "
              f"run_pipeline.py ({measure_script})")
        return 1
    if shutil.which(freecadcmd) is None and not Path(freecadcmd).is_file():
        print(f"MEASURE FAIL: freecadcmd not found: {freecadcmd}")
        return 1
    measurements_path = output_dir / "measurements.json"
    log_path = output_dir / "measure_log.txt"
    env = dict(os.environ)
    env["MEASURE_OUT"] = str(measurements_path)
    with open(log_path, "w", encoding="utf-8") as log_file:
        result = subprocess.run(
            [freecadcmd, str(measure_script), str(step_path)],
            stdout=log_file, stderr=subprocess.STDOUT, env=env)
    # freecadcmd exits 0 even on macro errors, so the file is the
    # only trustworthy signal.
    if not measurements_path.is_file():
        print("MEASURE FAIL: measurements.json was not written "
              f"(see {log_path})")
        return 1
    try:
        measurements = json.loads(measurements_path.read_text(
            encoding="utf-8"))
    except Exception as exc:
        print(f"MEASURE FAIL: cannot read measurements.json: {exc}")
        return 1
    if measurements.get("error"):
        print(f"MEASURE FAIL: {measurements['error']}")
        return 1
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    measurements["measured_at"] = stamp
    measurements_path.write_text(
        json.dumps(measurements, indent=1, ensure_ascii=False),
        encoding="utf-8")
    # Bootstrap (Nov 1, 2026): Measure used to write an empty
    # matching.json when the folder had no table, so the tab
    # stayed empty even though measurement ran. If no D-rows
    # exist yet, build the table first (from dimensions.json),
    # so the measured values below have rows to fill.
    if not _matching_has_d_rows(output_dir):
        try:
            ensure_matching_file(output_dir, freecadcmd)
        except Exception:
            pass
    matching_path = output_dir / "matching.json"
    rows = []
    if matching_path.is_file():
        try:
            rows = json.loads(matching_path.read_text(encoding="utf-8"))
        except Exception:
            rows = []
    # Refresh modeling/result with the CURRENT matching rules when
    # the folder still holds the macro that built the model. Old
    # result folders carry stale modeling values (whole-bbox
    # mapping: widths -> size Y, heights -> size Z), which is why
    # their Result column shows X even though the measured column
    # is nearly exact. The D-list is rebuilt from the stored rows
    # themselves (label/value/view/reference), so no dimensions.json
    # is needed; folders without macro.py keep their old rows, and
    # a failed verification never downgrades good rows to ?.
    macro_path = output_dir / "macro.py"
    d_old = [r for r in rows
             if re.match(r"D\d+$", str(r.get("no", "")))]
    if macro_path.is_file() and d_old:
        try:
            verification = verify_step(freecadcmd, step_path, output_dir)
            macro_text = macro_path.read_text(encoding="utf-8",
                                              errors="replace")
            d_lines = []
            for r in d_old:
                item = str(r.get("item", ""))
                view = r.get("view")
                if not view:
                    vm = re.search(r"\[(front|section|side|top)\]\s*$",
                                   item)
                    view = vm.group(1) if vm else None
                label = re.sub(r"\s*\[(front|section|side|top)\]\s*$",
                               "", item)
                val = r.get("drawing")
                if val is None:
                    continue
                val_txt = (f"({val})"
                           if r.get("result") == "? (참조치수)"
                           else f"{val}")
                view_txt = f" [{view}]" if view else ""
                d_lines.append(f"{r.get('no')}: {label} = {val_txt} mm"
                               f"{view_txt}")
            new_rows = None
            mapping_data = None
            mapping_file = output_dir / "mapping.json"
            if mapping_file.is_file():
                try:
                    mapping_data = json.loads(
                        mapping_file.read_text(encoding="utf-8"))
                except Exception:
                    mapping_data = None
            if mapping_data is None:
                m2, _ = extract_feature_map(macro_text)
                if m2:
                    mapping_data = m2
            if mapping_data is not None:
                features_data = run_read_features(
                    freecadcmd, output_dir / "model.fcstd", output_dir)
                if features_data is None:
                    print("MEASURE NOTE: mapping refresh skipped "
                          "(features unreadable); keeping existing rows")
                else:
                    new_rows = build_matching(
                        verification, macro_text, "\n".join(d_lines),
                        mapping=mapping_data, features=features_data)
            else:
                new_rows = build_matching(verification, macro_text,
                                          "\n".join(d_lines))
            if verification.get("ok") and new_rows:
                rows = new_rows
                print(f"MEASURE NOTE: modeling column refreshed "
                      f"({len(new_rows)} rows)")
        except Exception as exc:
            print(f"MEASURE NOTE: modeling refresh skipped ({exc}); "
                  f"keeping existing rows")
    # Anchored measurement when the folder carries a mapping (new
    # builds): each D-row is measured on its mapped feature's STEP
    # faces only. Per-row fallback (Oct 31, 2026): a partial map
    # must NOT disable measurement for its unmapped rows -- the
    # old folder-level rule (mapping present => every unmapped row
    # gets ?) made a 1-entry remap map WORSE than no map at all
    # for the measured column. So an unmapped row, or a row whose
    # anchored measurement returns nothing, falls back to the
    # battery for the MEASURED column only, with its method
    # labelled "battery fallback" (never silent, never anchored).
    # The MODELING column keeps its ? -- only the measured value
    # is allowed to fall back, because a measured value is a STEP
    # fact with a visible method, while a modeling value claims a
    # feature link that does not exist. NOTE rows (tolerance /
    # general chamfer) never fall back: they are rules, not sizes.
    mapping_data = None
    mapping_present = False
    mapping_file = output_dir / "mapping.json"
    if mapping_file.is_file():
        try:
            mapping_data = json.loads(
                mapping_file.read_text(encoding="utf-8"))
            mapping_present = True
        except Exception:
            mapping_data = None
    anchored = None
    anchored_by_name = {}
    anchored_faces = []
    if mapping_present:
        features_data = run_read_features(
            freecadcmd, output_dir / "model.fcstd", output_dir)
        step_faces = measurements.get("faces") or []
        if features_data is not None and step_faces:
            anchored_by_name = _features_by_name(features_data)
            anchored = attribute_step_faces(features_data, step_faces)
            anchored_faces = step_faces
    measured_count = 0
    d_count = 0
    for row in rows:
        no = str(row.get("no", ""))
        if not re.match(r"D\d+$", no):
            continue  # only D-rows get a measured column
        d_count += 1
        item = str(row.get("item", ""))
        view = row.get("view")
        if not view:
            vm = re.search(r"\[(front|section|side|top)\]\s*$", item)
            view = vm.group(1) if vm else None
        label = re.sub(r"\s*\[(front|section|side|top)\]\s*$", "",
                       item)
        value = row.get("drawing")
        if value is None:
            row["measured"] = None
            row["measured_method"] = None
            row["measured_result"] = None
            continue
        if mapping_present:
            entry = mapping_data.get(no)
            if entry is None:
                measured, method = None, "no FEATURE_MAP entry"
            elif anchored is None:
                measured, method = None, \
                    "attribution unavailable (.fcstd or STEP faces)"
            else:
                measured, method = measure_anchored(
                    no, entry, anchored_by_name, anchored, anchored_faces)
            if measured is None and "NOTE" not in label.upper():
                # Per-row measured fallback (see comment above):
                # only the measured column, explicitly labelled.
                _fb, _fb_method = match_measured(
                    label, float(value), view, measurements)
                if _fb is not None:
                    measured, method = (
                        _fb, f"battery fallback: {_fb_method}")
        else:
            measured, method = match_measured(label, float(value), view,
                                              measurements)
        row["measured"] = measured
        row["measured_method"] = method
        # Separate verdict for the measured value, next to the
        # modeling-based Result: general tolerance ±0.1 (NOT the
        # strict 0.01 table tolerance, which would flag accepted
        # outline deviations like peak height 1.739 vs 1.70).
        # No measurement -> ? (cannot judge); non-D rows keep no
        # measured_result field at all.
        if measured is None:
            row["measured_result"] = "?"
        elif abs(measured - float(value)) <= 0.1 + 1e-9:
            row["measured_result"] = "O"
        else:
            row["measured_result"] = "X"
        if measured is not None:
            measured_count += 1
    matching_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False),
                             encoding="utf-8")
    summary = (f"Measurement (실측) {stamp}: {measured_count}/{d_count} "
               f"D-rows measured (see matching.json measured column; "
               f"methods in measurements.json).")
    print(summary)
    report_path = output_dir / "report.txt"
    try:
        with open(report_path, "a", encoding="utf-8") as f:
            f.write("\n" + summary + "\n")
    except OSError:
        pass
    return 0


def run_remap_mode(output_dir, freecadcmd, model, max_tokens, dry_run):
    """Repair a folder's FEATURE_MAP without rebuilding the model.

    Used by the matching-table "Remap" button when a build produced
    a correct model but a blind table (all D-rows "?" with
    "no FEATURE_MAP entry"). One short LLM call is given ONLY the
    folder's D-list + the .fcstd feature dump (no drawing, no
    rebuild) and must return a FEATURE_MAP dict literal. Every
    returned entry is validated with resolve_mapping_value against
    the dump; entries that do not resolve are dropped with a reason
    in remap_log.txt, never kept as guesses. The validated map is
    saved to mapping.json (old map kept as mapping_before_remap.json)
    and matching.json is rebuilt from it. model.fcstd, model.step,
    macro.py, and report.txt are never changed. Returns 0 when a
    validated map was saved and matching.json rebuilt, 1 on hard
    failure (missing files, no API key, API error, or no entry
    validated) -- a remap failure never touches the model.
    """
    macro_path = output_dir / "macro.py"
    fcstd_path = output_dir / "model.fcstd"
    step_path = output_dir / "model.step"
    matching_path = output_dir / "matching.json"
    log_lines = []
    def _log(msg):
        log_lines.append(msg)
        print(msg)
    for needed, label in ((macro_path, "macro.py"),
                          (fcstd_path, "model.fcstd"),
                          (step_path, "model.step"),
                          (matching_path, "matching.json")):
        if not needed.is_file():
            _log(f"REMAP FAIL: {label} missing in {output_dir}")
            (output_dir / "remap_log.txt").write_text(
                "\n".join(log_lines) + "\n", encoding="utf-8")
            return 1
    try:
        rows = json.loads(matching_path.read_text(encoding="utf-8"))
    except Exception:
        rows = []
    d_rows = [r for r in rows if re.match(r"D\d+$", str(r.get("no", "")))]
    if not d_rows:
        _log("REMAP FAIL: no D-rows in matching.json to map")
        (output_dir / "remap_log.txt").write_text(
            "\n".join(log_lines) + "\n", encoding="utf-8")
        return 1
    d_lines = []
    for r in d_rows:
        item = str(r.get("item", ""))
        view = r.get("view")
        if not view:
            vm = re.search(r"\[(front|section|side|top)\]\s*$", item)
            view = vm.group(1) if vm else None
        label = re.sub(r"\s*\[(front|section|side|top)\]\s*$", "", item)
        val = r.get("drawing")
        if val is None:
            continue
        d_lines.append(f"{r.get('no')}: {label} = {val} mm"
                       f"{' [' + view + ']' if view else ''}")
    features_data = run_read_features(freecadcmd, fcstd_path, output_dir)
    if features_data is None:
        _log("REMAP FAIL: .fcstd feature dump unreadable")
        (output_dir / "remap_log.txt").write_text(
            "\n".join(log_lines) + "\n", encoding="utf-8")
        return 1
    by_name = _features_by_name(features_data)
    feat_lines = []
    for name, feat in by_name.items():
        cons = [(c.get("name"), c.get("value"))
                for c in (feat.get("constraints") or [])]
        # The pre-fix prompt listed ONLY length/size/sketch/
        # constraints, although the dump also carries the data most
        # dimensions actually are: created-face cylinder diameters
        # and feature extents, plus sketch circle diameters. With
        # only Length to go on, an honest LLM maps exactly one row
        # (D1 = Pad_Body length 7.0) and leaves the rest out "do
        # not guess" -- the Oct 31, 2026 home remap returned 1/13
        # for exactly this reason. Give it the full per-feature
        # numbers so diameter/extent rows can be mapped at all.
        faces = feat.get("created_faces") or []
        cyl_diams = sorted({round(2 * fc["radius"], 4)
                            for fc in faces
                            if fc.get("radius") is not None})
        ext = {}
        for ax in ("x", "y", "z"):
            vals = []
            for fc in faces:
                bb = fc.get("bbox") or {}
                rng = bb.get(ax)
                if rng and len(rng) == 2:
                    vals += [rng[0], rng[1]]
            if vals:
                ext[ax.upper()] = round(max(vals) - min(vals), 4)
        geom = feat.get("geometry") or []
        circ_diams = sorted({round(2 * g["radius"], 4)
                             for g in geom
                             if g.get("type") == "Circle"
                             and g.get("radius") is not None})
        feat_lines.append(
            f"- {name}: length={feat.get('length')} "
            f"size={feat.get('size')} sketch={feat.get('sketch')} "
            f"constraints={cons} cyl_diams={cyl_diams} "
            f"extent={ext} sketch_circle_diams={circ_diams}")
    prompt = (
        "Write ONLY one python code fence containing exactly this "
        "assignment (no other text, no bare dict):\n"
        "FEATURE_MAP = {\"D<n>\": {\"feature\": \"<name>\", "
        "\"kind\": \"<kind>\", ...}, ...}\n"
        "Map EVERY D-number below to the feature in the .fcstd dump "
        "that creates that dimension. Use feature names EXACTLY as "
        "listed; do not invent features, sketches, or constraint "
        "names. Kinds: pad_length (feature Length), chamfer_size "
        "(feature Size), diameter/radius (feature's cylinder), "
        "feature_extent (axis X/Y/Z), sketch_constraint (ONLY when "
        "the sketch already has a constraint named exactly D<n>). "
        "Reference/note rows (tolerance, general chamfer) need no "
        "entry. If a row cannot be mapped from the dump data, "
        "leave it out -- do not guess.\n\n"
        "Dimensions:\n" + "\n".join(d_lines) + "\n\n"
        "Features in .fcstd:\n" + "\n".join(feat_lines) + "\n")
    # Step 2 (Q&A matching): the folder's Q&A history, verbatim,
    # in whatever language the answers were written (Korean,
    # English, or both mixed). No keyword dictionary is used --
    # the LLM reads both languages and bridges them to the
    # English feature names above, which is what resolves
    # ambiguous rows value alone cannot (two 1.5 features: boss
    # vs recess; several features sharing 7.93 or 22). Entries
    # still go through resolve_mapping_value validation below,
    # so a Q&A reading that does not resolve is dropped, never
    # kept as a guess.
    qa_path = output_dir / "qa_history.txt"
    if qa_path.is_file():
        try:
            qa_text = qa_path.read_text(encoding="utf-8",
                                        errors="replace")
        except OSError:
            qa_text = ""
        if qa_text.strip():
            prompt += ("\nQ&A history (user-confirmed answers; "
                       "use these to resolve ambiguous rows -- "
                       "they name which feature a dimension "
                       "belongs to, even when two features share "
                       "the same value):\n"
                       + qa_text[:12000] + "\n")
    (output_dir / "remap_prompt.txt").write_text(prompt, encoding="utf-8")
    if dry_run:
        _log("REMAP DRY-RUN: prompt written to remap_prompt.txt, "
             "no API call, no mapping change")
        (output_dir / "remap_log.txt").write_text(
            "\n".join(log_lines) + "\n", encoding="utf-8")
        return 0
    api_key = os.environ.get("META_API_KEY") or load_dotenv_key()
    if not api_key:
        _log("REMAP FAIL: META_API_KEY is not set (password field "
             "or local .env)")
        (output_dir / "remap_log.txt").write_text(
            "\n".join(log_lines) + "\n", encoding="utf-8")
        return 1
    try:
        response_json = call_api(api_key, model, max_tokens,
                                 [{"role": "user",
                                   "content": prompt}])
        content = extract_content(response_json)
    except RuntimeError as exc:
        _log(f"REMAP FAIL: API error: {exc}")
        (output_dir / "remap_log.txt").write_text(
            "\n".join(log_lines) + "\n", encoding="utf-8")
        return 1
    (output_dir / "remap_raw_response.txt").write_text(
        json.dumps(response_json, indent=2, ensure_ascii=False),
        encoding="utf-8")
    candidate, warn = extract_feature_map_from_response(content)
    if warn:
        _log(f"REMAP FAIL: {warn}")
        (output_dir / "remap_log.txt").write_text(
            "\n".join(log_lines) + "\n", encoding="utf-8")
        return 1
    validated = {}
    dropped = []
    for d_id, entry in candidate.items():
        value, method = resolve_mapping_value(d_id, entry, by_name)
        if value is not None:
            validated[d_id] = entry
        else:
            dropped.append(f"{d_id}: {method}")
    _log(f"REMAP: {len(validated)} entries validated, "
         f"{len(dropped)} dropped")
    for d in dropped:
        _log(f"  dropped {d}")
    if not validated:
        _log("REMAP FAIL: no entry validated against the .fcstd dump")
        (output_dir / "remap_log.txt").write_text(
            "\n".join(log_lines) + "\n", encoding="utf-8")
        return 1
    mapping_file = output_dir / "mapping.json"
    if mapping_file.is_file():
        try:
            (output_dir / "mapping_before_remap.json").write_text(
                mapping_file.read_text(encoding="utf-8"),
                encoding="utf-8")
        except OSError:
            pass
    mapping_file.write_text(json.dumps(validated, indent=2,
                                       ensure_ascii=False),
                            encoding="utf-8")
    try:
        verification = verify_step(freecadcmd, step_path, output_dir)
        macro_text = macro_path.read_text(encoding="utf-8",
                                          errors="replace")
        new_rows = build_matching(verification, macro_text,
                                  "\n".join(d_lines), mapping=validated,
                                  features=features_data)
        matching_path.write_text(json.dumps(new_rows, indent=2,
                                            ensure_ascii=False),
                                 encoding="utf-8")
        filled = sum(1 for r in new_rows
                     if re.match(r"D\d+$", str(r.get("no", "")))
                     and r.get("modeling") is not None)
        _log(f"REMAP OK: matching.json rebuilt, "
             f"{filled}/{len(d_rows)} D-rows now have modeling values")
    except Exception as exc:
        _log(f"REMAP FAIL: matching rebuild failed ({exc})")
        (output_dir / "remap_log.txt").write_text(
            "\n".join(log_lines) + "\n", encoding="utf-8")
        return 1
    (output_dir / "remap_log.txt").write_text(
        "\n".join(log_lines) + "\n", encoding="utf-8")
    return 0


def run_inspect_mode(output_dir, freecadcmd):
    """Feature inspection for an existing result folder (separate button).

    NOT a gate, NOT a rebuild, NOT a failure: this mode only READS
    the current model (fresh STEP verification + .fcstd feature
    dump) and compares it with the folder's matching table and
    FEATURE_MAP. It writes feature_check.txt (human-readable) and
    feature_check.json (structured), appends ONE compact entry to
    feature_check_history.txt, and always returns 0 when the folder
    exists -- even when checks MISS. A miss means "this feature is
    not in the model yet, fix it in the next Continue run", never
    "this run failed, throw the model away". It never touches
    model.fcstd, model.step, macro.py, or report.txt.
    History: feature_check_history.txt is append-only and is
    copied forward by the web UI's Continue work, so the next
    build's prompt carries every previous inspection's misses.
    """
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    step_path = output_dir / "model.step"
    fcstd_path = output_dir / "model.fcstd"
    matching_path = output_dir / "matching.json"
    mapping_path = output_dir / "mapping.json"
    rows = []
    if matching_path.is_file():
        try:
            rows = json.loads(matching_path.read_text(encoding="utf-8"))
        except Exception:
            rows = []
    mapping = None
    if mapping_path.is_file():
        try:
            mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
        except Exception:
            mapping = None
    verification = None
    if step_path.is_file():
        try:
            verification = verify_step(freecadcmd, step_path, output_dir)
        except Exception:
            verification = None
    features_data = None
    by_name = {}
    if fcstd_path.is_file():
        try:
            features_data = run_read_features(freecadcmd, fcstd_path,
                                              output_dir)
            if features_data is not None:
                by_name = _features_by_name(features_data)
        except Exception:
            features_data = None
    checks = []
    missing = []
    diffs = []
    counts = {"OK": 0, "MISS": 0, "DIFF": 0, "?": 0, "REF": 0}
    for row in rows:
        no = str(row.get("no", ""))
        if not re.match(r"D\d+$", no):
            continue
        item = str(row.get("item", ""))
        drawing = row.get("drawing")
        modeling = row.get("modeling")
        result = str(row.get("result", ""))
        measured = row.get("measured")
        meas_result = row.get("measured_result")
        entry = (mapping or {}).get(no) if mapping is not None else None
        feature = entry.get("feature") if isinstance(entry, dict) else None
        in_fcstd = feature in by_name if feature else None
        low_item = item.lower()
        if result == "? (참조치수)" or "tolerance" in low_item or \
                "general chamfer" in low_item:
            # Notes/rules, not geometry: never a miss, never a diff.
            status = "REF"
        elif modeling is None:
            status = "MISS"
        elif result == "X":
            # Value present but different: could be a wrong build
            # OR a drawing misread (e.g. gear D1 21 vs true 22).
            # Listed separately from MISS (feature absent), so the
            # history does not claim a present feature is missing.
            status = "DIFF"
        elif result == "O":
            status = "OK"
        else:
            status = "?"
        # A mapped feature that is not in the .fcstd dump at all is
        # a miss even if an old modeling value happens to look right.
        if feature and in_fcstd is False and status in ("OK", "DIFF"):
            status = "MISS"
        counts[status] = counts.get(status, 0) + 1
        checks.append({"no": no, "item": item, "drawing": drawing,
                       "modeling": modeling, "result": result,
                       "measured": measured,
                       "measured_result": meas_result,
                       "feature": feature, "feature_in_fcstd": in_fcstd,
                       "check": status})
        if status == "MISS":
            missing.append(f"{no} {item} (drawing {drawing}, "
                           f"modeling {modeling}, feature {feature})")
        elif status == "DIFF":
            diffs.append(f"{no} {item} (drawing {drawing}, "
                         f"modeling {modeling}, feature {feature})")
    model_info = {}
    if verification and verification.get("ok"):
        model_info = {"solids": verification.get("solids"),
                      "valid": verification.get("valid"),
                      "volume": verification.get("volume"),
                      "size_x": verification.get("size_x"),
                      "size_y": verification.get("size_y"),
                      "size_z": verification.get("size_z"),
                      "cyl_diams": verification.get("cyl_diams")}
    else:
        model_info = {"solids": None, "valid": None,
                      "note": "STEP verification unavailable"}
    payload = {"inspected_at": stamp, "folder": output_dir.name,
               "model": model_info, "mapping_present": mapping is not None,
               "features_in_fcstd": sorted(by_name.keys()),
               "checks": checks, "missing": missing, "diffs": diffs, "counts": counts}
    (output_dir / "feature_check.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [f"Feature check {stamp} (folder {output_dir.name})",
             f"Model: solids={model_info.get('solids')} "
             f"valid={model_info.get('valid')} "
             f"volume={model_info.get('volume')} "
             f"size X={model_info.get('size_x')} "
             f"Y={model_info.get('size_y')} Z={model_info.get('size_z')}",
             f"Counts: OK {counts['OK']}, MISS {counts['MISS']}, "
             f"DIFF {counts['DIFF']}, ? {counts['?']}, REF {counts['REF']}",
             f"Missing ({len(missing)}):"]
    lines += [f"  - {m}" for m in missing] or ["  - none"]
    lines.append(f"Differs from drawing ({len(diffs)}):")
    lines += [f"  - {m}" for m in diffs] or ["  - none"]
    lines.append("Checks:")
    for c in checks:
        lines.append(f"  [{c['check']}] {c['no']} {c['item']} | "
                     f"drawing {c['drawing']} | modeling {c['modeling']} "
                     f"({c['result']}) | measured {c['measured']} "
                     f"({c['measured_result']}) | "
                     f"feature {c['feature']} in_fcstd={c['feature_in_fcstd']}")
    (output_dir / "feature_check.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    hist_entry = (f"--- {stamp} ---\n"
                  f"PASS {counts['OK']}, MISS {counts['MISS']}, "
                  f"DIFF {counts['DIFF']}, ? {counts['?']}, "
                  f"REF {counts['REF']}\n"
                  f"Missing: {'; '.join(missing) if missing else 'none'}\n"
                  f"Differs: {'; '.join(diffs) if diffs else 'none'}\n")
    try:
        with open(output_dir / "feature_check_history.txt", "a",
                  encoding="utf-8") as f:
            f.write(hist_entry)
    except OSError:
        pass
    print(f"Feature check {stamp}: OK {counts['OK']}, "
          f"MISS {counts['MISS']}, DIFF {counts['DIFF']}, "
          f"? {counts['?']} "
          f"(see feature_check.txt; model unchanged, not a failure)")
    return 0


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


def run_read_features(freecadcmd, fcstd_path, output_dir):
    """Run read_features.py under freecadcmd on a .fcstd file.

    Returns the features.json dict, or None when the dump is missing
    or carries an error. Same env-var pattern as measure_step.py:
    freecadcmd exits 0 even on macro errors, so the output file is
    the only trustworthy signal.
    """
    script_dir = Path(__file__).resolve().parent
    script = script_dir / "read_features.py"
    if not script.is_file():
        return None
    features_path = output_dir / "features.json"
    log_path = output_dir / "features_log.txt"
    env = dict(os.environ)
    env["FCSTD_PATH"] = str(fcstd_path)
    env["FEATURES_OUT"] = str(features_path)
    try:
        with open(log_path, "w", encoding="utf-8") as log_file:
            subprocess.run([freecadcmd, str(script)],
                           stdout=log_file, stderr=subprocess.STDOUT,
                           env=env, timeout=600)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if not features_path.is_file():
        return None
    try:
        data = json.loads(features_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if data.get("error"):
        return None
    return data


def extract_patch_replacements(content):
    """Parse a JSON replacement list from an LLM patch response.

    Accepted shapes (in a ```json fence, a plain fence, or bare):
    [{"old": "<exact text>", "new": "<exact text>"}, ...]
    {"replacements": [{...}, ...]}
    Returns (replacements, error_or_None). The list is validated
    for shape only here; apply_patch_replacements() validates
    each "old" against the actual macro (exactly one occurrence).
    """
    candidates = []
    for fence in re.findall(r"```[^\n]*\n(.*?)```", content or "", re.DOTALL):
        candidates.append(fence.strip())
    candidates.append((content or "").strip())
    for cand in candidates:
        if not cand:
            continue
        # Try the whole candidate, then its outermost [...] / {...}
        tries = [cand]
        for open_ch, close_ch in (("[", "]"), ("{", "}")):
            start = cand.find(open_ch)
            end = cand.rfind(close_ch)
            if 0 <= start < end:
                tries.append(cand[start:end + 1])
        for text in tries:
            try:
                data = json.loads(text)
            except Exception:
                continue
            if isinstance(data, dict):
                data = data.get("replacements")
            if not isinstance(data, list) or not data:
                continue
            replacements = []
            bad = False
            for item in data:
                if not isinstance(item, dict):
                    bad = True
                    break
                old = item.get("old")
                new = item.get("new", "")
                if not isinstance(old, str) or not old:
                    bad = True
                    break
                if not isinstance(new, str):
                    bad = True
                    break
                replacements.append({"old": old, "new": new})
            if not bad and replacements:
                return replacements, None
    return [], ("no JSON replacement list found in patch response "
                "(expected one ```json fence with "
                '[{"old": "...", "new": "..."}])')


def apply_patch_replacements(macro_text, replacements):
    """Apply replacements to macro_text, all-or-nothing.

    Every "old" string must occur EXACTLY once in the macro.
    If any occurs 0 or 2+ times, NOTHING is applied and the
    errors name the failing replacement, so a partial patch can
    never leave a half-edited macro. Returns
    (new_text, applied_count, errors).
    """
    errors = []
    for index, rep in enumerate(replacements):
        count = macro_text.count(rep["old"])
        if count != 1:
            errors.append(
                f"replacement {index + 1}: old text occurs {count} "
                f"times, expected exactly 1 "
                f"(first 80 chars: {rep['old'][:80]!r})")
    if errors:
        return macro_text, 0, errors
    new_text = macro_text
    for rep in replacements:
        new_text = new_text.replace(rep["old"], rep["new"], 1)
    return new_text, len(replacements), []


def export_step_from_fcstd(freecadcmd, fcstd_path, step_path, output_dir):
    """Fallback STEP export when a macro saved .fcstd but not .step.

    Opens the .fcstd, exports the PartDesign Body shape (or, if no
    Body exists, the first solid-bearing object) to step_path.
    Returns True when step_path exists afterwards. This is the
    Oct 31, 2026 home case (182125 attempt 4: fcstd present, step
    missing, whole run failed for a missing export alone).
    """
    snippet = output_dir / "export_step_patch.py"
    snippet.write_text(
        "import FreeCAD\n"
        f"doc = FreeCAD.openDocument({str(fcstd_path)!r})\n"
        "body = None\n"
        "for obj in doc.Objects:\n"
        "    if obj.TypeId == 'PartDesign::Body':\n"
        "        body = obj\n"
        "        break\n"
        "target = body if body is not None else None\n"
        "if target is None:\n"
        "    for obj in doc.Objects:\n"
        "        try:\n"
        "            if obj.Shape and obj.Shape.Solids:\n"
        "                target = obj\n"
        "                break\n"
        "        except Exception:\n"
        "            pass\n"
        "if target is not None:\n"
        "    target.Shape.exportStep(" + f"{str(step_path)!r}" + ")\n"
        "    print('EXPORT_STEP_OK')\n"
        "else:\n"
        "    print('EXPORT_STEP_NO_TARGET')\n",
        encoding="utf-8",
    )
    log_path = output_dir / "export_step_patch.log"
    try:
        with open(log_path, "w", encoding="utf-8") as log_file:
            subprocess.run([freecadcmd, str(snippet)],
                           stdout=log_file, stderr=subprocess.STDOUT,
                           timeout=600)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return step_path.is_file()


def render_previews(output_dir):
    """Render preview PNGs from tris.json (best-effort, never a gate).

    Same chain as the full build used to inline: render_preview.py
    (matplotlib) first, then render_preview_pil.py (Pillow+numpy).
    Returns (ok, note). The renderers now draw an XYZ axes triad
    in every preview (X red, Y green, Z blue) so directions in
    questions and patches can be talked about against the image.
    """
    preview_iso = output_dir / "preview_iso.png"
    preview_main = output_dir / "preview_main.png"
    preview_front = output_dir / "preview_front.png"
    preview_top = output_dir / "preview_top.png"
    preview_side = output_dir / "preview_side.png"
    tris_path = output_dir / "tris.json"
    script_dir = Path(__file__).resolve().parent
    render_scripts = [
        script_dir / "render_preview.py",
        script_dir / "render_preview_pil.py",
    ]
    note = ""
    for render_script in render_scripts:
        if not render_script.is_file():
            continue
        try:
            preview_result = subprocess.run(
                [sys.executable, str(render_script), str(tris_path),
                 str(preview_iso), str(preview_main),
                 str(preview_front), str(preview_top),
                 str(preview_side)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=300, text=True)
            if preview_iso.is_file() and preview_main.is_file():
                return True, (f"{preview_iso}, {preview_main} "
                              f"(via {render_script.name})")
            note = (f"{render_script.name} exit "
                    f"{preview_result.returncode}, output: "
                    f"{preview_result.stdout[-300:]}")
        except Exception as exc:
            note = f"{render_script.name}: {exc}"
    return False, note


def run_images_mode(output_dir, freecadcmd):
    """Re-render preview images from the CURRENT model, no rebuild.

    Web "Extract images" button: requires model.step, runs
    verify_step (rewrites tris.json from the current STEP), then
    render_previews (with XYZ triad). The model, macro, and
    report are never changed; only preview_*.png + tris.json +
    images_log.txt are updated, so images after a patch are
    fresh instead of stale. Returns 0 on rendered previews,
    1 when no STEP or verification/rendering failed.
    """
    step_path = output_dir / "model.step"
    log_lines = []

    def _log(msg):
        log_lines.append(msg)
        print(msg)

    def _finish(code):
        (output_dir / "images_log.txt").write_text(
            "\n".join(log_lines) + "\n", encoding="utf-8")
        return code

    if not step_path.is_file():
        _log("IMAGES FAIL: model.step missing in this folder.")
        return _finish(1)
    verification = verify_step(freecadcmd, step_path, output_dir)
    _log(f"IMAGES: verification: {verification}")
    if not verification.get("ok"):
        _log("IMAGES FAIL: STEP verification snippet failed.")
        return _finish(1)
    ok, note = render_previews(output_dir)
    if ok:
        _log(f"IMAGES: previews rendered: {note}")
        return _finish(0)
    _log(f"IMAGES FAIL: previews unavailable ({note})")
    return _finish(1)


def parse_q_lines(text):
    """Parse 'Q<n>:' lines into {label: text}. Multiline answers
    are NOT joined here; callers use the first line per label."""
    out = {}
    for line in (text or "").splitlines():
        match = re.match(r"\s*(Q\d+)\s*:\s*(.*)$", line.strip())
        if match and match.group(2).strip():
            out[match.group(1)] = match.group(2).strip()
    return out


def clean_patch_instructions(text, question_dict=None):
    """De-duplicate a patch instruction that pasted questions as
    answers (Oct 31, 2026 home case, patch_prompt.txt).

    The web answer form prefills only 'Q13:' labels, but a user
    who pastes questions.txt into the answer box produces:
      Questions: Q13..Q20
      Answers: Q13..Q20 (the questions again)
      Answers: Q13..Q20 (the real answers)
    An LLM given that as 'modification instructions' sees the
    questions as if they were answers, and the real answers
    buried after a second 'Answers:' header. Fix: keep the
    Questions section for reference, keep ONLY the LAST
    'Answers:' section, and drop any answer line that exactly
    matches its question line. Returns (cleaned_text,
    answered_labels) where answered_labels are Q labels with a
    non-empty answer that differs from the question text.
    """
    question_dict = question_dict or {}
    lines = (text or "").splitlines()
    # Split on lines that are exactly 'Answers:' (allow trailing
    # spaces / CR from Windows pastes).
    sections = []
    current = []
    for line in lines:
        if line.strip() == "Answers:":
            sections.append(current)
            current = []
        else:
            current.append(line)
    sections.append(current)
    if len(sections) <= 1:
        # No 'Answers:' header at all: plain instruction text.
        # Still parse Q-label lines as answers for cleanup.
        answers = parse_q_lines(text)
        answered = {label for label, ans in answers.items()
                    if ans and ans != question_dict.get(label)}
        return text, answered
    # sections[0] = everything before the first Answers: (usually
    # the Questions: block). sections[-1] = the last Answers:
    # block, which is the real answers when duplicated.
    questions_part = "\n".join(sections[0]).strip()
    last_answers_lines = sections[-1]
    kept = []
    for line in last_answers_lines:
        stripped = line.strip()
        match = re.match(r"(Q\d+)\s*:\s*(.*)$", stripped)
        if match and question_dict.get(match.group(1)) == match.group(2).strip():
            continue
        kept.append(line)
    answers_text = "\n".join(kept).strip()
    answers = parse_q_lines(answers_text)
    answered = {label for label, ans in answers.items()
                if ans and ans != question_dict.get(label)}
    cleaned = ""
    if questions_part:
        cleaned += questions_part + "\n"
    cleaned += "Answers (apply these, do not re-ask them):\n" + answers_text
    return cleaned, answered


def answered_labels_from_qa_history(qa_text, question_dict):
    """Q labels answered in qa_history.txt (last Answers: section
    per round, real answers only, not pasted question lines)."""
    if not qa_text:
        return set()
    # Reuse the same de-duplication: split the whole history on
    # 'Answers:' and parse every section after the first, but a
    # pasted-questions section is dropped by the exact-match rule.
    answers = {}
    for part in qa_text.split("Answers:"):
        for label, ans in parse_q_lines(part).items():
            if ans and ans != question_dict.get(label):
                answers[label] = ans
    return set(answers)


def _dims_file_to_text(output_dir):
    """D-lines text for build_matching, from dimensions.json first,
    else from existing matching.json D-rows. Empty when neither
    source exists — build_matching then still yields the always
    rows, so a matching file can exist even without a D source."""
    dims_path = output_dir / "dimensions.json"
    if dims_path.is_file():
        try:
            dims = json.loads(dims_path.read_text(encoding="utf-8"))
        except Exception:
            dims = []
        lines = []
        for d in dims:
            if not isinstance(d, dict) or d.get("id") is None:
                continue
            val = d.get("value")
            if val is None:
                continue
            val_txt = f"({val})" if d.get("reference") else f"{val}"
            view_txt = f" [{d['view']}]" if d.get("view") else ""
            lines.append(f"{d['id']}: {d.get('label', '')} = "
                         f"{val_txt} mm{view_txt}")
        if lines:
            return "\n".join(lines)
    matching_path = output_dir / "matching.json"
    if matching_path.is_file():
        try:
            rows = json.loads(matching_path.read_text(encoding="utf-8"))
        except Exception:
            rows = []
        lines = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            no = str(r.get("no", ""))
            if not re.match(r"D\d+$", no):
                continue
            val = r.get("drawing")
            if val is None:
                continue
            lines.append(f"{no}: {r.get('item', '')} = {val} mm")
        return "\n".join(lines)
    return ""


def _matching_has_d_rows(output_dir):
    matching_path = output_dir / "matching.json"
    if not matching_path.is_file():
        return False
    try:
        rows = json.loads(matching_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return any(isinstance(r, dict)
               and re.match(r"D\d+$", str(r.get("no", "")))
               for r in rows)


def ensure_matching_file(output_dir, freecadcmd, macro_text=None,
                         verification=None, features=None):
    """Guarantee matching.json exists, with D-rows when a D source
    exists (Nov 1, 2026 user rule: the table JSON must keep
    existing, even on failure).

    Only builds when the file is missing or has no D-rows — an
    existing table (including its measured columns, which
    build_matching does not produce) is NEVER overwritten by
    this helper. Sources: dimensions.json (or old matching rows)
    for D-lines, macro.py FEATURE_MAP (or mapping.json) for the
    map, the STEP verification and the .fcstd feature dump for
    modeling values. On any build error, a minimal file with the
    always rows (or a single unavailable row) is still written,
    so the tab never has to say "no matching table" for a folder
    that has a model. Returns the row count written (0 only when
    even the minimal write failed).
    """
    if _matching_has_d_rows(output_dir):
        return -1
    try:
        if macro_text is None:
            macro_path = output_dir / "macro.py"
            macro_text = (macro_path.read_text(encoding="utf-8",
                                               errors="replace")
                          if macro_path.is_file() else "")
        mapping = None
        mapping_path = output_dir / "mapping.json"
        if mapping_path.is_file():
            try:
                mapping = json.loads(
                    mapping_path.read_text(encoding="utf-8"))
            except Exception:
                mapping = None
        if mapping is None:
            mapping, _warn = extract_feature_map(macro_text or "")
        if verification is None:
            step_path = output_dir / "model.step"
            if step_path.is_file():
                try:
                    verification = verify_step(freecadcmd, step_path,
                                               output_dir)
                except Exception:
                    verification = {}
            else:
                verification = {}
        if features is None:
            features_path = output_dir / "features.json"
            if features_path.is_file():
                try:
                    features = json.loads(
                        features_path.read_text(encoding="utf-8"))
                except Exception:
                    features = None
            elif (output_dir / "model.fcstd").is_file():
                try:
                    features = run_read_features(
                        freecadcmd, output_dir / "model.fcstd",
                        output_dir)
                except Exception:
                    features = None
        d_text = _dims_file_to_text(output_dir)
        rows = build_matching(verification or {}, macro_text or "",
                              d_text, mapping=mapping,
                              features=features)
        old_path = output_dir / "matching.json"
        if old_path.is_file():
            try:
                shutil.copyfile(old_path,
                                output_dir / "matching.prev.json")
            except OSError:
                pass
        old_path.write_text(json.dumps(rows, indent=2,
                                       ensure_ascii=False),
                            encoding="utf-8")
        return len(rows)
    except Exception:
        try:
            (output_dir / "matching.json").write_text(
                json.dumps([{"no": "—", "item": "Matching unavailable",
                             "drawing": None, "modeling": None,
                             "result": "?"}], indent=2,
                           ensure_ascii=False), encoding="utf-8")
            return 1
        except OSError:
            return 0


def run_build_table_mode(output_dir, freecadcmd):
    """Build (or rebuild) matching.json without rebuilding the
    model — the web matching tab's "표 만들기" button.

    No API call, no macro/model change, no report change. D-rows
    come from dimensions.json (or existing matching rows); the
    FEATURE_MAP comes from mapping.json or macro.py; modeling
    values come from the current .fcstd dump + STEP verification.
    Measured columns from a previous table are preserved by
    D-number. Fails clearly when there is no D source at all;
    even then ensure_matching_file leaves at least a minimal
    matching.json behind, so the tab is never empty for a
    missing-file reason.
    """
    log_lines = []

    def _log(msg):
        log_lines.append(msg)
        print(msg)

    def _finish(code):
        (output_dir / "table_log.txt").write_text(
            "\n".join(log_lines) + "\n", encoding="utf-8")
        return code

    old_rows = []
    matching_path = output_dir / "matching.json"
    if matching_path.is_file():
        try:
            old_rows = json.loads(
                matching_path.read_text(encoding="utf-8"))
        except Exception:
            old_rows = []
    measured_by_no = {}
    for r in old_rows:
        if isinstance(r, dict) and r.get("measured") is not None:
            measured_by_no[str(r.get("no", ""))] = {
                "measured": r.get("measured"),
                "measured_method": r.get("measured_method"),
                "measured_result": r.get("measured_result"),
            }
    d_text = _dims_file_to_text(output_dir)
    if not d_text.strip():
        _log("TABLE FAIL: no D source (dimensions.json or matching "
             "D-rows) in this folder, so no D table can be built.")
        ensure_matching_file(output_dir, freecadcmd)
        return _finish(1)
    macro_path = output_dir / "macro.py"
    macro_text = (macro_path.read_text(encoding="utf-8",
                                       errors="replace")
                  if macro_path.is_file() else "")
    mapping = None
    mapping_path = output_dir / "mapping.json"
    if mapping_path.is_file():
        try:
            mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
        except Exception:
            mapping = None
    if mapping is None:
        mapping, _warn = extract_feature_map(macro_text)
    verification = {}
    step_path = output_dir / "model.step"
    if step_path.is_file():
        try:
            verification = verify_step(freecadcmd, step_path, output_dir)
        except Exception:
            verification = {}
    features = None
    features_path = output_dir / "features.json"
    if features_path.is_file():
        try:
            features = json.loads(features_path.read_text(encoding="utf-8"))
        except Exception:
            features = None
    elif (output_dir / "model.fcstd").is_file():
        try:
            features = run_read_features(freecadcmd,
                                         output_dir / "model.fcstd",
                                         output_dir)
        except Exception:
            features = None
    try:
        rows = build_matching(verification, macro_text, d_text,
                              mapping=mapping, features=features)
    except Exception as exc:
        _log(f"TABLE FAIL: build_matching failed: {exc}")
        ensure_matching_file(output_dir, freecadcmd)
        return _finish(1)
    d_rows = [r for r in rows
              if isinstance(r, dict)
              and re.match(r"D\d+$", str(r.get("no", "")))]
    if not d_rows:
        _log("TABLE FAIL: build produced no D-rows.")
        ensure_matching_file(output_dir, freecadcmd)
        return _finish(1)
    preserved = 0
    for r in d_rows:
        saved = measured_by_no.get(str(r.get("no", "")))
        if saved:
            r.update(saved)
            preserved += 1
    if matching_path.is_file():
        try:
            shutil.copyfile(matching_path,
                            output_dir / "matching_before_table.json")
        except OSError:
            pass
    matching_path.write_text(json.dumps(rows, indent=2,
                                        ensure_ascii=False),
                             encoding="utf-8")
    _log(f"TABLE OK: matching.json built ({len(d_rows)} D-rows, "
         f"{preserved} measured column(s) preserved). Model, macro, "
         f"and report unchanged.")
    return _finish(0)


def extract_outline_points_from_json(data):
    """Snap-tool outline JSON -> numeric mm outline, or None.

    Preference order (all from the tool's own calibration, never
    guessed): (1) fills.auto_closed_outlines largest polygon_mm
    (other outlines inside its bbox are holes, per the tool's
    own note); (2) points[].mm in click_seq order; (3) a closed
    lines[] entry's points_mm. Any list with a null mm entry
    is skipped — uncalibrated px points are never presented
    as mm. Returns a dict like trace_outline.py's output
    (source, points_mm, holes_mm), or None.
    """
    if not isinstance(data, dict):
        return None

    def _mm_list(raw):
        if not isinstance(raw, list) or len(raw) < 3:
            return None
        out = []
        for p in raw:
            if not isinstance(p, dict):
                return None
            x, y = p.get("x"), p.get("y")
            if x is None or y is None:
                return None
            out.append([round(float(x), 4), round(float(y), 4)])
        return out

    fills = data.get("fills") or {}
    outlines = fills.get("auto_closed_outlines") or []
    cands = []
    for o in outlines:
        if not isinstance(o, dict):
            continue
        pts = _mm_list(o.get("polygon_mm"))
        if pts:
            cands.append((float(o.get("area_px2") or 0), pts))
    if cands:
        cands.sort(key=lambda t: -t[0])
        outer = cands[0][1]
        ox = [p[0] for p in outer]
        oy = [p[1] for p in outer]
        holes = []
        for _, pts in cands[1:]:
            if (min(p[0] for p in pts) >= min(ox)
                    and max(p[0] for p in pts) <= max(ox)
                    and min(p[1] for p in pts) >= min(oy)
                    and max(p[1] for p in pts) <= max(oy)):
                holes.append(pts)
        return {"source": "snap_json_fills", "points_mm": outer,
                "holes_mm": holes, "bottom_cropped": False}
    points = data.get("points") or []
    pts = []
    for p in sorted(points, key=lambda q: q.get("click_seq", 0)
                    if isinstance(q, dict) else 0):
        if not isinstance(p, dict):
            continue
        mm = p.get("mm")
        if not isinstance(mm, dict) or mm.get("x") is None \
                or mm.get("y") is None:
            return None
        pts.append([round(float(mm["x"]), 4),
                    round(float(mm["y"]), 4)])
    if len(pts) >= 3:
        return {"source": "snap_json_points", "points_mm": pts,
                "holes_mm": [], "bottom_cropped": False}
    for line in data.get("lines") or []:
        if not isinstance(line, dict) or not line.get("closed"):
            continue
        pts = _mm_list(line.get("points_mm"))
        if pts:
            return {"source": "snap_json_line", "points_mm": pts,
                    "holes_mm": [], "bottom_cropped": False}
    return None


def load_outline_points(output_dir):
    """outline_points.json in a folder, validated, or None."""
    path = output_dir / "outline_points.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if data.get("error"):
        return None
    pts = data.get("points_mm")
    if not isinstance(pts, list) or len(pts) < 3:
        return None
    return data


def format_outline_points_text(data):
    """Prompt section carrying traced outline points as numbers.

    This is the whole point of the trace step: the LLM gets
    coordinates to COPY, not an image to eyeball. The section
    also says what the coordinates are NOT: Y = 0 is the
    outline bottom (or a crop edge), never a dimension, and
    holes are inner voids, never outer contour.
    """
    if not data:
        return ""
    pts = data.get("points_mm") or []
    lines = ["TRACED OUTLINE — numeric points, copy exactly:"]
    lines.append(f"Source: {data.get('source', 'unknown')}. "
                 "The sketch for the outline feature MUST use "
                 "these points as a closed polyline, in this "
                 "order, closing back to the first point. Do NOT "
                 "invent other coordinates for that feature, do "
                 "NOT flip X/Y, do NOT mirror it.")
    if data.get("bottom_cropped"):
        lines.append("WARNING: the outline image bottom is cropped "
                     "(green touches the image edge), so Y = 0 is "
                     "the crop edge, NOT a design edge. Close the "
                     "profile at the real datum/base from the "
                     "drawing; do not treat Y = 0 as a dimension.")
    else:
        lines.append("X = 0 is the outline centre, Y = 0 is the "
                     "outline bottom (see source for the exact "
                     "datum); scale/origin come from the trace, "
                     "not from the drawing's other dimensions.")
    for i, (x, y) in enumerate(pts, 1):
        lines.append(f"P{i}: ({x:.4f}, {y:.4f}) mm")
    for hi, hole in enumerate(data.get("holes_mm") or [], 1):
        lines.append(f"Inner closed void {hi} (cut as a pocket, "
                     "NOT outer contour):")
        for i, (x, y) in enumerate(hole, 1):
            lines.append(f"  H{hi}P{i}: ({x:.4f}, {y:.4f}) mm")
    return "\n".join(lines)


def outline_text_check(macro_text, points_mm):
    """Best-effort, log-only check: how many traced points
    appear in the macro text on a single line (Vector/tuple
    point, ±0.05 mm). A B-spline through the points uses
    control points that differ, so a low count is a hint,
    never a gate — the caller logs it, never fails on it."""
    if not macro_text or not points_mm:
        return (0, len(points_mm or []))
    nums_by_line = []
    for line in macro_text.splitlines():
        nums = []
        for m in re.finditer(r"-?\d+(?:\.\d+)?", line):
            try:
                nums.append(float(m.group(0)))
            except ValueError:
                pass
        nums_by_line.append(nums)
    matched = 0
    for x, y in points_mm:
        ok = any(any(abs(n - x) <= 0.05 for n in nums)
                 and any(abs(n - y) <= 0.05 for n in nums)
                 for nums in nums_by_line)
        if ok:
            matched += 1
    return (matched, len(points_mm))


def run_trace_outline_mode(output_dir, freecadcmd, image_path,
                           width_mm):
    """Trace step: outline image/JSON -> outline_points.json.

    JSON input needs no image processing: its mm polygon is
    extracted directly. Image input runs trace_outline.py under
    freecadcmd (bundled PIL) into outline_traced.json, then
    copies it to outline_points.json ONLY on success — a
    failed trace never overwrites a previous good trace.
    Returns 0 on success, 1 on failure (log in trace_log.txt).
    """
    log_lines = []

    def _log(msg):
        log_lines.append(msg)
        print(msg)

    def _finish(code):
        (output_dir / "trace_log.txt").write_text(
            "\n".join(log_lines) + "\n", encoding="utf-8")
        return code

    if image_path is None:
        cands = sorted(output_dir.glob("input_outline.*"))
        image_path = None
        for c in cands:
            if c.suffix.lower() in (".png", ".jpg", ".jpeg",
                                    ".webp", ".bmp", ".gif"):
                image_path = c
                break
        if image_path is None and cands:
            image_path = cands[0]
    if image_path is None or not Path(image_path).is_file():
        _log("TRACE FAIL: no outline file in this folder "
             "(attach an outline image or snap-tool JSON first).")
        return _finish(1)
    image_path = Path(image_path)
    if image_path.suffix.lower() == ".json":
        try:
            data = json.loads(image_path.read_text(encoding="utf-8"))
        except Exception as exc:
            _log(f"TRACE FAIL: outline JSON unreadable: {exc}")
            return _finish(1)
        pts = extract_outline_points_from_json(data)
        if pts is None:
            _log("TRACE FAIL: snap JSON has no calibrated mm "
                 "polygon/points (calibrate in the snap tool "
                 "first, or trace a green-filled image).")
            return _finish(1)
        pts["source_image"] = image_path.name
        (output_dir / "outline_points.json").write_text(
            json.dumps(pts, indent=1, ensure_ascii=False),
            encoding="utf-8")
        _log(f"TRACE OK (snap JSON): {len(pts['points_mm'])} points, "
             f"{len(pts['holes_mm'])} hole(s) -> outline_points.json")
        return _finish(0)
    script = Path(__file__).resolve().parent / "trace_outline.py"
    if not script.is_file():
        _log("TRACE FAIL: trace_outline.py missing next to "
             "run_pipeline.py")
        return _finish(1)
    traced_path = output_dir / "outline_traced.json"
    overlay_path = output_dir / "outline_traced_overlay.png"
    env = dict(os.environ)
    env["TRACE_IMAGE"] = str(image_path)
    env["TRACE_OUT"] = str(traced_path)
    env["TRACE_OVERLAY"] = str(overlay_path)
    if width_mm is not None:
        env["TRACE_WIDTH_MM"] = str(width_mm)
    with open(output_dir / "trace_run.log", "w",
              encoding="utf-8") as log_file:
        subprocess.run([freecadcmd, str(script)],
                       stdout=log_file, stderr=subprocess.STDOUT,
                       env=env)
    if not traced_path.is_file():
        _log("TRACE FAIL: trace_outline.py wrote no output "
             "(see trace_run.log)")
        return _finish(1)
    try:
        data = json.loads(traced_path.read_text(encoding="utf-8"))
    except Exception as exc:
        _log(f"TRACE FAIL: traced output unreadable: {exc}")
        return _finish(1)
    if data.get("error"):
        _log(f"TRACE FAIL: {data['error']}")
        return _finish(1)
    if not data.get("points_mm"):
        _log("TRACE FAIL: traced image has no mm points "
             "(outline width in mm is required for an image "
             "trace; a snap-tool JSON carries its own scale).")
        return _finish(1)
    shutil.copyfile(traced_path, output_dir / "outline_points.json")
    _log(f"TRACE OK: {data.get('point_count')} points, "
         f"{data.get('hole_count')} hole(s), "
         f"bottom_cropped={data.get('bottom_cropped')} -> "
         "outline_points.json (+ outline_traced_overlay.png)")
    return _finish(0)


def build_patch_messages(prompt, outline_image):
    """Patch call messages: text-only when there is no outline
    image (unchanged old behaviour), text + outline image when
    the folder carries one (Nov 1, 2026 user rule: resend the
    outline image on patch, ONLY when it exists). outline_image
    is (base64, mime) or None. No drawing image is sent on patch
    — patch edits an existing macro, it does not re-read the
    drawing."""
    if outline_image is None:
        return [{"role": "user", "content": prompt}]
    b64, mime = outline_image
    return [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "text",
         "text": "Outline image (user-captured outline, from the "
                 "folder's input_outline image — use it to check "
                 "the outline feature's shape against the traced "
                 "points above, not to invent new coordinates):"},
        {"type": "image_url",
         "image_url": {"url": f"data:{mime};base64,{b64}"}},
    ]}]


def run_suggest_mode(output_dir, drawing_path, model, max_tokens,
                     dry_run):
    """Suggest DRAFT answers for questions.txt — nothing else.

    Why this exists (Oct 31, 2026 user request): answering every
    question by hand takes 5+ minutes per round. The LLM already
    powers the pipeline, so let it draft the answers and let the
    user edit + confirm them. This mode NEVER builds, patches,
    or changes the macro, model, questions.txt, or qa_history:
    it only writes suggested_answers.txt (clean Q lines, in
    questions order), suggested_notes.txt (source + confidence
    per question), and suggest_log.txt. The web UI shows the
    draft in an editable box; only the user's Continue press
    turns a draft into an answer (via the normal /answer patch
    path). A draft is therefore never silently applied.

    Sources, in priority order: (1) the drawing image +
    dimensions.json, (2) qa_history.txt already-decided answers
    (a draft must NOT contradict them; a conflict is flagged,
    not silently overridden), (3) current results: macro.py
    provisional values + feature_history.json, (4) calculation
    or a standard, only when the first three do not decide,
    with the calculation shown. The principles file is NOT an
    answer source: it says how to build, not what this part's
    dimensions are, so it must not be used to invent a value.
    If drawing + history + results do not decide a question,
    the draft answer is "결정 필요: <options>" with confidence
    결정필요 — never a fake certainty.
    """
    log_lines = []

    def _log(msg):
        log_lines.append(msg)
        print(msg)

    def _finish(code):
        (output_dir / "suggest_log.txt").write_text(
            "\n".join(log_lines) + "\n", encoding="utf-8")
        return code

    questions_path = output_dir / "questions.txt"
    if not questions_path.is_file():
        _log("SUGGEST FAIL: questions.txt missing in this folder. "
             "Suggest needs pending questions to answer.")
        return _finish(1)
    try:
        question_dict = parse_q_lines(questions_path.read_text(
            encoding="utf-8", errors="replace"))
    except OSError:
        question_dict = {}
    if not question_dict:
        _log("SUGGEST FAIL: questions.txt has no valid Q-lines.")
        return _finish(1)
    if drawing_path is None:
        drawings = sorted(output_dir.glob("input_drawing.*"))
        if not drawings:
            _log("SUGGEST FAIL: no input_drawing.* in this folder.")
            return _finish(1)
        drawing_path = drawings[0]
    if not drawing_path.is_file():
        _log(f"SUGGEST FAIL: drawing not found: {drawing_path}")
        return _finish(1)
    dims_text = ""
    dims_path = output_dir / "dimensions.json"
    if dims_path.is_file():
        try:
            _dims = json.loads(dims_path.read_text(encoding="utf-8"))
            _lines = []
            for _d in _dims:
                _val = _d.get("value", "")
                if _d.get("reference"):
                    _val = f"({_val})"
                _lines.append(f"{_d.get('id', 'D?')}: "
                              f"{_d.get('label', '')} = {_val} mm")
            dims_text = "\n".join(_lines)
        except Exception:
            dims_text = ""
    qa_text = ""
    qa_path = output_dir / "qa_history.txt"
    if qa_path.is_file():
        try:
            qa_text = qa_path.read_text(encoding="utf-8",
                                        errors="replace")[-8000:]
        except OSError:
            qa_text = ""
    hist_text = ""
    hist_path = output_dir / "feature_history.json"
    if hist_path.is_file():
        try:
            hist = json.loads(hist_path.read_text(encoding="utf-8"))
            hist_text = feature_history_report(hist.get("features", []))
        except Exception:
            hist_text = ""
    macro_text = ""
    macro_path = output_dir / "macro.py"
    if macro_path.is_file():
        try:
            macro_text = macro_path.read_text(encoding="utf-8",
                                              errors="replace")
        except OSError:
            macro_text = ""
    questions_text = questions_path.read_text(encoding="utf-8",
                                              errors="replace")
    prompt = (
        "You are drafting SUGGESTED answers to pending questions "
        "about a part drawing. You are NOT building anything and "
        "you are NOT deciding anything: the user will edit and "
        "confirm your draft before it is used. Answer in Korean.\n\n"
        "Sources, in priority order: (1) the drawing image and "
        "the numbered dimensions below, (2) the Q&A history "
        "below — already-decided answers MUST NOT be contradicted; "
        "if a new question conflicts with an old answer, flag the "
        "conflict in Notes instead of silently picking one side, "
        "(3) the current macro's provisional values and the "
        "feature history below (what is already built and what "
        "failed), (4) a calculation or a standard, ONLY when "
        "(1)-(3) do not decide the question, and then show the "
        "calculation. The build principles are NOT an answer "
        "source: never invent a dimension because a principle "
        "says so.\n\n"
        "Output EXACTLY two sections, nothing else:\n"
        "Answers:\n"
        "Q<n>: <one short answer in Korean, with numbers and units>\n"
        "(one line per question, every question covered, in the "
        "same order as the questions)\n"
        "Notes:\n"
        "Q<n>: <source: drawing / Q&A history / current result / "
        "calculation / standard> — <one short sentence> — "
        "확신: 확실 / 계산 / 추측 / 결정필요\n"
        "If drawing + history + results do not decide a question, "
        "its answer MUST be '결정 필요: <options>' and its "
        "confidence 결정필요. Never present a guess as certain.\n\n"
        f"Pending questions:\n{questions_text}\n\n"
        + (f"Numbered dimensions:\n{dims_text}\n\n" if dims_text else "")
        + (f"Q&A history (already decided):\n{qa_text}\n\n"
           if qa_text.strip() else "")
        + (f"Feature history (pipeline-measured):\n{hist_text}\n\n"
           if hist_text else "")
        + (f"Current macro.py (provisional values live here):\n"
           f"```python\n{macro_text}\n```\n" if macro_text else "")
    )
    (output_dir / "suggest_prompt.txt").write_text(prompt,
                                                   encoding="utf-8")
    if dry_run:
        _log("SUGGEST DRY-RUN: prompt written to suggest_prompt.txt, "
             "no API call, no suggestion written")
        return _finish(0)
    api_key = os.environ.get("META_API_KEY") or load_dotenv_key()
    if not api_key:
        _log("SUGGEST FAIL: META_API_KEY is not set (password field "
             "or local .env)")
        return _finish(1)
    mime_type, _enc = mimetypes.guess_type(str(drawing_path))
    if mime_type is None:
        mime_type = "application/octet-stream"
    try:
        image_b64 = base64.b64encode(
            drawing_path.read_bytes()).decode("ascii")
    except OSError as exc:
        _log(f"SUGGEST FAIL: cannot read drawing: {exc}")
        return _finish(1)
    try:
        response_json = call_api(
            api_key, model, max_tokens,
            build_messages(prompt, image_b64, mime_type))
        content = extract_content(response_json)
    except RuntimeError as exc:
        _log(f"SUGGEST FAIL: API error: {exc}")
        return _finish(1)
    (output_dir / "suggest_raw_response.txt").write_text(
        json.dumps(response_json, indent=2, ensure_ascii=False),
        encoding="utf-8")
    # Split Answers: / Notes: sections; only the Answers section
    # becomes suggested_answers.txt (clean Q lines for /answer).
    sections = {}
    current = None
    for line in (content or "").splitlines():
        stripped = line.strip()
        if stripped == "Answers:":
            current = "answers"
            sections[current] = []
            continue
        if stripped == "Notes:":
            current = "notes"
            sections[current] = []
            continue
        if current:
            sections[current].append(line)
    answers = parse_q_lines("\n".join(sections.get("answers", [])))
    missing = [label for label in question_dict
               if label not in answers]
    pasted = [label for label, ans in answers.items()
              if ans == question_dict.get(label)]
    if missing or pasted:
        _log(f"SUGGEST FAIL: draft incomplete (missing: {missing}; "
             f"question-as-answer: {pasted}). Nothing written; "
             "answer manually or retry.")
        return _finish(1)
    ordered = [f"{label}: {answers[label]}"
               for label in question_dict if label in answers]
    (output_dir / "suggested_answers.txt").write_text(
        "\n".join(ordered) + "\n", encoding="utf-8")
    (output_dir / "suggested_notes.txt").write_text(
        "\n".join(sections.get("notes", [])).strip() + "\n",
        encoding="utf-8")
    _log(f"SUGGEST OK: draft for {len(ordered)} question(s) written "
         f"to suggested_answers.txt + suggested_notes.txt. "
         f"Draft only — nothing built, nothing applied.")
    return _finish(0)


def run_patch_mode(output_dir, freecadcmd, model, max_tokens, text,
                   dry_run):
    """Patch the existing macro.py in place — no regeneration.

    Why this mode exists (Oct 31, 2026 user instruction): a
    modification request must NOT regenerate the whole macro.
    The existing macro.py is read, the LLM returns ONLY a JSON
    list of exact-string replacements for the parts the user's
    instructions require, the replacements are applied
    all-or-nothing, and freecadcmd runs ONCE. No drawing is
    re-read, no image is sent (text-only call), no 4-attempt
    loop, no FEATURE_MAP guard consuming attempts, no new
    folder. Cost driver is output size: a diff is a few hundred
    tokens, a full macro is ~17 KB, so this is the part that
    makes a modification fast. On ANY failure (no macro, bad
    patch, safety hit, syntax error, freecadcmd/STEP failure,
    feature gate FAIL) the macro is left exactly as it was
    except for a successful application followed by a failed
    build — in that case macro.prev.py holds the pre-patch
    macro and patch_log.txt says how to restore it. Returns
    0 on a verified patched model, 1 otherwise.
    """
    macro_path = output_dir / "macro.py"
    fcstd_path = output_dir / "model.fcstd"
    step_path = output_dir / "model.step"
    log_lines = []

    def _log(msg):
        log_lines.append(msg)
        print(msg)

    def _finish(code):
        (output_dir / "patch_log.txt").write_text(
            "\n".join(log_lines) + "\n", encoding="utf-8")
        return code

    if not macro_path.is_file():
        _log("PATCH FAIL: macro.py missing in this folder. "
             "Patch needs an existing macro; build once with a "
             "full run first, then patch from that folder.")
        return _finish(1)
    if not (text or "").strip():
        _log("PATCH FAIL: no modification instructions given.")
        return _finish(1)
    macro_text = macro_path.read_text(encoding="utf-8", errors="replace")
    qa_text = ""
    qa_path = output_dir / "qa_history.txt"
    if qa_path.is_file():
        try:
            qa_text = qa_path.read_text(encoding="utf-8",
                                        errors="replace")[-8000:]
        except OSError:
            qa_text = ""
    # Answered-question resolution (Oct 31, 2026, CORRECTED same
    # day): answering and implementing are SEPARATE. The first
    # loop fix tied removal to patch SUCCESS, which was wrong:
    # a gate-FAILED patch left questions.txt untouched, so the
    # result page re-asked Q13-Q20 even though the user had
    # already answered them and qa_history held the answers.
    # Correct rule: a label with a recorded, non-question-matching
    # answer is answered, full stop. It leaves questions.txt
    # BEFORE the patch runs (unless dry-run), whether the patch
    # then succeeds or fails; a failed patch's next step is its
    # gate failures, and the next patch prompt still carries the
    # answers via qa_history, so the LLM can retry implementing
    # them without the user re-answering. History answers are
    # NOT restricted to labels in this instruction: in patch
    # mode questions.txt is static for the folder, so any label
    # answered in qa_history is answered, even on a flip-only
    # patch. Macro comments mentioning Q-numbers are NOT
    # questions.txt and do not drive the banner.
    questions_path = output_dir / "questions.txt"
    question_dict = {}
    if questions_path.is_file():
        try:
            question_dict = parse_q_lines(questions_path.read_text(
                encoding="utf-8", errors="replace"))
        except OSError:
            question_dict = {}
    cleaned_text, answered_from_instructions = clean_patch_instructions(
        text, question_dict)
    answered_from_history = answered_labels_from_qa_history(
        qa_text, question_dict)
    answered_labels = ((answered_from_instructions
                        | answered_from_history)
                       & set(question_dict))
    if answered_labels and not dry_run and questions_path.is_file():
        try:
            _qlines = questions_path.read_text(
                encoding="utf-8", errors="replace").splitlines()
            _kept = [ln for ln in _qlines
                     if not (re.match(r"\s*(Q\d+)\s*:", ln)
                             and re.match(r"\s*(Q\d+)\s*:", ln).group(1)
                             in answered_labels)]
            if _kept:
                questions_path.write_text("\n".join(_kept) + "\n",
                                          encoding="utf-8")
                _log(f"PATCH: answered questions removed from "
                     f"questions.txt (answered, even if this patch "
                     f"later fails): {sorted(answered_labels)}; "
                     f"remaining: {[ln.split(':')[0] for ln in _kept]}")
            else:
                questions_path.unlink()
                _log(f"PATCH: all pending questions answered "
                     f"({sorted(answered_labels)}); questions.txt removed")
        except OSError as exc:
            _log(f"PATCH: questions.txt cleanup failed: {exc}")
    hist_text = ""
    hist_path = output_dir / "feature_history.json"
    if hist_path.is_file():
        try:
            hist = json.loads(hist_path.read_text(encoding="utf-8"))
            fails = [f"{f['feature']} delta {f['delta']}"
                     for f in hist.get("features", [])
                     if f.get("verdict") == "FAIL"]
            hist_text = ("Previous feature-gate FAILs: "
                         + ("; ".join(fails) if fails else "none"))
        except Exception:
            hist_text = ""
    guidance_text = ""
    guidance_path = output_dir / "guidance.txt"
    if guidance_path.is_file():
        try:
            guidance_text = guidance_path.read_text(
                encoding="utf-8", errors="replace")[:2000]
        except OSError:
            guidance_text = ""
    prompt = (
        "You are editing an EXISTING FreeCAD macro. Do NOT write a "
        "new macro, do NOT regenerate the whole file, do NOT "
        "reorder features, do NOT rename features, do NOT change "
        "any dimension, direction, or sketch except what the "
        "modification instructions below require. Chamfer/Fillet "
        "stay LAST in the feature order. If a feature you change "
        "is in FEATURE_MAP, keep the map entry and update only "
        "its changed value.\n\n"
        "Return ONLY one ```json code fence containing a list of "
        "replacements, no other text:\n"
        '[{"old": "<EXACT text copied from the macro, including '
        'indentation>", "new": "<replacement text>"}]\n'
        "Each \"old\" must occur exactly once in the macro; copy "
        "enough surrounding lines to make it unique. Keep each "
        "replacement as small as possible: one feature, one "
        "direction flip, one value, one position — never the "
        "whole file.\n"
        "The instructions below are ANSWERS to questions, not new "
        "questions. Apply them to the provisional values they "
        "answer and do NOT re-ask them, do NOT leave them as "
        "provisional values.\n\n"
        f"Modification instructions:\n{cleaned_text}\n\n"
        + (f"{hist_text}\n\n" if hist_text else "")
        + (f"Previous guidance:\n{guidance_text}\n\n" if guidance_text else "")
        + (f"Q&A history (user-confirmed; do not contradict it):\n"
           f"{qa_text}\n\n" if qa_text.strip() else "")
        + (f"Traced outline points (numeric — the outline "
           f"feature's sketch MUST use these, see the section "
           f"above for the copy rule):\n"
           f"{format_outline_points_text(load_outline_points(output_dir))}\n\n"
           if load_outline_points(output_dir) else "")
        + "Existing macro.py:\n```python\n" + macro_text + "\n```\n"
        + f"Save the patched model to {fcstd_path} and the STEP "
        f"export to {step_path} (the macro already does this; "
        f"do not change its output paths)."
    )
    (output_dir / "patch_prompt.txt").write_text(prompt, encoding="utf-8")
    # Patch resends the outline image — ONLY when the folder
    # carries one (Nov 1, 2026 user rule). Previously patch was
    # text-only, so after the second question round the patch
    # LLM could not see the green outline at all, and "follow
    # the green outline" was words without coordinates. When no
    # outline image exists, the call stays text-only, exactly
    # as before. JSON outlines are not images and are not sent
    # (their numeric points, above, are the usable form).
    _outline_image_patch = None
    for _cand in sorted(output_dir.glob("input_outline.*")) + \
            sorted(output_dir.glob("outline_input.*")):
        if _cand.suffix.lower() in (".png", ".jpg", ".jpeg",
                                    ".webp", ".bmp", ".gif"):
            try:
                _mime, _ = mimetypes.guess_type(str(_cand))
                _outline_image_patch = (
                    base64.b64encode(_cand.read_bytes()).decode("ascii"),
                    _mime or "image/png")
                _log(f"PATCH: outline image resent from {_cand.name}")
            except OSError:
                pass
            break
    if dry_run:
        _log("PATCH DRY-RUN: prompt written to patch_prompt.txt, "
             "no API call, no macro change")
        return _finish(0)
    api_key = os.environ.get("META_API_KEY") or load_dotenv_key()
    if not api_key:
        _log("PATCH FAIL: META_API_KEY is not set (password field "
             "or local .env)")
        return _finish(1)
    try:
        response_json = call_api(
            api_key, model, max_tokens,
            build_patch_messages(prompt, _outline_image_patch))
        content = extract_content(response_json)
    except RuntimeError as exc:
        _log(f"PATCH FAIL: API error: {exc}")
        return _finish(1)
    # Save FULL raw response BEFORE any extraction.
    (output_dir / "patch_raw_response.txt").write_text(
        json.dumps(response_json, indent=2, ensure_ascii=False),
        encoding="utf-8")
    replacements, patch_err = extract_patch_replacements(content)
    if patch_err:
        _log(f"PATCH FAIL: {patch_err}. Macro untouched.")
        return _finish(1)
    new_text, applied, apply_errors = apply_patch_replacements(
        macro_text, replacements)
    if apply_errors:
        _log("PATCH FAIL: replacements did not apply cleanly. "
             "Macro untouched.")
        for err in apply_errors:
            _log(f"  {err}")
        return _finish(1)
    hits = safety_check(new_text)
    if hits:
        _log(f"PATCH FAIL: safety check failed: {hits}. "
             "Macro untouched.")
        return _finish(1)
    try:
        ast.parse(new_text)
    except SyntaxError as exc:
        _log(f"PATCH FAIL: patched macro has a syntax error: {exc}. "
             "Macro untouched.")
        return _finish(1)
    # Backup BEFORE overwriting, in the SAME folder.
    try:
        (output_dir / "macro.prev.py").write_text(macro_text,
                                                  encoding="utf-8")
    except OSError:
        pass
    for _name, _prev in (("model.fcstd", "model.prev.fcstd"),
                         ("model.step", "model.prev.step")):
        _src = output_dir / _name
        if _src.is_file():
            try:
                shutil.copyfile(_src, output_dir / _prev)
            except OSError:
                pass
    macro_path.write_text(new_text, encoding="utf-8")
    _log(f"PATCH: applied {applied} replacement(s) to macro.py "
         f"(backup: macro.prev.py)")
    cleaned = clean_model_outputs(output_dir)
    if cleaned:
        _log(f"PATCH: cleaned stale outputs: {cleaned}")
    run_log = output_dir / "run.log"
    try:
        returncode = run_freecadcmd(freecadcmd, macro_path, run_log)
    except OSError as exc:
        _log(f"PATCH FAIL: freecadcmd run failed: {exc}")
        return _finish(1)
    (output_dir / "run_patch.log").write_text(
        run_log.read_text(encoding="utf-8", errors="replace"),
        encoding="utf-8")
    _log(f"PATCH: freecadcmd exit {returncode}")
    if returncode != 0:
        tail = run_log.read_text(encoding="utf-8",
                                 errors="replace")[-1000:]
        _log(f"PATCH FAIL: freecadcmd exit {returncode}. Log tail:\n{tail}")
        _log("Restore the pre-patch macro with: copy macro.prev.py "
             "over macro.py, then patch again.")
        return _finish(1)
    if fcstd_path.is_file() and not step_path.is_file():
        _log("PATCH: model.fcstd saved but model.step missing; "
             "exporting STEP from the .fcstd instead of failing.")
        if export_step_from_fcstd(freecadcmd, fcstd_path, step_path,
                                  output_dir):
            _log("PATCH: STEP fallback export succeeded.")
        else:
            _log("PATCH FAIL: STEP fallback export failed.")
            return _finish(1)
    if not fcstd_path.is_file() or not step_path.is_file():
        _log(f"PATCH FAIL: output files missing: model.fcstd "
             f"exists={fcstd_path.is_file()}, model.step "
             f"exists={step_path.is_file()}")
        return _finish(1)
    verification = verify_step(freecadcmd, step_path, output_dir)
    _log(f"PATCH: verification: {verification}")
    if not verification.get("ok"):
        _log("PATCH FAIL: STEP verification snippet failed "
             "(see verify.log).")
        return _finish(1)
    if verification["solids"] != 1 or not verification["valid"]:
        _log(f"PATCH FAIL: solids must be exactly 1 and valid True; "
             f"got solids={verification['solids']}, "
             f"valid={verification['valid']}")
        return _finish(1)
    _checks = parse_check_lines(run_log.read_text(encoding="utf-8",
                                                  errors="replace"))
    _history = evaluate_feature_history(_checks)
    if _history:
        (output_dir / "feature_history.json").write_text(
            json.dumps({"attempt": "patch", "features": _history},
                       indent=2, ensure_ascii=False), encoding="utf-8")
        _log("PATCH: feature history:\n" + feature_history_report(_history))
        _failed = [r for r in _history if r["verdict"] == "FAIL"]
        if _failed:
            _log("PATCH FAIL: feature volume gate FAIL: "
                 + "; ".join(f"{r['feature']} delta {r['delta']} "
                             f"({r['reason']})" for r in _failed)
                 + ". Patch again with only those features changed; "
                 "no auto-retry is run in patch mode.")
            # Table JSON keeps existing even on a gate failure:
            # the failed model's values are still worth showing.
            try:
                _n = ensure_matching_file(
                    output_dir, freecadcmd, macro_text=new_text,
                    verification=verification)
                if _n > 0:
                    _log(f"PATCH: matching.json ensured ({_n} rows, "
                         f"even on failure)")
            except Exception:
                pass
            return _finish(1)
    # Fresh previews + feature tree after a patch, best-effort:
    # the result page must show the PATCHED model, not stale
    # images/tree from before the patch.
    try:
        _pok, _pnote = render_previews(output_dir)
        _log(f"PATCH: previews refreshed: {_pnote if _pok else 'unavailable'}")
    except Exception as exc:
        _log(f"PATCH: preview refresh failed (best-effort): {exc}")
    try:
        if run_read_features(freecadcmd, fcstd_path, output_dir) is not None:
            _log("PATCH: features.json refreshed from patched .fcstd")
    except Exception as exc:
        _log(f"PATCH: features refresh failed (best-effort): {exc}")
    # Answered questions were already removed from questions.txt
    # BEFORE the patch ran (see above), so nothing is left to
    # clean up here on success; unanswered questions stay.
    # Outline check (log-only, never a gate) on patch success.
    try:
        _op = load_outline_points(output_dir)
        _pts = (_op or {}).get("points_mm") if _op else None
        if _pts:
            _m, _t = outline_text_check(new_text, _pts)
            _log(f"PATCH: outline check: {_m}/{_t} traced points "
                 "appear in patched macro text (per-line, ±0.05 mm; "
                 "B-spline control points may differ, hint only)")
    except Exception:
        pass
    # Point 2 (Nov 1, 2026 user rule): a successful patch must
    # not leave the table missing — build it if it is absent.
    try:
        _n = ensure_matching_file(output_dir, freecadcmd,
                                  macro_text=new_text,
                                  verification=verification)
        if _n > 0:
            _log(f"PATCH: matching.json ensured ({_n} rows)")
    except Exception:
        pass
    report_lines = [
        "Drawing-to-Parametric-CAD orchestrator v0.1",
        "PATCH MODE: existing macro.py patched in place, 1 API call, "
        "1 freecadcmd run, no new folder, no regeneration.",
        f"PATCH: applied {applied} replacement(s).",
        f"PATCH verification: {verification}",
        "RESULT: PATCH COMPLETE",
    ]
    write_report(output_dir / "report.txt", report_lines)
    _log("RESULT: PATCH COMPLETE")
    return _finish(0)


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
    parser.add_argument("--drawing", default="",
                        help="Drawing image file (read, never copied into the repo). "
                        "Required unless --measure is given.")
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
    parser.add_argument("--measure", action="store_true",
                        help="Measure an existing result folder instead of "
                        "building: run measure_step.py on its model.step "
                        "and add a measured column to matching.json. "
                        "Needs only --output-dir (+ --freecadcmd); no "
                        "drawing, no API call.")
    parser.add_argument("--inspect", action="store_true",
                        help="Inspect an existing result folder instead of "
                        "building: check every FEATURE_MAP / matching "
                        "feature against the current .fcstd + STEP, "
                        "write feature_check.txt/.json, and append a "
                        "compact entry to feature_check_history.txt. "
                        "NEVER a failure gate: it returns 0 even when "
                        "checks miss, and it never rebuilds or changes "
                        "the model, macro, or report.txt. Needs only "
                        "--output-dir (+ --freecadcmd); no drawing, "
                        "no API call.")
    parser.add_argument("--remap", action="store_true",
                        help="Repair an existing result folder's "
                        "FEATURE_MAP without rebuilding the model: "
                        "ask the LLM (one short call) for a FEATURE_MAP "
                        "only, from the folder's D-list + .fcstd dump, "
                        "validate it against the dump, save mapping.json, "
                        "and rebuild matching.json. The model, macro, "
                        "and report.txt are never changed. Needs only "
                        "--output-dir (+ --freecadcmd); with --dry-run "
                        "it writes remap_prompt.txt and calls no API.")
    parser.add_argument("--images", action="store_true",
                        help="Re-render preview images from the CURRENT "
                        "model.step in an existing folder (web "
                        "\"Extract images\" button): verify_step "
                        "rewrites tris.json, then preview PNGs are "
                        "rendered with the XYZ triad. No API call, "
                        "no model/macro/report change. Needs only "
                        "--output-dir (+ --freecadcmd).")
    parser.add_argument("--suggest", action="store_true",
                        help="Suggest DRAFT answers for an existing "
                        "folder's questions.txt (web \"Suggest "
                        "answers\" button): one LLM call with the "
                        "drawing + dimensions + Q&A history + "
                        "current results, writing only "
                        "suggested_answers.txt + suggested_notes.txt. "
                        "No macro, model, questions.txt, or "
                        "qa_history change; a draft is never "
                        "applied until the user edits + confirms it "
                        "via /answer. With --dry-run it writes "
                        "suggest_prompt.txt and calls no API.")
    parser.add_argument("--trace-outline", action="store_true",
                        help="Trace step: outline image/JSON in "
                        "--output-dir (or --outline) -> "
                        "outline_points.json (numeric mm points "
                        "for later prompts). Image traces need "
                        "--outline-width-mm; snap-tool JSON "
                        "carries its own scale. No rebuild, no "
                        "API call, model/macro/report unchanged.")
    parser.add_argument("--outline-width-mm", type=float, default=None,
                        help="Real width (mm) of the outline image "
                        "for tracing: scale = width / outline "
                        "pixel width, X = 0 at outline centre. "
                        "Required for image traces; ignored for "
                        "snap-tool JSON (it is calibrated).")
    parser.add_argument("--build-table", action="store_true",
                        help="Build (or rebuild) matching.json without "
                        "rebuilding the model (web matching tab's "
                        "\"표 만들기\" button): D-rows from "
                        "dimensions.json, FEATURE_MAP from "
                        "mapping.json or macro.py, modeling values "
                        "from the current .fcstd + STEP. No API "
                        "call, no macro/model/report change; "
                        "measured columns are preserved by D-number.")
    parser.add_argument("--patch", action="store_true",
                        help="Patch an existing result folder's macro.py "
                        "in place instead of regenerating it: one "
                        "text-only LLM call returns only JSON "
                        "replacements for the parts --text requires, "
                        "they are applied all-or-nothing to macro.py "
                        "(backup macro.prev.py in the same folder), "
                        "then freecadcmd runs ONCE and the STEP is "
                        "verified (feature volume gate still applies, "
                        "but there is no auto-retry). Needs only "
                        "--output-dir (+ --freecadcmd) and --text; "
                        "no drawing, no image, no new folder. With "
                        "--dry-run it writes patch_prompt.txt and "
                        "calls no API.")
    return parser.parse_args(argv)


def main(argv=None):
    # Windows trap (Oct 30, 2026, real home failure): Windows Python
    # defaults redirected stdout to cp1252, so ANY non-ASCII print
    # (the "Measurement (실측)" summary) raises UnicodeEncodeError
    # and kills the run AFTER the work is done. Force UTF-8 here so
    # no print can crash on language again; web_ui additionally
    # sets PYTHONUTF8=1 for its subprocesses.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    args = parse_args(argv)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.measure:
        return run_measure_mode(output_dir, args.freecadcmd)
    if args.inspect:
        return run_inspect_mode(output_dir, args.freecadcmd)
    if args.remap:
        return run_remap_mode(output_dir, args.freecadcmd, args.model,
                              args.max_tokens, args.dry_run)
    if args.trace_outline:
        _img = Path(args.outline) if args.outline else None
        return run_trace_outline_mode(output_dir, args.freecadcmd,
                                      _img, args.outline_width_mm)
    if args.build_table:
        return run_build_table_mode(output_dir, args.freecadcmd)
    if args.suggest:
        _drawing = Path(args.drawing) if args.drawing else None
        return run_suggest_mode(output_dir, _drawing, args.model,
                                args.max_tokens, args.dry_run)
    if args.patch:
        return run_patch_mode(output_dir, args.freecadcmd, args.model,
                              args.max_tokens, args.text, args.dry_run)
    if args.images:
        return run_images_mode(output_dir, args.freecadcmd)
    if not args.drawing:
        die("--drawing is required unless --measure, --inspect, --remap, --patch, --images, --suggest, --build-table, or --trace-outline is given.")
    report_lines = ["Drawing-to-Parametric-CAD orchestrator v0.1"]
    self_fix_log = output_dir / "self_fix_log.txt"
    if self_fix_log.exists():
        self_fix_log.unlink()
    # A new run starts with NO questions: a previous run's (or a
    # previous attempt's) questions.txt must never drive this run's
    # banner. New questions, if any, are written by write_questions()
    # below; qa_history.txt (not questions.txt) carries history.
    _qf = output_dir / "questions.txt"
    if _qf.is_file():
        try:
            _qf.unlink()
        except OSError:
            pass

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

    # Traced outline points (Nov 1, 2026 user rule): an image
    # alone is eyeballed and mis-copied, so when numeric points
    # exist they go into EVERY prompt of this run (base + retry,
    # via outline_text) as coordinates to copy. JSON outlines
    # carry their own calibration; image outlines are traced
    # only when an outline width in mm is given (without a
    # scale, px points must never be presented as mm). Tracing
    # is best-effort here: a trace failure never fails the
    # build, it just leaves the image-only behaviour + a note.
    outline_points_data = None
    if args.outline and outline_suffix.lower() == ".json":
        try:
            outline_points_data = extract_outline_points_from_json(
                outline_data)
        except Exception:
            outline_points_data = None
        if outline_points_data is not None:
            outline_points_data["source_image"] = outline_path.name
            (output_dir / "outline_points.json").write_text(
                json.dumps(outline_points_data, indent=1,
                           ensure_ascii=False), encoding="utf-8")
            report_lines.append(
                f"Outline trace: snap JSON -> outline_points.json "
                f"({len(outline_points_data['points_mm'])} points)")
    elif args.outline and outline_image is not None \
            and args.outline_width_mm is not None:
        try:
            if run_trace_outline_mode(
                    output_dir, args.freecadcmd, outline_path,
                    args.outline_width_mm) == 0:
                outline_points_data = load_outline_points(output_dir)
                report_lines.append(
                    "Outline trace: image -> outline_points.json "
                    "(see trace_log.txt)")
            else:
                report_lines.append(
                    "Outline trace: FAILED (see trace_log.txt); "
                    "continuing with the outline image only.")
        except Exception as exc:
            report_lines.append(
                f"Outline trace: skipped ({exc}); continuing with "
                "the outline image only.")
    _points_text = format_outline_points_text(outline_points_data)
    if _points_text:
        outline_text = (outline_text + "\n\n" + _points_text
                        if outline_text else _points_text)

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
        if questions and write_questions(output_dir, questions):
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
            # Unformatted / non-question response: NEVER dump it
            # into questions.txt (that is how a whole macro ended
            # up in the question window). Keep it visible in
            # guidance.txt + raw_response.txt, leave questions.txt
            # empty, and say so plainly. The Continue form is
            # always shown, so this is not a dead end.
            write_questions(output_dir, [])
            (output_dir / "guidance.txt").write_text(
                "ASK-FIRST response was not questions (code/prose, "
                "not Q-lines). See raw_response.txt for the full "
                "response. Press Continue work to retry or build.\n\n"
                + content.strip() + "\n", encoding="utf-8")
            report_lines.append(
                "RESULT: ASK-FIRST INVALID RESPONSE (not questions, "
                "see guidance.txt, no model built yet)")
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
    # Previous attempt's artifacts, for the next attempt's diagnosis.
    # Reset at the start of each retry (below) and filled in only
    # when that attempt actually runs freecadcmd / verification, so
    # a safety/API failure is never diagnosed from an older run's log.
    prev_run_log_text = ""
    prev_verification = None
    prev_feature_history = []
    prev_ran = False
    for attempt in range(1, MAX_ATTEMPTS + 1):
        append_log(self_fix_log,
                   f"Attempt {attempt}/{MAX_ATTEMPTS} started.")
        if attempt == 1:
            prompt_text = base_prompt
        else:
            # Diagnose -> category reference -> retry: the diagnosis
            # is built from the previous attempt's ACTUAL artifact
            # (its freecadcmd log + verification + .fcstd features),
            # never from the error message alone, and the matched
            # reference file(s) go into the prompt's Reference part
            # (after the instruction, before the output paths -- see
            # build_prompt). Attempt 4 always gets the full set.
            last_diagnosis = build_diagnosis(
                prev_run_log_text, prev_verification, last_error,
                fcstd_path)
            retry_categories = select_retry_categories(last_diagnosis,
                                                       attempt)
            reference_text, reference_notes = load_reference_texts(
                retry_categories)
            for note in reference_notes:
                append_log(self_fix_log, f"Attempt {attempt}: {note}")
            append_log(self_fix_log,
                       f"Attempt {attempt}: {last_diagnosis['report']}")
            append_log(self_fix_log,
                       f"Attempt {attempt}: categories: {retry_categories}")
            retry_prompt = build_prompt(
                principles_text, gear_text, args.text, output_dir,
                outline_text, reference_text=reference_text)
            _hist_text = (feature_history_report(prev_feature_history)
                          if prev_feature_history else
                          "no CHECK lines recorded")
            prompt_text = (
                retry_prompt
                + "\n\nPrevious attempt failed with this exact error:\n"
                + last_error
                + "\n" + last_diagnosis["report"]
                + "\nFeature history (pipeline-measured from CHECK "
                + "volumes, not the LLM's own PASS claims):\n"
                + _hist_text
                + "\nKeep every OK feature exactly as it was (same "
                + "direction, same dimensions, same sketch). Change "
                + "ONLY FAIL features. Do not repeat a direction that "
                + "already gave delta 0 for that feature. If a feature "
                + "already failed with both Reversed values, ask a "
                + "question instead of guessing again."
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
            # Reset previous-attempt artifacts for this attempt.
            prev_run_log_text = ""
            prev_verification = None
            prev_feature_history = []
            prev_ran = False
        # Stale-output guard: delete any previous attempt's model
        # outputs BEFORE this attempt, so verification below can
        # never read a stale STEP and pass/fail the wrong attempt.
        cleaned = clean_model_outputs(output_dir)
        if cleaned:
            append_log(self_fix_log,
                       f"Attempt {attempt}: cleaned stale outputs: {cleaned}")
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
            # Write ONLY validated Q-lines to questions.txt.
            # The old fallback wrote the whole response here when
            # no Q-lines were found, which is how a fenceless macro
            # ended up in the question window. The full response
            # stays visible in guidance.txt + raw_response.txt.
            # The Continue form is always shown, so an empty
            # questions.txt is not a dead end.
            _qs = extract_questions(content, "")
            write_questions(output_dir, _qs)
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
        # write_questions() validates AND deletes any stale
        # questions.txt when this attempt asked nothing, so a
        # clean final attempt can never inherit an earlier
        # attempt's questions (and its banner).
        if write_questions(output_dir, questions):
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

        # FEATURE_MAP guard (Oct 30, 2026 home gear run): a macro
        # that builds correct geometry but writes no FEATURE_MAP
        # leaves every D-row "?" (no FEATURE_MAP entry). That is a
        # self-fixable code omission, not a model failure: retry
        # the attempt with an explicit instruction to add the map
        # for the CURRENT D-list, before spending a FreeCAD run.
        # On the last attempt the guard is skipped, so a correct
        # model is never discarded for a missing map alone. When
        # there is no numbered D-list at all, there is nothing to
        # cover and the guard is skipped.
        _map_guard, _map_warn = extract_feature_map(macro_text)
        _d_ids_guard = [d["id"] for d in
                        parse_numbered_dimensions(args.text or "")]
        if _d_ids_guard and attempt < MAX_ATTEMPTS:
            _missing_guard = [d for d in _d_ids_guard
                              if d not in _map_guard]
            if _missing_guard:
                last_error = (
                    f"FEATURE_MAP incomplete: missing "
                    f"{', '.join(_missing_guard)} "
                    f"({_map_warn or 'map present but incomplete'}). "
                    f"Add a FEATURE_MAP at the top of the macro "
                    f"mapping EVERY D-number in the current "
                    f"dimension list to its sketch/feature, using "
                    f"the feature name exactly as created in the "
                    f"macro (kind + sketch where needed). Do not "
                    f"change any dimension, feature, or geometry.")
                append_log(self_fix_log,
                           f"Attempt {attempt}: {last_error}")
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
        prev_run_log_text = run_log.read_text(encoding="utf-8",
                                              errors="replace")
        prev_ran = True
        append_log(self_fix_log,
                   f"Attempt {attempt}: freecadcmd exit {returncode}.")
        if returncode != 0:
            tail = run_log.read_text(encoding="utf-8", errors="replace")[-1000:]
            last_error = f"freecadcmd exit {returncode}. Log tail:\n{tail}"
            append_log(self_fix_log, f"Attempt {attempt}: {last_error}")
            continue
        # STEP fallback (Oct 31, 2026 item 4): a macro's in-macro
        # check_gate() saves .fcstd on EVERY feature but STEP is
        # exported only at the very end, so a gate raise before
        # the end leaves fcstd present and step missing (182125
        # attempt 4 exactly). That is a macro-abort, not a STEP
        # export failure — and it got more common as gate raises
        # were added to macros. Export STEP from the .fcstd here
        # instead of failing the whole attempt for a missing
        # export; verification and the volume gate below still
        # decide pass/fail, so a partial model is never passed.
        if fcstd_path.is_file() and not step_path.is_file():
            append_log(self_fix_log,
                       f"Attempt {attempt}: model.fcstd saved but "
                       f"model.step missing; exporting STEP from "
                       f"the .fcstd instead of failing.")
            if export_step_from_fcstd(args.freecadcmd, fcstd_path,
                                      step_path, output_dir):
                append_log(self_fix_log,
                           f"Attempt {attempt}: STEP fallback "
                           f"export succeeded.")
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
        prev_verification = verification
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

        # Per-feature volume gate (see evaluate_feature_history).
        # This runs AFTER the STEP gate and BEFORE any MODELING
        # COMPLETE declaration, so a final solid that is 1 + valid
        # can still fail when a Pocket cut air. Macros without
        # CHECK lines skip this gate (no false failure for them).
        _checks = parse_check_lines(run_log.read_text(
            encoding="utf-8", errors="replace"))
        _history = evaluate_feature_history(_checks)
        prev_feature_history = _history
        if _history:
            (output_dir / "feature_history.json").write_text(
                json.dumps({"attempt": attempt, "features": _history},
                           indent=2, ensure_ascii=False), encoding="utf-8")
            append_log(self_fix_log,
                       f"Attempt {attempt}: feature history:\n"
                       + feature_history_report(_history))
            _failed = [r for r in _history if r["verdict"] == "FAIL"]
            if _failed:
                last_error = (
                    "Feature volume gate FAIL: "
                    + "; ".join(
                        f"{r['feature']} delta {r['delta']} "
                        f"({r['reason']})" for r in _failed)
                    + ". A macro log PASS alone is not a pass; a "
                    "Pocket with delta 0 cut air."
                )
                append_log(self_fix_log,
                           f"Attempt {attempt}: {last_error}")
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
        # run — the .fcstd / STEP files are the result. Same helper
        # as --images, so previews always carry the XYZ triad.
        preview_ok, preview_note = render_previews(output_dir)
        if preview_ok:
            report_lines.append(f"Previews: {preview_note}")
        else:
            report_lines.append(f"Previews: unavailable ({preview_note})")
        # Drawing-vs-modeling matching table (matching.json + report
        # lines). Drawing values are the LLM's reading from the
        # drawing (D-dimensions from --text when present). Modeling
        # values are read from the .fcstd feature dump via the
        # macro's FEATURE_MAP (see MAPPING_DESIGN.md); a dimension
        # without a mapping entry shows ?, never a guessed value.
        try:
            mapping, map_warn = extract_feature_map(macro_text)
            (output_dir / "mapping.json").write_text(
                json.dumps(mapping, indent=2, ensure_ascii=False),
                encoding="utf-8")
            if map_warn:
                report_lines.append(f"Mapping: {map_warn}")
            features_data = run_read_features(args.freecadcmd, fcstd_path,
                                              output_dir)
            if features_data is None:
                report_lines.append(
                    "Mapping: features unreadable (modeling rows "
                    "will show ?)")
            try:
                d_ids = {d["id"] for d in
                         parse_numbered_dimensions(args.text or "")}
                extra = sorted(set(mapping) - d_ids)
                if extra:
                    report_lines.append(
                        "Mapping: entries without a D-row (ignored): "
                        + ", ".join(extra))
            except Exception:
                pass
            matching_rows = build_matching(verification, macro_text,
                                           args.text, mapping=mapping,
                                           features=features_data)
            (output_dir / "matching.json").write_text(
                json.dumps(matching_rows, indent=2, ensure_ascii=False),
                encoding="utf-8")
            for row in matching_rows:
                method = row.get("modeling_method")
                method_txt = f" | via {method}" if method else ""
                report_lines.append(
                    f"Matching: {row['no']} | {row['item']} | "
                    f"drawing={row['drawing']} | "
                    f"modeling={row['modeling']} | {row['result']}"
                    f"{method_txt}")
        except Exception as exc:
            report_lines.append(f"Matching: unavailable ({exc})")
        # Outline check (log-only, never a gate): did the built
        # macro actually copy the traced points?
        try:
            _pts = (outline_points_data or {}).get("points_mm") \
                if outline_points_data else None
            if _pts:
                _m, _t = outline_text_check(macro_text, _pts)
                report_lines.append(
                    f"Outline check: {_m}/{_t} traced points appear "
                    "in macro text (per-line, ±0.05 mm; B-spline "
                    "control points may differ, so this is a hint, "
                    "not a gate)")
        except Exception:
            pass
        # Point 2 (Nov 1, 2026 user rule): a later successful
        # build must not leave the table missing. If the block
        # above did not leave D-rows (exception, no map, no
        # D source in --text), build them from dimensions.json
        # / old rows instead of leaving matching.json absent.
        if not _matching_has_d_rows(output_dir):
            try:
                _n = ensure_matching_file(
                    output_dir, args.freecadcmd, macro_text=macro_text,
                    verification=verification, features=features_data)
                if _n > 0:
                    report_lines.append(
                        f"Matching: matching.json ensured ({_n} rows)")
            except Exception:
                pass
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

    # 4th failure: STOP, guide, do NOT run a 5th time.
    final_diagnosis = build_diagnosis(
        prev_run_log_text, prev_verification, last_error, fcstd_path)
    guidance = (
        "GUIDANCE (4th failure, stopped - no 5th run):\n"
        f"Feature/geometry: {last_feature}\n"
        f"Exact error: {last_error}\n"
        "Cause hypothesis: see self_fix_log.txt for the per-attempt "
        "errors; the last error above is the current cause.\n"
        f"{final_diagnosis['report']}\n"
        "What was tried: 4 attempts total (first generation + up to "
        "3 regenerations with the exact error, diagnosis, and "
        "matched reference fed back). "
        "See self_fix_log.txt.\n"
        "Question/alternative: fix the error above in the macro, or "
        "answer the design question if the error is a missing or "
        "ambiguous dimension. Do not retry without that fix/answer.\n"
    )
    (output_dir / "guidance.txt").write_text(guidance, encoding="utf-8")
    # Point 1 (Nov 1, 2026 user rule): the table JSON must keep
    # existing, even on failure. A failed build still leaves a
    # matching.json (D-rows with ? where unknown) so the tab is
    # never empty for a missing-file reason.
    try:
        _n = ensure_matching_file(output_dir, args.freecadcmd)
        if _n > 0:
            report_lines.append(
                f"Matching: matching.json ensured ({_n} rows, "
                f"even on failure)")
    except Exception:
        pass
    report_lines.append("RESULT: FAIL - 4th failure, see guidance.txt")
    write_report(output_dir / "report.txt", report_lines)
    print(guidance)
    return 1


if __name__ == "__main__":
    sys.exit(main())
