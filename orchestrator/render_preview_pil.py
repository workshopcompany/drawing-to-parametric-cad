#!/usr/bin/env python3
"""PIL + numpy fallback renderer for STEP tessellation previews.

Same CLI as render_preview.py:
    python render_preview_pil.py tris.json preview_iso.png preview_main.png

Why this exists: render_preview.py needs matplotlib, which is often
missing on a fresh Windows PC (this repo IS that case - my_run_output
says "Previews: unavailable (matplotlib is not available)"). This
fallback uses only Pillow + numpy (both already present here) so the
web UI can ALWAYS show result images with eyes, without pip install.

Method: orthographic projection + Lambertian shading + painter's
sort + Pillow polygon rasterization. White background, base color
(0.68, 0.75, 0.84), ambient 0.40 + diffuse 0.60 with light from the
camera direction. Same two views as render_preview.py:
  - preview_iso: camera (1,1,1), up (0,0,1)
  - preview_main: camera along the smallest bbox axis, up along the
    second-largest axis (shows the largest face).
"""
import json
import sys


def load_tris(path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data["verts"], data["facets"]


def render_view(verts, facets, cam, up, size=(900, 675)):
    import numpy as np
    from PIL import Image, ImageDraw

    V = np.array(verts, dtype=float)
    F = np.array(facets, dtype=int)
    cam = np.array(cam, dtype=float)
    cam = cam / float(np.linalg.norm(cam))
    view_dir = -cam
    up = np.array(up, dtype=float)
    right = np.cross(view_dir, up)
    n = float(np.linalg.norm(right))
    if n == 0:
        up = np.array([0.0, 0.0, 1.0]) if abs(cam[2]) < 0.9 else np.array([0.0, 1.0, 0.0])
        right = np.cross(view_dir, up)
        n = float(np.linalg.norm(right))
    right = right / n
    up2 = np.cross(right, view_dir)
    up2 = up2 / float(np.linalg.norm(up2))

    # Project all verts once.
    x = V @ right
    y = V @ up2
    depth = V @ cam
    xmin, xmax = float(x.min()), float(x.max())
    ymin, ymax = float(y.min()), float(y.max())
    W, H = size
    margin = 30
    span_x = (xmax - xmin) or 1.0
    span_y = (ymax - ymin) or 1.0
    scale = min((W - 2 * margin) / span_x, (H - 2 * margin) / span_y)
    cx, cy = (xmin + xmax) / 2.0, (ymin + ymax) / 2.0

    def proj(i):
        return (W / 2.0 + (float(x[i]) - cx) * scale,
                H / 2.0 - (float(y[i]) - cy) * scale)

    BCOL = (0.68, 0.75, 0.84)
    AMBIENT, DIFFUSE = 0.40, 0.60
    items = []
    for a, b, c in F.tolist():
        pa, pb, pc = V[a], V[b], V[c]
        nvec = np.cross(pb - pa, pc - pa)
        ln = float(np.linalg.norm(nvec))
        if ln == 0:
            continue
        nvec = nvec / ln
        shade = AMBIENT + DIFFUSE * max(0.0, float(nvec @ cam))
        col = tuple(int(max(0, min(255, round(ch * shade * 255)))) for ch in BCOL)
        d = (float(depth[a]) + float(depth[b]) + float(depth[c])) / 3.0
        items.append((d, (proj(a), proj(b), proj(c)), col))
    # Far first (small depth = far from camera along cam dir).
    items.sort(key=lambda t: t[0])

    img = Image.new("RGB", (W, H), (255, 255, 255))
    dr = ImageDraw.Draw(img)
    for _d, (p1, p2, p3), col in items:
        dr.polygon([p1, p2, p3], fill=col)
    return img, len(items)


def main(argv):
    if len(argv) not in (4, 7):
        print("usage: render_preview_pil.py tris.json preview_iso.png preview_main.png "
              "[preview_front.png preview_top.png preview_side.png]",
              file=sys.stderr)
        return 2
    tris_path, out_iso, out_main = argv[1], argv[2], argv[3]
    try:
        import numpy  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError as exc:
        print(f"render_preview_pil: missing dependency: {exc}", file=sys.stderr)
        return 2
    import numpy as np
    verts, facets = load_tris(tris_path)
    V = np.array(verts, dtype=float)
    print(f"verts: {len(verts)}, facets: {len(facets)}")
    extents = V.max(axis=0) - V.min(axis=0)
    order = list(np.argsort(-extents))
    horiz, vert, depth_axis = int(order[0]), int(order[1]), int(order[2])
    cam_main = [0.0, 0.0, 0.0]
    cam_main[depth_axis] = 1.0
    up_main = [0.0, 0.0, 0.0]
    up_main[vert] = 1.0
    img_iso, n1 = render_view(verts, facets, (1, 1, 1), (0, 0, 1))
    img_iso.save(out_iso)
    print(f"saved {out_iso} ({n1} triangles)")
    img_main, n2 = render_view(verts, facets, tuple(cam_main), tuple(up_main))
    img_main.save(out_main)
    print(f"saved {out_main} ({n2} triangles)")
    print(f"main view: horizontal axis {horiz}, vertical axis {vert}")
    if len(argv) == 7:
        # Fixed world-axis views (same cameras as render_preview.py).
        for cam, up, out_path in (
                ((0, -1, 0), (0, 0, 1), argv[4]),
                ((0, 0, 1), (0, 1, 0), argv[5]),
                ((1, 0, 0), (0, 0, 1), argv[6])):
            img, n = render_view(verts, facets, cam, up)
            img.save(out_path)
            print(f"saved {out_path} ({n} triangles)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
