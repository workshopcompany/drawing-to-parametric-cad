#!/usr/bin/env python3
"""Render shaded preview PNGs from a STEP tessellation JSON.

Usage: python3 render_preview.py tris.json preview_iso.png preview_main.png

tris.json format (written by run_pipeline.py verify_step):
{"verts": [[x, y, z], ...], "facets": [[a, b, c], ...]} where a/b/c
are indices into verts.

Method (project standard, from earlier STEP previews): tessellation
triangles only, no edge lines, Lambertian shading with the light from
the camera direction, base color (0.68, 0.75, 0.84), ambient 0.40 +
diffuse 0.60, white background, DPI 150, back-to-front sort.

Views (generic, no part-specific axis assumption):
- preview_iso: isometric, camera (1, 1, 1), up (0, 0, 1).
- preview_main: orthographic onto the two largest bounding-box axes
  (horizontal = largest axis, vertical = second largest), camera
  along the remaining axis. This shows the part's largest face.

Requires matplotlib. If matplotlib is missing, this script exits 2
with a clear message and the caller must NOT fail the whole run —
previews are best-effort; the .fcstd / STEP files are the result.
"""
import json
import sys

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    import numpy as np
except ImportError:
    print("render_preview: matplotlib is not available; "
          "install it (pip install matplotlib) to render previews.",
          file=sys.stderr)
    sys.exit(2)

BCOL = np.array([0.68, 0.75, 0.84])
AMBIENT, DIFFUSE = 0.40, 0.60


def render(tris, cam, up, out_path):
    cam = np.array(cam, dtype=float)
    cam = cam / np.linalg.norm(cam)
    view_dir = -cam
    up = np.array(up, dtype=float)
    right = np.cross(view_dir, up)
    right = right / np.linalg.norm(right)
    up2 = np.cross(right, view_dir)
    items = []
    for a, b, c in tris:
        n = np.cross(b - a, c - a)
        ln = np.linalg.norm(n)
        if ln == 0:
            continue
        n = n / ln
        shade = AMBIENT + DIFFUSE * max(0.0, float(np.dot(n, cam)))
        col = tuple(np.clip(BCOL * shade, 0, 1))
        pa = (float(np.dot(a, right)), float(np.dot(a, up2)))
        pb = (float(np.dot(b, right)), float(np.dot(b, up2)))
        pc = (float(np.dot(c, right)), float(np.dot(c, up2)))
        depth = float(np.dot((a + b + c) / 3.0, cam))
        items.append((depth, [pa, pb, pc], col))
    items.sort(key=lambda t: t[0])
    fig = plt.figure(figsize=(8, 6), dpi=150)
    ax = fig.add_subplot(111)
    ax.set_facecolor("white")
    coll = PolyCollection([it[1] for it in items],
                          facecolors=[it[2] for it in items],
                          edgecolors="none", linewidths=0)
    ax.add_collection(coll)
    ax.autoscale_view()
    ax.set_aspect("equal")
    ax.axis("off")
    fig.savefig(out_path, bbox_inches="tight", pad_inches=0.05,
                facecolor="white")
    plt.close(fig)
    print(f"saved {out_path} ({len(items)} triangles)")


def main(argv):
    if len(argv) != 4:
        print("usage: render_preview.py tris.json preview_iso.png "
              "preview_main.png", file=sys.stderr)
        return 2
    tris_path, out_iso, out_main = argv[1], argv[2], argv[3]
    with open(tris_path, encoding="utf-8") as fh:
        data = json.load(fh)
    verts = np.array(data["verts"], dtype=float)
    tris = [(verts[a], verts[b], verts[c]) for a, b, c in data["facets"]]
    print(f"triangles: {len(tris)}")
    # Main view axes: two largest bounding-box extents.
    extents = verts.max(axis=0) - verts.min(axis=0)
    order = list(np.argsort(-extents))
    horiz, vert, depth_axis = order[0], order[1], order[2]
    cam_main = np.zeros(3)
    cam_main[depth_axis] = 1.0
    up_main = np.zeros(3)
    up_main[vert] = 1.0
    # Note: render() builds right = cross(view_dir, up); with cam
    # along +depth_axis and up along +vert, horizontal in the image
    # is the remaining (largest) axis. Sign flips are acceptable:
    # the preview is for shape checking, not a dimensioned drawing.
    render(tris, (1, 1, 1), (0, 0, 1), out_iso)
    render(tris, tuple(cam_main), tuple(up_main), out_main)
    print(f"main view: horizontal axis {horiz}, vertical axis {vert}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
