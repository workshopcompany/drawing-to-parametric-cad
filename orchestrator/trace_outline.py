#!/usr/bin/env python3
"""Trace a user-captured outline image into numeric mm points.

Run under freecadcmd (its bundled Python carries PIL, which the
web server's stdlib-only Python may not): the caller sets
TRACE_IMAGE, TRACE_OUT, TRACE_WIDTH_MM (optional), TRACE_TOL_PX
(optional, default 3), TRACE_OVERLAY (optional path) in the
environment and runs `freecadcmd trace_outline.py`. Exit code
from freecadcmd is unreliable, so the caller checks that the
output file exists and has no "error" key.

Input: a filled outline image. v1 supports one fill colour:
bright green dominant pixels (G >= 100, G - R >= 40, G - B >= 40)
— the fill colour the snap tool and the hand-painted bracket
outline both use. Red/blue paint edge strokes are NOT green
dominant, so they are ignored, not traced.

Method (no OpenCV, no numpy — PIL + stdlib only):
1. Green mask from RGB pixels.
2. Largest green region's outer boundary by Moore-Neighbour
   tracing (8-connected foreground). Top-open notches (slots
   open to the background, as in the bracket crown) are part of
   this outer boundary, so they are traced, not lost.
3. Enclosed white regions (fully surrounded by green) are
   traced the same way and reported as "holes" (closed voids).
4. Douglas-Peucker simplification (tolerance in px) so the
   point list is sketch-sized, not a per-pixel staircase.
5. Pixel -> mm: X = (px - bbox_centre_x) * scale, Y =
   (bbox_bottom_y - py) * scale, scale = width_mm / bbox_width_px.
   X = 0 is the outline's own centre; Y = 0 is the outline's
   bottom. If the green touches the image bottom edge, the
   bottom is a crop, NOT a shape edge, and "bottom_cropped"
   is true — the caller must close the profile at the real
   datum (e.g. the crown base) instead of trusting Y = 0 as a
   design edge.

Output JSON (TRACE_OUT):
- points_mm: [[x, y], ...] in contour order (closed loop;
  repeat the first point at the end is NOT added — the loop
  closes back to the first point).
- holes_mm: list of closed loops, same convention.
- px_bbox, mm_bbox, scale_mm_per_px, width_mm, bottom_cropped,
  point_count, tolerance_px, source_image.
Without TRACE_WIDTH_MM the points are in pixels (points_px,
scale_mm_per_px null) and must NOT be presented as mm — the
caller treats an unscaled trace as shape-only, never as sizes.
On any failure the output is {"error": "..."} so the caller
can report it plainly instead of inventing points.
"""

import json
import os
import sys
from collections import deque

# Clockwise neighbour order in image coordinates (x right, y down):
# E, SE, S, SW, W, NW, N, NE. On screen (y down) this order is
# clockwise, which is what Moore tracing needs.
_DIRS = [(1, 0), (1, 1), (0, 1), (-1, 1),
          (-1, 0), (-1, -1), (0, -1), (1, -1)]


def _is_green(r, g, b):
    return g >= 100 and g - r >= 40 and g - b >= 40


def _moore_trace(mask, w, h, start):
    """Trace the outer boundary of one 8-connected region.

    mask: flat list of bool, row-major. start: (x, y) of the
    region's topmost, then leftmost pixel. Returns the boundary
    pixel list in order (no repeated closing point).
    """
    sx, sy = start
    contour = [(sx, sy)]
    # Backtrack pixel is west of start (background: start is
    # leftmost in its row, so west is outside the region).
    back_dir = 4  # W: direction from current to backtrack pixel
    cx, cy = sx, sy
    # Safety bound: a boundary cannot visit more pixels than
    # there are foreground pixels plus a margin.
    limit = w * h + 10
    for _ in range(limit):
        # Examine neighbours clockwise, starting just after the
        # backtrack direction.
        found = None
        for k in range(8):
            d = (back_dir + 1 + k) % 8
            dx, dy = _DIRS[d]
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < w and 0 <= ny < h and mask[ny * w + nx]:
                found = (nx, ny, d)
                break
        if found is None:
            break
        nx, ny, d = found
        # Backtrack for the next step is the reverse direction:
        # the pixel we came from, seen from the new current pixel.
        back_dir = (d + 4) % 8
        if (nx, ny) == (sx, sy):
            # Back at start after a real lap: stop. (The earlier
            # version required back_dir == W here, which never
            # happens on a clockwise lap — arrival is from the
            # south — so it traced ~111 laps until the safety
            # bound. A start revisit with only a few points is a
            # spur, not a lap, so keep going in that case.)
            if len(contour) > 20:
                break
            cx, cy = nx, ny
            continue
        contour.append((nx, ny))
        cx, cy = nx, ny
    return contour


