#!/usr/bin/env python3
"""Dump a .fcstd feature tree to JSON (run under freecadcmd).

This is the modeling-side reader for dimension-to-feature mapping:
for every feature in the Body it records the values a table row can
be read from WITHOUT hunting macro text: Pad/Pocket Length, named
sketch constraints (constraints named after D-numbers, e.g. "D8"),
sketch geometry (for constraint-to-face mapping), and the faces
each feature CREATED (its shape minus the previous feature's shape
-- PartDesign feature shapes are cumulative, so "faces of Pad_Body"
would wrongly include gear/step faces).

Usage: freecadcmd read_features.py
  Input path comes from the FCSTD_PATH environment variable and
  output from FEATURES_OUT (same argv-trap avoidance as
  measure_step.py: freecadcmd tries to open trailing argv entries
  as documents). Exit code from freecadcmd is unreliable, so the
  caller checks that the output file exists and has no "error" key.

Output features.json:
- features: [{name, type, index, sketch, sketch_normal, sketch_x,
  sketch_y, length, teeth, modules, constraints, geometry,
  created_faces}] in Body tree order. Sketches carry constraints
  (named ones only: {name, type, value, first, second, first_pos,
  second_pos}) and geometry (lines: 3D start/end; circles: 3D
  center + radius). Solid features carry created_faces:
  [{type, center, area, bbox, normal (planes), radius/axis
  (cylinders)}]. Face BoundBox can inflate slightly for B-spline
  faces (control poles); plane/cylinder bboxes are exact.
"""

import json
import os

import FreeCAD as App


def _v3(v):
    return [round(float(v.x), 4), round(float(v.y), 4),
            round(float(v.z), 4)]


def _bbox(face):
    """Face bbox: tessellation extremes, except cylinders (analytic).

    Face.BoundBox inflates for faces bounded by B-splines: OCC
    builds it from control poles, not the curve itself (crown front
    plane: true X -2.4031..2.4076, BoundBox -2.4382..2.4519).
    Tessellation vertices lie ON the surface, so their extremes
    are the true extremes (same method verify_step trusts for the
    whole-shape bbox). Cylinders keep the analytic BoundBox:
    tessellation chords would underread a cylinder's extremes by
    up to the deflection.
    """
    try:
        if face.Surface.TypeId == "Part::GeomCylinder":
            raise ValueError("cylinder: use analytic box")
        verts, _facets = face.tessellate(0.01)
        if verts:
            xs = [v.x for v in verts]
            ys = [v.y for v in verts]
            zs = [v.z for v in verts]
            return {"x": [round(min(xs), 4), round(max(xs), 4)],
                    "y": [round(min(ys), 4), round(max(ys), 4)],
                    "z": [round(min(zs), 4), round(max(zs), 4)]}
    except Exception:
        pass
    try:
        bb = face.BoundBox
        return {"x": [round(bb.XMin, 4), round(bb.XMax, 4)],
                "y": [round(bb.YMin, 4), round(bb.YMax, 4)],
                "z": [round(bb.ZMin, 4), round(bb.ZMax, 4)]}
    except Exception:
        return None


def _face_sig(face):
    try:
        c = face.CenterOfMass
        return (face.Surface.TypeId, round(c.x, 3), round(c.y, 3),
                round(c.z, 3), round(face.Area, 3))
    except Exception:
        return None


def _face_record(face):
    rec = {"center": None, "area": None, "bbox": None}
    try:
        rec["center"] = _v3(face.CenterOfMass)
    except Exception:
        pass
    try:
        rec["area"] = round(float(face.Area), 4)
    except Exception:
        pass
    rec["bbox"] = _bbox(face)
    # Ordered curve samples for extrusion faces only: span
    # localmin mode (hook-tip dips) needs the curve in parameter
    # order -- a face bbox min is the face's lowest point (often
    # the root), and unordered tessellation vertices cannot tell a
    # dip from a band edge. BasisCurve.discretize gives ordered
    # points in global coords, identically on .fcstd and STEP.
    try:
        surf = face.Surface
        tid = surf.TypeId
        rec["type"] = tid.replace("Part::Geom", "")
        if "Extrusion" in tid:
            try:
                pts = surf.BasisCurve.discretize(Number=1000)
                rec["curve"] = [_v3(v) for v in pts]
            except Exception:
                pass
        if tid == "Part::GeomPlane":
            rec["normal"] = _v3(surf.Axis)
        elif tid == "Part::GeomCylinder":
            rec["radius"] = round(float(surf.Radius), 4)
            rec["axis"] = _v3(surf.Axis)
            try:
                rec["axis_point"] = _v3(surf.Center)
            except Exception:
                pass
    except Exception:
        rec["type"] = "?"
    return rec


