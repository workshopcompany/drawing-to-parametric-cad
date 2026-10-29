# OPEN QUESTIONS (English, ASCII only):
# Q-NEW1 (provisional, confirm if possible): Shaft flat plane Y=1.55 is +Y provisional.
#   Is the flat on +Y or -Y (mirror)? Current macro uses +Y. Confirm to keep or mirror.
# Q-NEW2 (estimated): Housing chamfer 1.0 is estimated (no drawing dimension). Confirm value.
# Q-NEW3 (estimated): Flattened D7.2 width 5.0 is user-set (no drawing dimension). Chord 5.180 computed. Confirm.
# MEMO: Bolt: separate fastener, modelling excluded.
# MEMO: Bottom unknown protrusion omitted per user answer (ignore).
# MEMO: Holes are only 4-M1.6 tap (drill D1.25) on housing face x=9.9 +X to 13.1. No hole on flat 7.0-8.5.
# STACK USED: D3.5 x0-7.0 (flat x0-5.5 Y=1.55 +Y, round x5.5-7.0), Flat D7.2 x7.0-8.5 Y=+-2.5,
#   D12 x8.5-9.9, Square 13x13 x9.9-21.5 chamfer 1.0, D10 x21.5-22.4 ALONE, D3 x22.4-23.0, D2 x23.0-27.0.
#   PCD D15, centres +-5.303, 45deg, depth 3.2. Total 27.0.
# CONSTRAINT RULE: No single-point-alone Lock. Used Coincident to origin and DistanceX/Y from origin only.
# PLACEMENT RULE: Direct Placement MapMode Deactivated, Matrix for YZ (localX->global +Y, localY->global +Z, normal->global +X).
# NOTE: DistanceX/Y (point,origin) solves as point=-value, so macro uses value=-target.

import FreeCAD
import Part
import Sketcher
import math

FCSTD_MAIN = "/tmp/CSF3_1U_Main.fcstd"
STEP_PATH = "/tmp/CSF3_1U_Main.step"

def log_msg(s):
    FreeCAD.Console.PrintMessage(s + "\n")

def log_err(s):
    FreeCAD.Console.PrintError(s + "\n")

def diag_save(doc, n):
    try:
        p = "/tmp/CSF3_1U_diag_%02d.fcstd" % n
        doc.saveCopy(p)
        log_msg("DIAG SAVE %d -> %s OK" % (n, p))
    except Exception as e:
        log_err("DIAG SAVE %d FAILED: %s" % (n, str(e)))

def check_body(doc, body, step_no, feat_name):
    doc.recompute()
    if body is None:
        log_err("CHECK %d %s FAILED: no body" % (step_no, feat_name))
        diag_save(doc, step_no)
        raise Exception("No body at " + feat_name)
    if body.Shape is None or body.Shape.isNull():
        log_err("CHECK %d %s FAILED: null shape" % (step_no, feat_name))
        diag_save(doc, step_no)
        raise Exception("Null shape at " + feat_name)
    if not body.Shape.isValid():
        log_err("CHECK %d %s FAILED: invalid solid" % (step_no, feat_name))
        diag_save(doc, step_no)
        raise Exception("Invalid at " + feat_name)
    try:
        ns = len(body.Shape.Solids)
    except Exception:
        ns = 0
    if ns != 1:
        log_err("CHECK %d %s FAILED: solids=%d (need 1)" % (step_no, feat_name, ns))
        diag_save(doc, step_no)
        raise Exception("Multiple solids at " + feat_name)
    vol = body.Shape.Volume
    log_msg("CHECK %d %s OK: valid single solid Volume=%.3f" % (step_no, feat_name, vol))
    diag_save(doc, step_no)

def place_YZ(sk, x_off):
    sk.MapMode = 'Deactivated'
    mat = FreeCAD.Matrix(0,0,1,x_off, 1,0,0,0, 0,1,0,0, 0,0,0,1)
    sk.Placement = FreeCAD.Placement(mat)

# --- document / body ---
doc = FreeCAD.newDocument("CSF3_1U")
body = doc.addObject('PartDesign::Body', 'Body')
doc.recompute()
log_msg("DOC/BODY created. Origin=input tip, +X=output.")
step = 0