def _douglas_peucker(pts, tol):
    """Simplify an open polyline. Closed loops are split at
    their farthest point and simplified as two open polylines
    by the caller (see _simplify_closed)."""
    if len(pts) <= 2:
        return list(pts)
    # Iterative stack version (no recursion-depth risk).
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        x1, y1 = pts[a]
        x2, y2 = pts[b]
        dx, dy = x2 - x1, y2 - y1
        norm = (dx * dx + dy * dy) ** 0.5
        far_i, far_d = -1, 0.0
        for i in range(a + 1, b):
            x, y = pts[i]
            if norm == 0:
                d = ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
            else:
                d = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / norm
            if d > far_d:
                far_d, far_i = d, i
        if far_d > tol:
            keep[far_i] = True
            stack.append((a, far_i))
            stack.append((far_i, b))
    return [p for p, k in zip(pts, keep) if k]


def _simplify_closed(pts, tol):
    """Simplify a closed loop (first point NOT repeated at end)."""
    if len(pts) <= 3:
        return list(pts)
    # Split at the point farthest from the first point.
    x0, y0 = pts[0]
    far = max(range(len(pts)),
              key=lambda i: (pts[i][0] - x0) ** 2 + (pts[i][1] - y0) ** 2)
    a = _douglas_peucker(pts[:far + 1], tol)
    b = _douglas_peucker(pts[far:] + [pts[0]], tol)
    # Join without duplicating the split points.
    out = a + b[1:-1]
    return out


def _flood_exterior(mask, w, h):
    """Background pixels reachable from the image border."""
    exterior = bytearray(w * h)
    dq = deque()
    for x in range(w):
        for y in (0, h - 1):
            i = y * w + x
            if not mask[i] and not exterior[i]:
                exterior[i] = 1
                dq.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            i = y * w + x
            if not mask[i] and not exterior[i]:
                exterior[i] = 1
                dq.append((x, y))
    while dq:
        x, y = dq.popleft()
        for dx, dy in _DIRS:
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h:
                i = ny * w + nx
                if not mask[i] and not exterior[i]:
                    exterior[i] = 1
                    dq.append((nx, ny))
    return exterior


def _trace_holes(mask, w, h, exterior):
    """Trace each enclosed white region's boundary (holes)."""
    seen = bytearray(w * h)
    holes = []
    for y in range(h):
        for x in range(w):
            i = y * w + x
            if mask[i] or exterior[i] or seen[i]:
                continue
            # One enclosed component: BFS to find its pixels,
            # then its topmost-leftmost pixel as trace start.
            comp = []
            dq = deque([(x, y)])
            seen[i] = 1
            while dq:
                cx, cy = dq.popleft()
                comp.append((cx, cy))
                for dx, dy in _DIRS:
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < w and 0 <= ny < h:
                        j = ny * w + nx
                        if not mask[j] and not exterior[j] and not seen[j]:
                            seen[j] = 1
                            dq.append((nx, ny))
            if len(comp) < 9:
                continue
            start = min(comp, key=lambda p: (p[1], p[0]))
            # Trace the hole boundary on the white set itself:
            # temporarily treat white as foreground by tracing
            # on the inverted mask restricted to this component
            # is complex; instead trace the green boundary around
            # the hole by Moore-tracing the white component and
            # reporting those pixels (they sit just inside the
            # hole edge, within 1 px of the green edge).
            white = bytearray(w * h)
            for (px, py) in comp:
                white[py * w + px] = 1
            holes.append(_moore_trace(white, w, h, start))
    return holes


