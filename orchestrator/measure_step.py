#!/usr/bin/env python3
"""Measure real geometry from a STEP file (run under freecadcmd).

This is the "silcheuk" (real measurement) battery: values measured
from the built shape itself, not from macro parameters or whole-part
bbox. It does NOT know any dimension list; it just reports every
geometric size it can find, and the caller (run_pipeline.py) matches
rows to this battery by value proximity.

Usage: freecadcmd measure_step.py <step_path>
  Output path comes from the MEASURE_OUT environment variable
  (set by run_pipeline.py --measure). Rationale: freecadcmd tries
  to open trailing argv entries as documents, and a .json entry
  gets fed to the Fem YAML/JSON mesh importer (noisy traceback
  after the script runs). Passing only the STEP on argv avoids
  that; the STEP itself opens harmlessly as a document.
  Fallback for manual runs: without MEASURE_OUT, the last two
  argv entries are <step_path> <out_json> as before.
  Exit code from freecadcmd is unreliable (0 even on error), so
  the caller checks that the output file exists.

Battery written to out_json:
- face_distances: [{value, axis}] unique distances between parallel
  planar face pairs (axis = dominant normal axis, else "angled").
  Plane distance only; faces need not overlap in projection.
- edge_lengths: [{value, axis}] unique straight-edge lengths,
  axis = dominant line direction (else "angled").
- vertex_deltas: {X: [...], Y: [...], Z: [...]} unique pairwise
  coordinate differences per axis (>= 0.01) from TOPOLOGICAL
  vertices (shape.Vertexes), NOT tessellation points: tessellation
  deltas are dense (a mesh point exists near almost any value)
  and would "confirm" anything. Consequence: smooth curve maxima
  with no corner point (e.g. hook tip tops) have no vertex delta;
  those rows stay unmeasured in v1 rather than faked.
- sections: [{z, x_extent, y_extent}] horizontal sections across Z
  (slice() with a thin-slab common() fallback).
- cyl_diams: [diameters] from cylindrical faces.
- faces: [{type, center, area, bbox, normal (planes),
  radius/axis (cylinders)}] for every STEP face, so the caller can
  attribute STEP faces to .fcstd features (feature-attributed
  measurement) instead of guessing from the value battery.
- solids, volume, bbox (tessellation vertices, not BoundBox: for
  B-spline models BoundBox inflates from control poles).
- bbox_extents: {X, Y, Z} whole-part extents from the same
  tessellation bbox. Sections sample coarsely (25 levels), so a
  smooth maximum between levels (e.g. crown width) reads low
  from sections alone; the bbox extent is the exact overall size.
"""

import json
import os
import sys

import FreeCAD as App
import Part


def _axis_of(n):
    ax = max(("X", "Y", "Z"), key=lambda a: abs(getattr(n, a.lower())))
    if abs(getattr(n, ax.lower())) > 0.9:
        return ax
    return "angled"


def _uniq3(values):
    return sorted({round(float(v), 3) for v in values if v >= 0.01})