# --- 1: Shaft flat D3.5 x0-5.5 (flat Y=1.55 +Y provisional) ---
sk0 = body.newObject('Sketcher::SketchObject', 'Sk_ShaftFlat_0_55')
place_YZ(sk0, 0.0)
R0 = 1.75
Xf0 = 1.55
hy0 = math.sqrt(R0*R0 - Xf0*Xf0)
li0 = sk0.addGeometry(Part.LineSegment(FreeCAD.Vector(Xf0, -hy0, 0), FreeCAD.Vector(Xf0, hy0, 0)), False)
c0 = Part.Circle(FreeCAD.Vector(0,0,0), FreeCAD.Vector(0,0,1), R0)
a0s = math.atan2(hy0, Xf0)
a0e = 2*math.pi - a0s
ar0 = sk0.addGeometry(Part.ArcOfCircle(c0, a0s, a0e), False)
sk0.addConstraint(Sketcher.Constraint('Coincident', li0, 2, ar0, 1))
sk0.addConstraint(Sketcher.Constraint('Coincident', li0, 1, ar0, 2))
sk0.addConstraint(Sketcher.Constraint('Vertical', li0))
sk0.addConstraint(Sketcher.Constraint('Coincident', ar0, 3, -1, 1))
sk0.addConstraint(Sketcher.Constraint('Radius', ar0, R0))
sk0.addConstraint(Sketcher.Constraint('DistanceX', li0, 1, -1, 1, -Xf0))
doc.recompute()
pad0 = body.newObject('PartDesign::Pad', 'Pad_ShaftFlat_0_55')
pad0.Profile = sk0
pad0.Length = 5.5
pad0.Reversed = False
doc.recompute()
step += 1
check_body(doc, body, step, "Pad_ShaftFlat_0_55")

# --- 2: Shaft round D3.5 x5.5-7.0 ---
sk1 = body.newObject('Sketcher::SketchObject', 'Sk_ShaftRound_55_70')
place_YZ(sk1, 5.5)
c1 = Part.Circle(FreeCAD.Vector(0,0,0), FreeCAD.Vector(0,0,1), 1.75)
ci1 = sk1.addGeometry(c1, False)
sk1.addConstraint(Sketcher.Constraint('Coincident', ci1, 3, -1, 1))
sk1.addConstraint(Sketcher.Constraint('Diameter', ci1, 3.5))
doc.recompute()
pad1 = body.newObject('PartDesign::Pad', 'Pad_ShaftRound_55_70')
pad1.Profile = sk1
pad1.Length = 1.5
pad1.Reversed = False
doc.recompute()
step += 1
check_body(doc, body, step, "Pad_ShaftRound_55_70")

# --- 3: Flattened D7.2 x7.0-8.5, Y-flats +-2.5 ---
sk2 = body.newObject('Sketcher::SketchObject', 'Sk_Flat72_70_85')
place_YZ(sk2, 7.0)
R2 = 3.6
Xf2 = 2.5
hy2 = math.sqrt(R2*R2 - Xf2*Xf2)
r_idx = sk2.addGeometry(Part.LineSegment(FreeCAD.Vector(Xf2, -hy2, 0), FreeCAD.Vector(Xf2, hy2, 0)), False)
l_idx = sk2.addGeometry(Part.LineSegment(FreeCAD.Vector(-Xf2, hy2, 0), FreeCAD.Vector(-Xf2, -hy2, 0)), False)
cb = Part.Circle(FreeCAD.Vector(0,0,0), FreeCAD.Vector(0,0,1), R2)
a_rt = math.atan2(hy2, Xf2)
t_idx = sk2.addGeometry(Part.ArcOfCircle(cb, a_rt, math.pi - a_rt), False)
b_idx = sk2.addGeometry(Part.ArcOfCircle(cb, math.pi + a_rt, 2*math.pi - a_rt), False)
sk2.addConstraint(Sketcher.Constraint('Coincident', r_idx, 2, t_idx, 1))
sk2.addConstraint(Sketcher.Constraint('Coincident', t_idx, 2, l_idx, 1))
sk2.addConstraint(Sketcher.Constraint('Coincident', l_idx, 2, b_idx, 1))
sk2.addConstraint(Sketcher.Constraint('Coincident', b_idx, 2, r_idx, 1))
sk2.addConstraint(Sketcher.Constraint('Vertical', r_idx))
sk2.addConstraint(Sketcher.Constraint('Vertical', l_idx))
sk2.addConstraint(Sketcher.Constraint('Coincident', t_idx, 3, -1, 1))
sk2.addConstraint(Sketcher.Constraint('Coincident', b_idx, 3, -1, 1))
sk2.addConstraint(Sketcher.Constraint('Radius', t_idx, R2))
sk2.addConstraint(Sketcher.Constraint('Radius', b_idx, R2))
sk2.addConstraint(Sketcher.Constraint('DistanceX', r_idx, 1, -1, 1, -Xf2))
sk2.addConstraint(Sketcher.Constraint('DistanceX', l_idx, 1, -1, 1, Xf2))
doc.recompute()
pad2 = body.newObject('PartDesign::Pad', 'Pad_Flat72_70_85')
pad2.Profile = sk2
pad2.Length = 1.5
pad2.Reversed = False
doc.recompute()
step += 1
check_body(doc, body, step, "Pad_Flat72_70_85")