def main():
    fcstd_path = os.environ.get("FCSTD_PATH", "")
    out_path = os.environ.get("FEATURES_OUT", "")
    if not fcstd_path or not out_path:
        raise RuntimeError("FCSTD_PATH and FEATURES_OUT must be set")
    doc = App.openDocument(fcstd_path)
    body = None
    for obj in doc.Objects:
        if obj.TypeId == "PartDesign::Body":
            body = obj
            break
    if body is None:
        raise RuntimeError("no PartDesign::Body in document")
    features = []
    prev_sigs = set()
    for index, obj in enumerate(body.Group):
        rec = {"name": obj.Name, "type": obj.TypeId, "index": index}
        if obj.TypeId == "Sketcher::SketchObject":
            try:
                pl = obj.Placement
                rot = pl.Rotation
                rec["sketch_normal"] = _v3(rot.multVec(App.Vector(0, 0, 1)))
                rec["sketch_x"] = _v3(rot.multVec(App.Vector(1, 0, 0)))
                rec["sketch_y"] = _v3(rot.multVec(App.Vector(0, 1, 0)))
                rec["sketch_origin"] = _v3(pl.Base)
            except Exception:
                pass
            cons = []
            try:
                for c in obj.Constraints:
                    name = getattr(c, "Name", "") or ""
                    if not name:
                        continue
                    entry = {"name": name, "type": getattr(c, "Type", "?")}
                    try:
                        entry["value"] = float(c.Value)
                    except Exception:
                        pass
                    for attr in ("First", "Second", "FirstPos",
                                 "SecondPos"):
                        try:
                            entry[attr.lower()] = int(getattr(c, attr))
                        except Exception:
                            pass
                    cons.append(entry)
            except Exception:
                pass
            rec["constraints"] = cons
            geom = []
            try:
                for gi, g in enumerate(obj.Geometry):
                    gt = g.TypeId.replace("Part::Geom", "")
                    entry = {"index": gi, "type": gt}
                    try:
                        if gt == "LineSegment":
                            entry["start"] = _v3(
                                pl.multVec(App.Vector(g.StartPoint.x,
                                                      g.StartPoint.y, 0)))
                            entry["end"] = _v3(
                                pl.multVec(App.Vector(g.EndPoint.x,
                                                      g.EndPoint.y, 0)))
                        elif gt in ("Circle", "ArcOfCircle"):
                            entry["center"] = _v3(
                                pl.multVec(App.Vector(g.Center.x,
                                                      g.Center.y, 0)))
                            entry["radius"] = round(float(g.Radius), 4)
                            try:
                                entry["start"] = _v3(pl.multVec(
                                    App.Vector(g.StartPoint.x,
                                               g.StartPoint.y, 0)))
                                entry["end"] = _v3(pl.multVec(
                                    App.Vector(g.EndPoint.x,
                                               g.EndPoint.y, 0)))
                            except Exception:
                                pass
                    except Exception:
                        pass
                    geom.append(entry)
            except Exception:
                pass
            rec["geometry"] = geom
            features.append(rec)
            continue
        # Solid feature: profile sketch, key properties, created faces.
        try:
            prof = obj.Profile
            sk = prof[0] if isinstance(prof, (tuple, list)) else prof
            rec["sketch"] = sk.Name if sk is not None else None
        except Exception:
            pass
        for prop in ("Length", "Size", "Radius"):
            try:
                rec[prop.lower()] = float(getattr(obj, prop))
            except Exception:
                pass
        if obj.TypeId == "PartDesign::InvoluteGear":
            try:
                rec["teeth"] = int(obj.NumberOfTeeth)
            except Exception:
                pass
            try:
                rec["modules"] = float(str(obj.Modules).split()[0])
            except Exception:
                pass
        try:
            sk = None
            prof = obj.Profile
            sk = prof[0] if isinstance(prof, (tuple, list)) else prof
            if sk is not None:
                rot = sk.Placement.Rotation
                rec["sketch_normal"] = _v3(rot.multVec(App.Vector(0, 0, 1)))
        except Exception:
            pass
        created = []
        try:
            shape = obj.Shape
            if shape is not None and not shape.isNull():
                sigs = set()
                for face in shape.Faces:
                    sig = _face_sig(face)
                    if sig is not None:
                        sigs.add(sig)
                for face in shape.Faces:
                    sig = _face_sig(face)
                    if sig is not None and sig not in prev_sigs:
                        created.append(_face_record(face))
                prev_sigs = sigs
        except Exception:
            pass
        rec["created_faces"] = created
        features.append(rec)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"features": features}, f, indent=1, ensure_ascii=False)
    print(f"FEATURES: {len(features)} objects dumped")


if __name__ == "__main__" or True:
    main()