def main():
    if "MEASURE_OUT" in os.environ:
        step_path, out_path = sys.argv[-1], os.environ["MEASURE_OUT"]
    else:
        step_path, out_path = sys.argv[-2], sys.argv[-1]
    shape = Part.read(step_path)
    if isinstance(shape, (list, tuple)):
        shape = shape[0]
    if shape is None or shape.isNull():
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"error": "STEP shape is null (empty export?)"},
                      f, ensure_ascii=False)
        print("MEASURE FAIL: STEP shape is null")
        return
    solids = shape.Solids
    verts, _facets = shape.tessellate(0.01)
    if not verts:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"error": "STEP tessellation is empty"}, f,
                      ensure_ascii=False)
        print("MEASURE FAIL: STEP tessellation is empty")
        return
    xs = [v.x for v in verts]
    ys = [v.y for v in verts]
    zs = [v.z for v in verts]

    # Planar faces: normal + center, for parallel-pair distances.
    planes = []
    cyl_diams = set()
    for face in shape.Faces:
        surf = face.Surface
        tid = surf.TypeId
        if tid == "Part::GeomPlane":
            try:
                n = surf.Axis
                c = face.CenterOfMass
            except Exception:
                continue
            planes.append((n, c))
        elif tid == "Part::GeomCylinder":
            try:
                cyl_diams.add(round(float(surf.Radius) * 2, 3))
            except Exception:
                pass
    face_distances = {}
    for i in range(len(planes)):
        n1, c1 = planes[i]
        for j in range(i + 1, len(planes)):
            n2, c2 = planes[j]
            try:
                dot = abs(n1.dot(n2))
            except Exception:
                continue
            if dot < 0.9995:
                continue
            d = abs((c2 - c1).dot(n1))
            if d < 0.01:
                continue
            key = (round(d, 3), _axis_of(n1))
            face_distances[key] = True
    face_list = [{"value": v, "axis": a}
                 for (v, a) in sorted(face_distances)]

    # Straight edge lengths, tagged with the line direction axis.
    edge_lengths = {}
    for edge in shape.Edges:
        try:
            if edge.Curve.TypeId == "Part::GeomLine":
                d = edge.Curve.Direction
                edge_lengths[(round(float(edge.Length), 3),
                              _axis_of(d))] = True
        except Exception:
            pass
    edge_list = [{"value": v, "axis": a}
                 for (v, a) in sorted(edge_lengths) if v >= 0.01]

    # Vertex coordinate differences per axis, from topological
    # vertices only (see module docstring: tessellation deltas are
    # dense and meaningless). Vertex has no .x attribute; use .Point.
    uniq = {a: sorted({round(getattr(v.Point, a.lower()), 4)
                       for v in shape.Vertexes})
            for a in ("X", "Y", "Z")}
    deltas = {}
    for a, coords in uniq.items():
        diffs = set()
        for i in range(len(coords)):
            for j in range(i + 1, len(coords)):
                d = round(coords[j] - coords[i], 3)
                if d >= 0.01:
                    diffs.add(d)
        deltas[a] = sorted(diffs)

    # Horizontal sections across Z.
    sections = []
    zmin, zmax = min(zs), max(zs)
    span = zmax - zmin
    if span > 0:
        n_levels = 25
        for k in range(n_levels):
            z = zmin + span * (k + 0.5) / n_levels
            sx = sy = None
            try:
                wires = shape.slice(App.Vector(0, 0, 1), z)
                pts = []
                for w in wires:
                    pts.extend(w.Vertexes)
                if pts:
                    px = [p.X for p in pts]
                    py = [p.Y for p in pts]
                    sx, sy = max(px) - min(px), max(py) - min(py)
            except Exception:
                sx = sy = None
            if sx is None:
                try:
                    slab = Part.makeBox(20000, 20000, 0.02,
                                        App.Vector(-10000, -10000, z - 0.01))
                    common = shape.common(slab)
                    if common is not None and common.Volume > 0:
                        cv, _ = common.tessellate(0.01)
                        if cv:
                            px = [p.x for p in cv]
                            py = [p.y for p in cv]
                            sx, sy = max(px) - min(px), max(py) - min(py)
                except Exception:
                    sx = sy = None
            if sx is not None and sx >= 0.01 and sy >= 0.01:
                sections.append({"z": round(z, 3),
                                 "x_extent": round(sx, 3),
                                 "y_extent": round(sy, 3)})

    # Full STEP face dump for feature attribution (see
    # attribute_step_faces in run_pipeline.py). Bbox from the face
    # BoundBox: exact for planes/cylinders, may inflate slightly
    # for B-spline faces (control poles).
    step_faces = []
    for face in shape.Faces:
        rec = {}
        try:
            surf = face.Surface
            tid = surf.TypeId
            rec["type"] = tid.replace("Part::Geom", "")
            if tid == "Part::GeomPlane":
                n = surf.Axis
                rec["normal"] = [round(float(n.x), 4),
                                 round(float(n.y), 4),
                                 round(float(n.z), 4)]
            elif tid == "Part::GeomCylinder":
                rec["radius"] = round(float(surf.Radius), 4)
                ax = surf.Axis
                rec["axis"] = [round(float(ax.x), 4),
                               round(float(ax.y), 4),
                               round(float(ax.z), 4)]
        except Exception:
            rec["type"] = "?"
        try:
            c = face.CenterOfMass
            rec["center"] = [round(float(c.x), 4),
                             round(float(c.y), 4),
                             round(float(c.z), 4)]
        except Exception:
            pass
        try:
            rec["area"] = round(float(face.Area), 4)
        except Exception:
            pass
        # Face bbox: tessellation extremes, except cylinders
        # (analytic). Same pole-inflation reason as read_features:
        # a planar face bounded by B-splines gets an inflated
        # BoundBox from control poles. Tessellation vertices lie
        # on the surface. Extrusion faces also carry ordered curve
        # samples for span localmin mode.
        try:
            tid = face.Surface.TypeId
            if tid == "Part::GeomCylinder":
                raise ValueError("cylinder: analytic box")
            verts, _facets = face.tessellate(0.01)
            if verts:
                xs = [v.x for v in verts]
                ys = [v.y for v in verts]
                zs = [v.z for v in verts]
                rec["bbox"] = {"x": [round(min(xs), 4), round(max(xs), 4)],
                               "y": [round(min(ys), 4), round(max(ys), 4)],
                               "z": [round(min(zs), 4), round(max(zs), 4)]}
                if "Extrusion" in tid:
                    try:
                        pts = face.Surface.BasisCurve.discretize(
                            Number=1000)
                        rec["curve"] = [[round(float(v.x), 4),
                                         round(float(v.y), 4),
                                         round(float(v.z), 4)]
                                        for v in pts]
                    except Exception:
                        pass
        except Exception:
            pass
        if "bbox" not in rec:
            try:
                bb = face.BoundBox
                rec["bbox"] = {"x": [round(bb.XMin, 4), round(bb.XMax, 4)],
                               "y": [round(bb.YMin, 4), round(bb.YMax, 4)],
                               "z": [round(bb.ZMin, 4), round(bb.ZMax, 4)]}
            except Exception:
                pass
        step_faces.append(rec)

    out = {
        "step": step_path,
        "solids": len(solids),
        "volume": round(float(shape.Volume), 4),
        "bbox": {"x": [round(min(xs), 3), round(max(xs), 3)],
                 "y": [round(min(ys), 3), round(max(ys), 3)],
                 "z": [round(min(zs), 3), round(max(zs), 3)]},
        "bbox_extents": {"X": round(max(xs) - min(xs), 3),
                         "Y": round(max(ys) - min(ys), 3),
                         "Z": round(max(zs) - min(zs), 3)},
        "face_distances": face_list,
        "edge_lengths": edge_list,
        "vertex_deltas": deltas,
        "sections": sections,
        "cyl_diams": sorted(cyl_diams),
        "faces": step_faces,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(f"MEASURED: {len(face_list)} face distances, "
          f"{len(edge_list)} edge lengths, "
          f"{sum(len(v) for v in deltas.values())} vertex deltas, "
          f"{len(sections)} sections, {len(cyl_diams)} cyl diameters")


if __name__ == "__main__" or True:
    main()