# --- 4: Boss D12 x8.5-9.9 ---
sk3 = body.newObject('Sketcher::SketchObject', 'Sk_Boss12_85_99')
place_YZ(sk3, 8.5)
c3 = Part.Circle(FreeCAD.Vector(0,0,0), FreeCAD.Vector(0,0,1), 6.0)
ci3 = sk3.addGeometry(c3, False)
sk3.addConstraint(Sketcher.Constraint('Coincident', ci3, 3, -1, 1))
sk3.addConstraint(Sketcher.Constraint('Diameter', ci3, 12.0))
doc.recompute()
pad3 = body.newObject('PartDesign::Pad', 'Pad_Boss12_85_99')
pad3.Profile = sk3
pad3.Length = 1.4
pad3.Reversed = False
doc.recompute()
step += 1
check_body(doc, body, step, "Pad_Boss12_85_99")

# --- 5: Housing square 13x13 x9.9-21.5 ---
sk4 = body.newObject('Sketcher::SketchObject', 'Sk_Housing_99_215')
place_YZ(sk4, 9.9)
h = 6.5
top_i = sk4.addGeometry(Part.LineSegment(FreeCAD.Vector(-h, h, 0), FreeCAD.Vector(h, h, 0)), False)
right_i = sk4.addGeometry(Part.LineSegment(FreeCAD.Vector(h, h, 0), FreeCAD.Vector(h, -h, 0)), False)
bot_i = sk4.addGeometry(Part.LineSegment(FreeCAD.Vector(h, -h, 0), FreeCAD.Vector(-h, -h, 0)), False)
left_i = sk4.addGeometry(Part.LineSegment(FreeCAD.Vector(-h, -h, 0), FreeCAD.Vector(-h, h, 0)), False)
sk4.addConstraint(Sketcher.Constraint('Coincident', top_i, 2, right_i, 1))
sk4.addConstraint(Sketcher.Constraint('Coincident', right_i, 2, bot_i, 1))
sk4.addConstraint(Sketcher.Constraint('Coincident', bot_i, 2, left_i, 1))
sk4.addConstraint(Sketcher.Constraint('Coincident', left_i, 2, top_i, 1))
sk4.addConstraint(Sketcher.Constraint('Horizontal', top_i))
sk4.addConstraint(Sketcher.Constraint('Horizontal', bot_i))
sk4.addConstraint(Sketcher.Constraint('Vertical', right_i))
sk4.addConstraint(Sketcher.Constraint('Vertical', left_i))
sk4.addConstraint(Sketcher.Constraint('Equal', top_i, right_i))
sk4.addConstraint(Sketcher.Constraint('Distance', top_i, 13.0))
sk4.addConstraint(Sketcher.Constraint('DistanceX', top_i, 2, -1, 1, -h))
sk4.addConstraint(Sketcher.Constraint('DistanceY', top_i, 2, -1, 1, -h))
doc.recompute()
pad4 = body.newObject('PartDesign::Pad', 'Pad_Housing_99_215')
pad4.Profile = sk4
pad4.Length = 11.6
pad4.Reversed = False
doc.recompute()
step += 1
check_body(doc, body, step, "Pad_Housing_99_215")

# --- 6: Housing chamfer 1.0 provisional ---
try:
    edge_names = []
    for i, e in enumerate(pad4.Shape.Edges):
        try:
            if isinstance(e.Curve, Part.Line):
                p1 = e.Vertexes[0].Point
                p2 = e.Vertexes[1].Point
                v = p2.sub(p1)
                L = v.Length
                if abs(L - 11.6) < 0.02:
                    if abs(abs(v.x) - L) < 0.02:
                        edge_names.append("Edge%d" % (i+1))
        except Exception:
            continue
    if len(edge_names) == 4:
        ch = body.newObject('PartDesign::Chamfer', 'Chamfer_Housing_10')
        ch.Base = (pad4, edge_names)
        ch.Size = 1.0
        doc.recompute()
        step += 1
        check_body(doc, body, step, "Chamfer_Housing_10")
        log_msg("CHAMFER OK edges=%s" % str(edge_names))
    else:
        log_msg("CHAMFER SKIPPED: found %d long edges (need 4). Housing stays square. Confirm chamfer 1.0." % len(edge_names))
        step += 1
        diag_save(doc, step)