def main():
    image_path = os.environ.get("TRACE_IMAGE", "")
    out_path = os.environ.get("TRACE_OUT", "")
    width_txt = os.environ.get("TRACE_WIDTH_MM", "")
    tol_txt = os.environ.get("TRACE_TOL_PX", "3")
    overlay_path = os.environ.get("TRACE_OVERLAY", "")
    result = {}

    def _fail(msg):
        result["error"] = msg
        if out_path:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=1, ensure_ascii=False)
        print(f"TRACE FAIL: {msg}")
        return 0

    if not image_path or not os.path.isfile(image_path):
        return _fail(f"outline image not found: {image_path}")
    if not out_path:
        return _fail("TRACE_OUT not set")
    try:
        tol = float(tol_txt)
    except ValueError:
        tol = 3.0
    width_mm = None
    if width_txt:
        try:
            width_mm = float(width_txt)
        except ValueError:
            return _fail(f"bad TRACE_WIDTH_MM: {width_txt}")
        if width_mm <= 0:
            return _fail("TRACE_WIDTH_MM must be positive")
    try:
        from PIL import Image, ImageDraw
    except Exception as exc:
        return _fail(f"PIL not available in this Python ({exc}); "
                     "trace needs FreeCAD's bundled Python (PIL) "
                     "or pip install Pillow")
    try:
        img = Image.open(image_path).convert("RGB")
    except Exception as exc:
        return _fail(f"cannot open outline image: {exc}")
    w, h = img.size
    px = img.load()
    mask = bytearray(w * h)
    green_count = 0
    for y in range(h):
        base = y * w
        for x in range(w):
            r, g, b = px[x, y]
            if _is_green(r, g, b):
                mask[base + x] = 1
                green_count += 1
    if green_count < max(100, w * h // 100):
        return _fail(
            f"green fill too small to trace ({green_count} px of "
            f"{w * h}; need a green-filled outline, or attach a "
            "snap-tool JSON instead)")
    # Outer boundary: start at topmost, then leftmost green pixel.
    start = None
    for y in range(h):
        for x in range(w):
            if mask[y * w + x]:
                start = (x, y)
                break
        if start is not None:
            break
    contour = _moore_trace(mask, w, h, start)
    if len(contour) < 4:
        return _fail("traced contour too short (shape too small?)")
    simple = _simplify_closed(contour, tol)
    xs = [p[0] for p in simple]
    ys = [p[1] for p in simple]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    bottom_cropped = any(py >= h - 1 for (_, py) in simple)
    exterior = _flood_exterior(mask, w, h)
    holes_px = _trace_holes(mask, w, h, exterior)
    holes_simple = [_simplify_closed(hole, tol) for hole in holes_px
                    if len(hole) >= 4]
    result["source_image"] = os.path.basename(image_path)
    result["image_size_px"] = [w, h]
    result["px_bbox"] = [x0, x1, y0, y1]
    result["tolerance_px"] = tol
    result["bottom_cropped"] = bool(bottom_cropped)
    result["point_count"] = len(simple)
    result["hole_count"] = len(holes_simple)
    if width_mm is not None:
        scale = width_mm / (x1 - x0) if x1 > x0 else 0
        cx = (x0 + x1) / 2.0
        result["width_mm"] = width_mm
        result["scale_mm_per_px"] = scale
        result["points_mm"] = [
            [round((px_ - cx) * scale, 4),
             round((y1 - py) * scale, 4)] for (px_, py) in simple]
        result["mm_bbox"] = [
            round((x0 - cx) * scale, 4), round((x1 - cx) * scale, 4),
            0.0, round((y1 - y0) * scale, 4)]
        result["holes_mm"] = [
            [[round((px_ - cx) * scale, 4),
              round((y1 - py) * scale, 4)] for (px_, py) in hole]
            for hole in holes_simple]
    else:
        result["width_mm"] = None
        result["scale_mm_per_px"] = None
        result["points_px"] = [[px_, py] for (px_, py) in simple]
        result["holes_px"] = holes_simple
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1, ensure_ascii=False)
    if overlay_path:
        try:
            ov = img.copy()
            draw = ImageDraw.Draw(ov)
            pts = [(float(px_), float(py)) for (px_, py) in simple]
            draw.line(pts + [pts[0]], fill=(255, 0, 0), width=2)
            ov.save(overlay_path)
        except Exception:
            pass
    print(f"TRACE OK: {len(simple)} points, "
          f"{len(holes_simple)} hole(s), "
          f"px bbox X {x0}..{x1} Y {y0}..{y1}, "
          f"bottom_cropped={bool(bottom_cropped)}")
    return 0


# freecadcmd runs scripts with __name__ != "__main__" (same
# trap as measure_step.py / read_features.py), so always run.
if __name__ == "__main__" or True:
    sys.exit(main())
