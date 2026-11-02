"""Dump per-feature geometry from a .fcstd for the frame gate.

Runs under freecadcmd (bundled Python, no cv2 needed). Reads
FCSTD_PATH and FEATURES_OUT from the environment, same pattern as
read_features.py. freecadcmd exits 0 even on errors, so the output
file is the only trustworthy signal: on any failure it carries
{"error": ...} and the caller skips the per-feature checks.

Per feature (Body tree order):
  name, type, length (Pad/Pocket Length or None),
  reversed (bool), placement_base [x,y,z],
  placement_matrix 3x3 (rotation rows = world axes),
  sketch_bbox [[xmin,xmax],[ymin,ymax],[zmin,zmax]] (Shape.BoundBox
    as dumped; the caller decides local-vs-world mechanically),
  cumulative_bbox [[xmin,xmax],[ymin,ymax],[zmin,zmax]] from
    tessellation extremes (deflection 0.01 — true size for
    B-spline shapes, same convention as verify_step).
"""

import json
import os
import sys


def _tess_extremes(shape, deflection=0.01):
    try:
        verts, _facets = shape.tessellate(deflection)
    except Exception:
        return None
    if not verts:
        return None
    xs = [float(v.x) for v in verts]
    ys = [float(v.y) for v in verts]
    zs = [float(v.z) for v in verts]
    return [[min(xs), max(xs)], [min(ys), max(ys)], [min(zs), max(zs)]]


def _sketch_of(feat):
    prof = None
    try:
        prof = feat.Profile
    except Exception:
        return None
    if prof is None:
        return None
    if isinstance(prof, (list, tuple)):
        prof = prof[0] if prof else None
    return prof


def main():
    fcstd_path = os.environ.get("FCSTD_PATH", "")
    out_path = os.environ.get("FEATURES_OUT", "")
    result = {"features": {}}
    try:
        import FreeCAD as App
        doc = App.openDocument(fcstd_path)
        bodies = [o for o in doc.Objects
                  if o.TypeId == "PartDesign::Body"]
        feats = []
        if bodies:
            # Sketches ride in Group too but carry no feature
            # geometry; the Pad/Pocket rows below hold their
            # sketch info instead.
            feats = [o for o in bodies[0].Group
                     if not o.TypeId.startswith("Sketcher::")]
        else:
            feats = [o for o in doc.Objects
                     if hasattr(o, "Shape") and o.TypeId.startswith("PartDesign::")]
        for feat in feats:
            try:
                name = feat.Name
            except Exception:
                continue
            rec = {"type": getattr(feat, "TypeId", "")}
            try:
                rec["length"] = float(feat.Length)
            except Exception:
                rec["length"] = None
            try:
                rec["reversed"] = bool(feat.Reversed)
            except Exception:
                rec["reversed"] = False
            try:
                shape = feat.Shape
                rec["cumulative_bbox"] = _tess_extremes(shape)
            except Exception:
                rec["cumulative_bbox"] = None
            sk = _sketch_of(feat)
            if sk is not None:
                try:
                    plm = sk.Placement
                    base = plm.Base
                    rec["placement_base"] = [float(base.x),
                                             float(base.y),
                                             float(base.z)]
                    rot = plm.Rotation.toMatrix()
                    rec["placement_matrix"] = [
                        [float(rot.A11), float(rot.A12), float(rot.A13)],
                        [float(rot.A21), float(rot.A22), float(rot.A23)],
                        [float(rot.A31), float(rot.A32), float(rot.A33)],
                    ]
                except Exception:
                    rec["placement_base"] = None
                    rec["placement_matrix"] = None
                try:
                    bb = sk.Shape.BoundBox
                    rec["sketch_bbox"] = [[float(bb.XMin), float(bb.XMax)],
                                          [float(bb.YMin), float(bb.YMax)],
                                          [float(bb.ZMin), float(bb.ZMax)]]
                except Exception:
                    rec["sketch_bbox"] = None
            result["features"][name] = rec
        App.closeDocument(doc.Name)
    except Exception as exc:
        result = {"error": str(exc)}
    try:
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=1, ensure_ascii=False)
    except Exception as exc:
        sys.stderr.write(f"frame_measure: cannot write output: {exc}\n")


if __name__ == "__main__" or True:
    main()