except Exception as e:
    log_err("CHAMFER FAILED (provisional 1.0): %s. Continue with square housing." % str(e))
    try:
        co = doc.getObject('Chamfer_Housing_10')
        if co is not None:
            body.removeObject(co)
    except Exception:
        pass
    doc.recompute()
    step += 1
    diag_save(doc, step)

# --- 7: Boss D10 x21.5-22.4 ALONE ---
sk5 = body.newObject('Sketcher::SketchObject', 'Sk_Boss10_215_224')
place_YZ(sk5, 21.5)
c5 = Part.Circle(FreeCAD.Vector(0,0,0), FreeCAD.Vector(0,0,1), 5.0)
ci5 = sk5.addGeometry(c5, False)
sk5.addConstraint(Sketcher.Constraint('Coincident', ci5, 3, -1, 1))
sk5.addConstraint(Sketcher.Constraint('Diameter', ci5, 10.0))
doc.recompute()
pad5 = body.newObject('PartDesign::Pad', 'Pad_Boss10_215_224')
pad5.Profile = sk5
pad5.Length = 0.9
pad5.Reversed = False
doc.recompute()
step += 1
check_body(doc, body, step, "Pad_Boss10_215_224")

# --- 8: Step D3 x22.4-23.0 ---
sk6 = body.newObject('Sketcher::SketchObject', 'Sk_Step3_224_230')
place_YZ(sk6, 22.4)
c6 = Part.Circle(FreeCAD.Vector(0,0,0), FreeCAD.Vector(0,0,1), 1.5)
ci6 = sk6.addGeometry(c6, False)
sk6.addConstraint(Sketcher.Constraint('Coincident', ci6, 3, -1, 1))
sk6.addConstraint(Sketcher.Constraint('Diameter', ci6, 3.0))
doc.recompute()
pad6 = body.newObject('PartDesign::Pad', 'Pad_Step3_224_230')
pad6.Profile = sk6
pad6.Length = 0.6
pad6.Reversed = False
doc.recompute()
step += 1
check_body(doc, body, step, "Pad_Step3_224_230")

# --- 9: Shaft D2 x23.0-27.0 ---
sk7 = body.newObject('Sketcher::SketchObject', 'Sk_Shaft2_230_270')
place_YZ(sk7, 23.0)
c7 = Part.Circle(FreeCAD.Vector(0,0,0), FreeCAD.Vector(0,0,1), 1.0)
ci7 = sk7.addGeometry(c7, False)
sk7.addConstraint(Sketcher.Constraint('Coincident', ci7, 3, -1, 1))
sk7.addConstraint(Sketcher.Constraint('Diameter', ci7, 2.0))
doc.recompute()
pad7 = body.newObject('PartDesign::Pad', 'Pad_Shaft2_230_270')
pad7.Profile = sk7
pad7.Length = 4.0
pad7.Reversed = False
doc.recompute()
step += 1
check_body(doc, body, step, "Pad_Shaft2_230_270")

# --- 10: 4-M1.6 tap holes, drill D1.25, depth 3.2, face x=9.9 +X ---
skh = body.newObject('Sketcher::SketchObject', 'Sk_Holes_M16_99')
place_YZ(skh, 9.9)
r_h = 7.5 * math.cos(math.pi/4)
pts = [(r_h, r_h), (-r_h, r_h), (-r_h, -r_h), (r_h, -r_h)]
for (tx, ty) in pts:
    cc = Part.Circle(FreeCAD.Vector(tx, ty, 0), FreeCAD.Vector(0,0,1), 0.625)
    idx = skh.addGeometry(cc, False)
    skh.addConstraint(Sketcher.Constraint('Diameter', idx, 1.25))
    skh.addConstraint(Sketcher.Constraint('DistanceX', idx, 3, -1, 1, -tx))
    skh.addConstraint(Sketcher.Constraint('DistanceY', idx, 3, -1, 1, -ty))
doc.recompute()
poc = body.newObject('PartDesign::Pocket', 'Pocket_Holes_M16_32')
poc.Profile = skh
poc.Length = 3.2
poc.Reversed = True
poc.Midplane = False
doc.recompute()
step += 1
check_body(doc, body, step, "Pocket_Holes_M16_32")

# --- final save / export ---
doc.recompute()
log_msg("FINAL Volume=%.3f Solids=%d" % (body.Shape.Volume, len(body.Shape.Solids)))
doc.saveAs(FCSTD_MAIN)
log_msg("FCSTD SAVED -> %s" % FCSTD_MAIN)
try:
    Part.export([body], STEP_PATH)
    log_msg("STEP EXPORTED -> %s" % STEP_PATH)
except Exception as e:
    log_err("STEP EXPORT FAILED: %s" % str(e))
    raise
log_msg("DONE. Total length 27.0. See header questions.")
