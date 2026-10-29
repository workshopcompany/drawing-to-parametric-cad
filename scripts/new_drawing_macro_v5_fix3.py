# FIX3 (user CONFIRMED Oct 29 18:21-18:22 EDT): centre between slots is a SINGLE sharp
# RIGHT-ANGLE peak, NOT S2 flat/dipped top. Peak = intersection of the two centre-facing
# slot sides (+35deg left, -55deg right, perpendicular), computed (0.178, 4.539).
# Height does NOT matter / is not preset. Method: extend slots outward along centrelines
# until they OVERLAP at the intersection (left outer -0.15, right outer +0.15 from datum I),
# so slot cuts create the peak. F2 centre top is a sacrificial horizontal line at Z=4.8
# (above 4.539) between scaled P2/P3 X positions; S2 spline is REMOVED. Final peak is
# created by F3/F4 pockets, not by F2.
# FreeCAD macro - crown part from 2D drawing + green outline image
# ASCII only, English messages only.
# QUESTIONS (do NOT invent, ask user if needed):
#  Q-OUTLINE-1: Crown outer outline = boundary of green region in green outline image.
#    Used here as slot-CLOSED B-spline loop S1/S2/S3 + top chords P1-P2, P3-P4.
#    NOT a rectangle, NOT straight sides at X=+/-2.4. CONFIRM if green boundary changes.
#  Q-OUTLINE-2: Hook underside concaves are part of crown outline profile itself,
#    NOT separate pockets. Built as S1/S3 splines. CONFIRM.
#  Q-OUTLINE-3: Slots are VOID top-open pockets AFTER crown Pad, NOT part of outline sketch.
#    Outline sketch is slot-CLOSED with straight chords. CONFIRM.
#  Q-OUTLINE-4: Slot outer end = OUTLINE DRAWING POSITION (top chord centres).
#    No arbitrary 1.0/1.5mm extension as drawing dim. Minimal 0.05mm overshoot
#    outward is IMPLEMENTATION ONLY to guarantee top-open, flagged below.
#  Q-OUTLINE-5: Crown bottom buried to Z=2.7 (0.1 below base top 2.8) to fuse.
#    Bottom edge RB-LB is inside base material. CONFIRM bury depth.
#  Q-OUTLINE-6: Hook outer curves use loop_v12.json spline poles/knots, X scaled
#    by 4.8/4.8107 about X=0 to exactly 4.800, Z unchanged. Peak ~4.5. CONFIRM.
#  Q-DIM-1: R0.8 centre (1.0011,+/-0.2987) radius 0.7989 is INFERRED from v12
#    to fit endpoints (1.325,+/-1.029)-(1.8,+/-0.298). Drawing says 2-R0.8 nominal.
#  Q-DATUM: Slot intersection I=(0.2392,4.8868) is CONSTRUCTION datum in air
#    above peak, NOT a solid. Left +35deg, right -55deg from horizontal.
# SCOPE: Base body + connected crown body, 2 slot voids through Y 2.124 symmetric.
#  Wire is separate inserted component, NOT modelled as solid.
#  Bolt: separate fastener, modelling excluded. No bolts in this part.
# ORIGIN: base bottom centre (0,0,0). +X=width/right, +Y=depth, +Z=up.
#  Base: X -1.8..+1.8 (3.6), Y -1.575..+1.575 (3.15), Z 0..2.8.
#  Crown: X -2.4..+2.4 nominal 4.800, Y -1.062..+1.062 (2.124), Z 2.7..~4.5.
# MATERIAL vs VOID:
#  F1 Base Pad = BODY material. F2 Crown Pad = BODY material.
#  F3/F4 Slot Pockets = VOID (empty holes, top-open). No solid added for voids.

import FreeCAD
import Part
import Sketcher
import math
import os

LOGFILE = "/home/hatch/workspace/drawing-to-parametric-cad/validations/new_drawing_macro_v5_fix3_selffix_log.txt"
def MSG(t):
    print(t)
    try:
        with open(LOGFILE, "a") as _f:
            _f.write(str(t) + "\n")
    except Exception:
        pass

def save_step(doc, path):
    try:
        doc.saveAs(path)
        MSG("SAVE OK: " + path)
    except Exception as e:
        MSG("SAVE FAIL: " + path + " err=" + str(e))

def safe_add(sk, constr, desc):
    try:
        sk.addConstraint(constr)
        return True
    except Exception as e:
        MSG("CONSTRAINT SKIP (redundant or rejected) " + desc + " err=" + str(e))
        return False

def add_c(sk, make_fn, desc, doc=None, diagpath=None):
    # Wrap CONSTRAINT CONSTRUCTION (not just addConstraint) in try/except.
    # v5 failure: Constraint("Length", geo, value) raised TypeError while evaluating
    # the argument, BEFORE safe_add() was called, so safe_add never caught it.
    try:
        constr = make_fn()
    except Exception as e:
        MSG("CONSTRAINT CONSTRUCTION FAIL " + desc + " err=" + str(e))
        if doc is not None and diagpath is not None:
            fail_guidance("ConstraintConstruction", desc, str(e), "Invalid Sketcher.Constraint form (e.g. Length(geo,value) for a line; use Distance(geo,1,geo,2,value))", "tried constructing constraint for " + desc, "Fix constraint form to FreeCAD 1.1.4 point-index form and rerun.", doc, diagpath)
        raise
    try:
        sk.addConstraint(constr)
        return True
    except Exception as e:
        MSG("CONSTRAINT SKIP (redundant or rejected) " + desc + " err=" + str(e))
        return False

def fail_guidance(feat, idx, errmsg, hypothesis, tried, question, doc, diagpath):
    MSG("==== GUIDANCE FAILURE ====")
    MSG("Feature: " + feat)
    MSG("Sketch/geometry index: " + str(idx))
    MSG("Exact solver/error message: " + str(errmsg))
    MSG("Cause hypothesis: " + hypothesis)
    MSG("What was tried: " + tried)
    MSG("Question/alternative: " + question)
    try:
        with open(LOGFILE, "a") as _f:
            _f.write("GUIDANCE " + feat + " idx=" + str(idx) + " err=" + str(errmsg) + " hypothesis=" + hypothesis + " tried=" + tried + " question=" + question + "\n")
    except Exception:
        pass
    try:
        doc.saveAs(diagpath)
        MSG("DIAGNOSTIC SAVED: " + diagpath)
    except Exception as e:
        MSG("DIAGNOSTIC SAVE FAIL: " + str(e))
    raise RuntimeError("STOP at " + feat + " : " + str(errmsg))

# ---------------- constants ----------------
XSCALE = 4.8 / 4.8107  # nominal 0.9978, computed to hit 4.800 exactly
Z_BURY = 2.7
BASE_TOP = 2.8
CROWN_THK = 2.124
OVERSHOOT = 0.0  # FIX3: superseded for centre peak by user-confirmed OVERLAP extension.
                 # Slot outer ends are now at centreline distances -0.15 / +0.15 from I,
                 # beyond the intersection projections (-0.250 / +0.250) by 0.10, so the
                 # two slot rectangles overlap at the peak intersection. Logged, NOT a drawing dim.

IX = 0.2392
IZ = 4.8868
ANG_L = math.radians(35.0)
ANG_R = math.radians(-55.0)
SLOT_W = 0.5
D_L_OUT = 0.0  # FIX3 ATTEMPT2: outer end at datum I, 0.25 beyond intersection projection -0.250. Attempt1 (-0.15) left a 0.0278 mm3 plateau fragment (X 0.117..0.315, Z 4.678..4.800) between outer short sides and sacrificial top; extending to I covers plateau fully. Peak unchanged (centre-facing sides unchanged).
D_L_IN = -1.7484
D_R_OUT = 0.0  # FIX3 ATTEMPT2: outer end at datum I, 0.25 beyond intersection projection +0.250. Same fragment fix as left.
D_R_IN = 1.2994

# loop_v12 data (X will be scaled, Z unchanged)
S1_poles_raw = [
    [-0.990304829110791,2.8031747070307746],
    [-1.0163359000695633,3.0375413675570626],
    [-1.1918940671271172,3.3878253972557544],
    [-1.5099956141091062,3.7399582903948265],
    [-1.8757566315860208,3.88066561909976],
    [-2.2175801510119637,3.5054860270729544],
    [-2.4506854833655707,3.7660565763062444],
    [-2.2896197947395818,4.0686447897997615],
    [-1.815833397254435,4.400916155310397],
    [-1.2454365503115825,4.5908948006098464],
    [-0.8843751521442406,4.404873708238385]
]
S1_knots = [0.0,0.17912062814498397,0.2954218534038019,0.34338024246497506,0.4811455002808187,0.5394792709912433,0.5976802492109224,0.7013753893342088,1.0]
S1_mults = [4,1,1,1,1,1,1,1,4]
S1_deg = 3
S2_poles_raw = [[0.06739930018495688,4.460968644671688],[0.07252775466351954,4.388256683026875],[0.20595719162791384,4.389208782310093],[0.24667261835023424,4.441034195631333]]
S2_knots = [0.0,1.0]
S2_mults = [4,4]
S2_deg = 3
S3_poles_raw = [[0.878997701291192,4.409681373051687],[1.0294202999011262,4.54799703415862],[1.4023139898100905,4.3754526536210845],[2.005031926014731,4.593602089612002],[2.5547042688377775,4.164527604003027],[2.2618876756754878,3.6732070287168077],[1.9600917510344968,3.9149798331337617],[1.28864084125942,3.954591672701641],[0.96834515168089,3.145703186995294],[1.0064804500705726,2.8031747070307746]]
S3_knots = [0.0,0.14220363255697796,0.24836182249235267,0.4498139576239322,0.5114572927538416,0.5845676402610921,0.684455762239933,1.0]
S3_mults = [4,1,1,1,1,1,1,4]
S3_deg = 3

P1_raw = [-0.8843751521442406,4.404873708238385]
P2_raw = [0.06739930018495688,4.460968644671688]
P3_raw = [0.24667261835023424,4.441034195631333]
P4_raw = [0.878997701291192,4.409681373051687]
xL_raw = -0.990304829110791
xR_raw = 1.0064804500705726
rootZ = 2.8031747070307746

def SX(x):
    return x * XSCALE

P1 = [SX(P1_raw[0]), P1_raw[1]]
P2 = [SX(P2_raw[0]), P2_raw[1]]
P3 = [SX(P3_raw[0]), P3_raw[1]]
P4 = [SX(P4_raw[0]), P4_raw[1]]
xL = SX(xL_raw)
xR = SX(xR_raw)

# ---------------- doc/body ----------------
doc = FreeCAD.newDocument("CrownPart")
body = doc.addObject("PartDesign::Body", "Body")
doc.recompute()
MSG("DOC/BODY created. Origin base-bottom-centre, +X right, +Y depth, +Z up.")

# =========================================================
# F1 Base Pad
# Sketch: XY plane. local X->global +X, local Y->global +Y, normal->global +Z.
# Pad: Length 2.8, direction +Z (Z 0 to 2.8), Reversed=False, Midplane=False.
# Material side: BODY material (base).
# =========================================================
MSG("F1 START: Base section 3.6 x 3.15, Pad 2.8 in Z.")
sk1 = body.newObject("Sketcher::SketchObject", "Sketch_Base")
sk1.MapMode = "Deactivated"
sk1.Placement = FreeCAD.Placement(FreeCAD.Vector(0,0,0), FreeCAD.Rotation())
# vertices
V0 = (-1.05, 1.575)
V1 = (0.1, 1.575)
V2 = (1.325, 1.029)
V3 = (1.8, 0.298)
V4 = (1.8, -0.298)
V5 = (1.325, -1.029)
V6 = (0.1, -1.575)
V7 = (-1.05, -1.575)
V8 = (-1.8, -0.825)
V9 = (-1.8, 0.825)
def LP(a,b):
    return Part.LineSegment(FreeCAD.Vector(a[0],a[1],0), FreeCAD.Vector(b[0],b[1],0))
i0 = sk1.addGeometry(LP(V0,V1), False)  # 0 top
i1 = sk1.addGeometry(LP(V1,V2), False)  # 1 diag top
# arcs via Part.ArcOfCircle centre+radius+angles (program rule, NO Part.Arc 3-point)
def arc_CR(cx,cy,r,a0,a1):
    circ = Part.Circle(FreeCAD.Vector(cx,cy,0), FreeCAD.Vector(0,0,1), r)
    return Part.ArcOfCircle(circ, a0, a1)
# R0.75 top: pi/2 (V0) to pi (V9)
i9_arc_top = arc_CR(-1.05, 0.825, 0.75, math.pi/2.0, math.pi)
# R0.75 bottom: pi (V8) to 3pi/2 (V7)
i7_arc_bot = arc_CR(-1.05, -0.825, 0.75, math.pi, 3.0*math.pi/2.0)
# R0.8 top centre (1.0011,0.2987) r 0.7989 INFERRED, angles from centre
CRT = (1.0011, 0.2987)
R80 = 0.7989
a_V2 = math.atan2(V2[1]-CRT[1], V2[0]-CRT[0])
a_V3 = math.atan2(V3[1]-CRT[1], V3[0]-CRT[0])
# ATTEMPT3 FIX: Do NOT min/max or wrap negative angles to 360deg.
# Raw atan2: top V3 angle ~0deg, V2 angle ~66deg. Minor arc is V3->V2, 66deg.
# min/max after wrapping V3 (-0.05deg) to 360deg gave a 294deg MAJOR arc (66->360),
# self-crossing the wire and making F1 Pad invalid (attempt2 bbox 3.05x2.54, valid=False).
# Correct: a0 = a_V3 (~0), a1 = a_V2 (~66deg), start=V3, end=V2, as Coincident mapping expects.
a0_top80 = a_V3
a1_top80 = a_V2
# R0.8 bottom
CRB = (1.0011, -0.2987)
a_V4 = math.atan2(V4[1]-CRB[1], V4[0]-CRB[0])
a_V5 = math.atan2(V5[1]-CRB[1], V5[0]-CRB[0])
# ATTEMPT3 FIX: Same major-arc bug for bottom. Raw atan2: V5 angle ~-66deg, V4 angle ~0deg.
# Minor arc is V5->V4, 66deg. min/max gave 0->294deg MAJOR arc, start/end reversed vs Coincident mapping.
# Correct: a0 = a_V5 (~-66deg), a1 = a_V4 (~0deg), start=V5, end=V4.
a0_bot80 = a_V5
a1_bot80 = a_V4

i2 = sk1.addGeometry(arc_CR(CRT[0],CRT[1],R80,a0_top80,a1_top80), False)  # 2 top80 V3->V2
i3 = sk1.addGeometry(LP(V3,V4), False)  # 3 right
i4 = sk1.addGeometry(arc_CR(CRB[0],CRB[1],R80,a0_bot80,a1_bot80), False)  # 4 bot80 V5->V4
i5 = sk1.addGeometry(LP(V5,V6), False)  # 5 diag bottom
i6 = sk1.addGeometry(LP(V6,V7), False)  # 6 bottom
i7 = sk1.addGeometry(i7_arc_bot, False)  # 7 bot75 V8->V7
i8 = sk1.addGeometry(LP(V8,V9), False)  # 8 left
i9 = sk1.addGeometry(i9_arc_top, False)  # 9 top75 V0->V9
# Coincident closure (10). Mapping accounts for arc Start/End order above.
# i0:V0->V1, i1:V1->V2, i2:V3->V2, i3:V3->V4, i4:V5->V4, i5:V5->V6, i6:V6->V7, i7:V8->V7, i8:V8->V9, i9:V0->V9
safe_add(sk1, Sketcher.Constraint("Coincident", i0, 1, i9, 1), "F1 V0")
safe_add(sk1, Sketcher.Constraint("Coincident", i0, 2, i1, 1), "F1 V1")
safe_add(sk1, Sketcher.Constraint("Coincident", i1, 2, i2, 2), "F1 V2")
safe_add(sk1, Sketcher.Constraint("Coincident", i2, 1, i3, 1), "F1 V3")
safe_add(sk1, Sketcher.Constraint("Coincident", i3, 2, i4, 2), "F1 V4")
safe_add(sk1, Sketcher.Constraint("Coincident", i4, 1, i5, 1), "F1 V5")
safe_add(sk1, Sketcher.Constraint("Coincident", i5, 2, i6, 1), "F1 V6")
safe_add(sk1, Sketcher.Constraint("Coincident", i6, 2, i7, 2), "F1 V7")
safe_add(sk1, Sketcher.Constraint("Coincident", i7, 1, i8, 1), "F1 V8")
safe_add(sk1, Sketcher.Constraint("Coincident", i8, 2, i9, 2), "F1 V9")
# H/V
safe_add(sk1, Sketcher.Constraint("Horizontal", i0), "F1 top H")
safe_add(sk1, Sketcher.Constraint("Horizontal", i6), "F1 bottom H")
safe_add(sk1, Sketcher.Constraint("Vertical", i3), "F1 right V")
safe_add(sk1, Sketcher.Constraint("Vertical", i8), "F1 left V")
# Radii
safe_add(sk1, Sketcher.Constraint("Radius", i2, R80), "F1 R0.8 top")
safe_add(sk1, Sketcher.Constraint("Radius", i4, R80), "F1 R0.8 bot")
safe_add(sk1, Sketcher.Constraint("Radius", i7, 0.75), "F1 R0.75 bot")
safe_add(sk1, Sketcher.Constraint("Radius", i9, 0.75), "F1 R0.75 top")
# Lengths for H/V edges (top/bottom/left/right). Diagonals via DistanceX/Y below.
add_c(sk1, lambda: Sketcher.Constraint("Distance", i8, 1, i8, 2, 1.65), "F1 left len 1.65", doc, "/tmp/crown_F1_diag.fcstd")
add_c(sk1, lambda: Sketcher.Constraint("Distance", i3, 1, i3, 2, 0.596), "F1 right len 0.596", doc, "/tmp/crown_F1_diag.fcstd")
add_c(sk1, lambda: Sketcher.Constraint("Distance", i0, 1, i0, 2, 1.15), "F1 top len 1.15", doc, "/tmp/crown_F1_diag.fcstd")
add_c(sk1, lambda: Sketcher.Constraint("Distance", i6, 1, i6, 2, 1.15), "F1 bottom len 1.15", doc, "/tmp/crown_F1_diag.fcstd")
# Diagonals: DistanceX/Y between own Start-End (absolute separations, no Angle API)
# FIX2 ATTEMPT1: E1 dx=+1.225 dy=-0.546 (V1->V2 end-start); E5 dx=-1.225 dy=-0.546 (V5->V6 end-start)
try:
    sk1.addConstraint(Sketcher.Constraint("DistanceX", i1, 1, i1, 2, 1.225))
except Exception as e:
    MSG("F1 diag DistanceX skip: " + str(e))
try:
    sk1.addConstraint(Sketcher.Constraint("DistanceY", i1, 1, i1, 2, -0.546))
except Exception as e:
    MSG("F1 diag DistanceY skip: " + str(e))
try:
    sk1.addConstraint(Sketcher.Constraint("DistanceX", i5, 1, i5, 2, -1.225))
except Exception as e:
    MSG("F1 diag2 DistanceX skip: " + str(e))
try:
    sk1.addConstraint(Sketcher.Constraint("DistanceY", i5, 1, i5, 2, -0.546))
except Exception as e:
    MSG("F1 diag2 DistanceY skip: " + str(e))
# Anchor V1 (i0 End) to origin with +/- signs. Note: (point,origin) solves point=-value.
# Target V1=(0.1,1.575) so values -0.1, -1.575.
try:
    sk1.addConstraint(Sketcher.Constraint("DistanceX", i0, 2, -1, 1, -0.1))
    MSG("F1 anchor DistanceX added (value -0.1 for X=0.1).")
except Exception as e:
    MSG("F1 anchor DistanceX origin form fail: " + str(e) + " trying single-point form.")
    try:
        sk1.addConstraint(Sketcher.Constraint("DistanceX", i0, 2, -0.1))
    except Exception as e2:
        MSG("F1 anchor DistanceX single fail: " + str(e2))
try:
    sk1.addConstraint(Sketcher.Constraint("DistanceY", i0, 2, -1, 1, -1.575))
    MSG("F1 anchor DistanceY added (value -1.575 for Y=1.575).")
except Exception as e:
    MSG("F1 anchor DistanceY origin form fail: " + str(e))
    try:
        sk1.addConstraint(Sketcher.Constraint("DistanceY", i0, 2, -1.575))
    except Exception as e2:
        MSG("F1 anchor DistanceY single fail: " + str(e2))

doc.recompute()
# F1 checks: sketch closed, shape valid, solids==1 after pad, bbox 3.6x3.15x2.8
try:
    w = sk1.Shape.Wires[0]
    if not w.isClosed():
        fail_guidance("F1 Base Pad", "sketch wires", "sketch not closed", "arc point order or missing Coincident", "tried ArcOfCircle centre+radius+angles + 10 Coincidents", "Is arc Start/End mapping correct? Should we swap R0.8 angles?", doc, "/tmp/crown_F1_diag.fcstd")
    if not sk1.Shape.isValid():
        fail_guidance("F1 Base Pad", "sketch", "sketch shape invalid", "self-crossing wire (Arc 3-point order?)", "used ArcOfCircle centre form, not 3-point", "Check 24deg diagonal vs arc tangency?", doc, "/tmp/crown_F1_diag.fcstd")
except Exception as e:
    fail_guidance("F1 Base Pad", "sketch check", str(e), "sketch wiring", "tried closed-wire check", "Send sketch solver message.", doc, "/tmp/crown_F1_diag.fcstd")

pad1 = body.newObject("PartDesign::Pad", "Pad_Base")
pad1.Profile = sk1
pad1.Length = 2.8
pad1.Reversed = False
pad1.Midplane = False
doc.recompute()
try:
    nsol = len(body.Shape.Solids)
    valid = body.Shape.isValid()
    bb = body.Shape.BoundBox
    MSG("F1 check: solids=%d valid=%s bbox=%.4f x %.4f x %.4f" % (nsol, str(valid), bb.XLength, bb.YLength, bb.ZLength))
    if nsol != 1 or not valid:
        fail_guidance("F1 Base Pad", "solid", "solids=%d valid=%s" % (nsol, str(valid)), "open wire or self-crossing (v4 had 6 solids from Arc 3-point order)", "used ArcOfCircle centre+radius+angles per rule", "Confirm R0.8 centre/radius? Try exact 0.8 vs 0.7989?", doc, "/tmp/crown_F1_diag.fcstd")
    if abs(bb.XLength-3.6) > 0.02 or abs(bb.YLength-3.15) > 0.02 or abs(bb.ZLength-2.8) > 0.02:
        fail_guidance("F1 Base Pad", "bbox", "bbox %.4f x %.4f x %.4f, expected 3.6 x 3.15 x 2.8" % (bb.XLength, bb.YLength, bb.ZLength), "anchor sign flip (DistanceX/Y point=-value) or diagonal dx/dy", "tried anchor values -0.1/-1.575", "Is base centred at origin? Should anchor be +0.1?", doc, "/tmp/crown_F1_diag.fcstd")
except Exception as e:
    fail_guidance("F1 Base Pad", "post-pad", str(e), "pad failed", "tried Pad Length 2.8 +Z Reversed=False", "Send exact error text.", doc, "/tmp/crown_F1_diag.fcstd")
save_step(doc, "/tmp/crown_F1.fcstd")
MSG("F1 PASS: Base standalone 3.6 x 3.15 x 2.8, single valid solid.")

# =========================================================
# F2 Crown Outline Pad (slot-CLOSED)
# Sketch: XZ plane via Rx+90. local X->global +X, local Y->global +Z, normal->global -Y.
# Pad: Length 2.124 symmetric (Midplane=True), Y -1.062..+1.062. Reversed=False (symmetric).
# Material side: BODY material (crown around slots). Green boundary, NOT rectangle.
# =========================================================
MSG("F2 START: Crown outline slot-CLOSED, splines S1/S2/S3 + chords P1-P2/P3-P4, bury 2.7.")
sk2 = body.newObject("Sketcher::SketchObject", "Sketch_Crown")
sk2.MapMode = "Deactivated"
sk2.Placement = FreeCAD.Placement(FreeCAD.Vector(0,0,0), FreeCAD.Rotation(FreeCAD.Vector(1,0,0), 90))
# Build B-splines
def make_spline(raw, knots, mults, deg):
    poles = [FreeCAD.Vector(SX(p[0]), p[1], 0) for p in raw]
    bs = Part.BSplineCurve()
    bs.buildFromPolesMultsKnots(poles, list(mults), list(knots), False, deg)
    return bs
bs1 = make_spline(S1_poles_raw, S1_knots, S1_mults, S1_deg)
bs2 = None  # FIX3: S2 spline REMOVED. Centre top is a straight line at Z=4.8 (below).
bs3 = make_spline(S3_poles_raw, S3_knots, S3_mults, S3_deg)
def LS(a,b):
    return Part.LineSegment(FreeCAD.Vector(a[0],a[1],0), FreeCAD.Vector(b[0],b[1],0))
LB = [xL, Z_BURY]
RB = [xR, Z_BURY]
RootL = [xL, rootZ]
RootR = [xR, rootZ]
g_dropL = sk2.addGeometry(LS(LB, RootL), False)
g_bot = sk2.addGeometry(LS(LB, RB), False)
g_dropR = sk2.addGeometry(LS(RB, RootR), False)
g_s1 = sk2.addGeometry(bs1, False)
P2p = [SX(P2_raw[0]), 4.8]  # FIX3 sacrificial top, above peak 4.539, X = scaled P2 X
P3p = [SX(P3_raw[0]), 4.8]  # FIX3 sacrificial top, above peak 4.539, X = scaled P3 X
g_chL = sk2.addGeometry(LS(P1, P2p), False)
g_s2 = sk2.addGeometry(LS(P2p, P3p), False)
g_chR = sk2.addGeometry(LS(P3p, P4), False)
g_s3 = sk2.addGeometry(bs3, False)
# Coincident: RootL, LB, RB, RootR, P1, P2, P3, P4
safe_add(sk2, Sketcher.Constraint("Coincident", g_dropL, 2, g_s1, 1), "F2 RootL")
safe_add(sk2, Sketcher.Constraint("Coincident", g_dropL, 1, g_bot, 1), "F2 LB")
safe_add(sk2, Sketcher.Constraint("Coincident", g_bot, 2, g_dropR, 1), "F2 RB")
safe_add(sk2, Sketcher.Constraint("Coincident", g_dropR, 2, g_s3, 2), "F2 RootR")
safe_add(sk2, Sketcher.Constraint("Coincident", g_s1, 2, g_chL, 1), "F2 P1")
safe_add(sk2, Sketcher.Constraint("Coincident", g_chL, 2, g_s2, 1), "F2 P2")
safe_add(sk2, Sketcher.Constraint("Coincident", g_s2, 2, g_chR, 1), "F2 P3")
safe_add(sk2, Sketcher.Constraint("Coincident", g_chR, 2, g_s3, 1), "F2 P4")
# Minimum-to-green: Block splines (1 per spline fixes poles), H/V for drops/bottom, 1 Length.
safe_add(sk2, Sketcher.Constraint("Block", g_s1), "F2 Block S1")
safe_add(sk2, Sketcher.Constraint("Horizontal", g_s2), "F2 Top Horizontal Z=4.8")
safe_add(sk2, Sketcher.Constraint("Block", g_s3), "F2 Block S3")
safe_add(sk2, Sketcher.Constraint("Vertical", g_dropL), "F2 dropL V")
safe_add(sk2, Sketcher.Constraint("Vertical", g_dropR), "F2 dropR V")
safe_add(sk2, Sketcher.Constraint("Horizontal", g_bot), "F2 bottom H")
add_c(sk2, lambda: Sketcher.Constraint("Distance", g_dropL, 1, g_dropL, 2, rootZ - Z_BURY), "F2 drop len", doc, "/tmp/crown_F2_diag.fcstd")
doc.recompute()
try:
    w2 = sk2.Shape.Wires[0]
    if not w2.isClosed():
        fail_guidance("F2 Crown Pad", "sketch", "outline not closed", "missing Coincident at P1/P2/P3/P4 or bury", "tried 8 Coincidents + Block splines", "Which junction is open? Send wire gap.", doc, "/tmp/crown_F2_diag.fcstd")
    if not sk2.Shape.isValid():
        fail_guidance("F2 Crown Pad", "sketch", "sketch invalid", "spline knot/mult mismatch or self-intersection", "used poles/mults/knots from loop_v12.json", "Should we resample splines as polylines?", doc, "/tmp/crown_F2_diag.fcstd")
except Exception as e:
    fail_guidance("F2 Crown Pad", "sketch check", str(e), "spline build", "tried buildFromPolesMultsKnots", "Send exact OCC message.", doc, "/tmp/crown_F2_diag.fcstd")

pad2 = body.newObject("PartDesign::Pad", "Pad_Crown")
pad2.Profile = sk2
pad2.Length = CROWN_THK
pad2.Midplane = True
pad2.Reversed = False
doc.recompute()
try:
    nsol = len(body.Shape.Solids)
    valid = body.Shape.isValid()
    bb = body.Shape.BoundBox
    MSG("F2 check: solids=%d valid=%s bbox=%.4f x %.4f x %.4f Zmin=%.4f Zmax=%.4f" % (nsol, str(valid), bb.XLength, bb.YLength, bb.ZLength, bb.ZMin, bb.ZMax))
    if nsol != 1 or not valid:
        fail_guidance("F2 Crown Pad", "solid", "solids=%d valid=%s" % (nsol, str(valid)), "crown not fused to base (bury?) or spline self-crossing", "tried bury 2.7 (0.1 overlap) + symmetric 2.124", "Increase bury to 2.6? Or check spline direction?", doc, "/tmp/crown_F2_diag.fcstd")
    # FIX2 ATTEMPT2: BoundBox INFLATES B-splines (control poles, not curve).
    # Attempt1: BoundBox X=4.8795 (poles -2.4329..2.4466) while sampled true curve
    # X=-2.3976..2.4022 = 4.7998, i.e. correct 4.800. So width/peak must use
    # solid TESSELLATION vertices (true size), NOT Shape.BoundBox, for crown.
    tess_verts = body.Shape.tessellate(0.01)[0]
    tess_xmin = min(v.x for v in tess_verts); tess_xmax = max(v.x for v in tess_verts)
    tess_zmax = max(v.z for v in tess_verts)
    tess_w = tess_xmax - tess_xmin
    MSG("F2 tessellation: X=%.4f..%.4f width=%.4f Zmax=%.4f (BoundBox X=%.4f Zmax=%.4f is pole-inflated, ignore for crown)" % (tess_xmin, tess_xmax, tess_w, tess_zmax, bb.XLength, bb.ZMax))
    if abs(tess_w-4.8) > 0.03:
        fail_guidance("F2 Crown Pad", "width-tess", "tess X=%.4f width=%.4f expected 4.800" % (tess_xmin, tess_w), "X scale factor", "used XSCALE=4.8/4.8107", "Is 4.800 exact after scaling?", doc, "/tmp/crown_F2_diag.fcstd")
    if tess_zmax < 4.75 or tess_zmax > 4.85:
        fail_guidance("F2 Crown Pad", "peak-tess", "tess Zmax=%.4f expected sacrificial 4.8" % tess_zmax, "centre top line not at 4.8", "FIX3 sacrificial top P2p-P3p at Z=4.8", "Is centre top line at Z=4.8?", doc, "/tmp/crown_F2_diag.fcstd")
    MSG("F2 NOTE: tess Zmax ~4.8 is SACRIFICIAL plateau only; final centre peak (0.178,4.539) is created by F3/F4 slot overlap, not by F2.")
except Exception as e:
    fail_guidance("F2 Crown Pad", "post-pad", str(e), "pad fuse fail", "tried Midplane 2.124 normal -Y", "Send exact error.", doc, "/tmp/crown_F2_diag.fcstd")
save_step(doc, "/tmp/crown_F2.fcstd")
MSG("F2 PASS: Crown fused, width 4.800, sacrificial top 4.8, thk 2.124. Final peak created by slots.")

# ---------------- slot math ----------------
uL = (math.cos(ANG_L), math.sin(ANG_L))
uR = (math.cos(ANG_R), math.sin(ANG_R))
perpL = (-math.sin(ANG_L), math.cos(ANG_L))
perpR = (-math.sin(ANG_R), math.cos(ANG_R))
OL = [IX + D_L_OUT*uL[0], IZ + D_L_OUT*uL[1]]
EL = [IX + D_L_IN*uL[0], IZ + D_L_IN*uL[1]]
OR_ = [IX + D_R_OUT*uR[0], IZ + D_R_OUT*uR[1]]
ER = [IX + D_R_IN*uR[0], IZ + D_R_IN*uR[1]]
OL_ext = [OL[0] + OVERSHOOT*uL[0], OL[1] + OVERSHOOT*uL[1]]
OR_ext = [OR_[0] - OVERSHOOT*uR[0], OR_[1] - OVERSHOOT*uR[1]]
MSG("Slots: I=(%.4f,%.4f) OL=(%.4f,%.4f) EL=(%.4f,%.4f) OR=(%.4f,%.4f) ER=(%.4f,%.4f) overshoot=%.2f flagged" % (IX,IZ,OL[0],OL[1],EL[0],EL[1],OR_[0],OR_[1],ER[0],ER[1],OVERSHOOT))

def slot_corners(Oe, E, perp):
    hw = SLOT_W/2.0
    Oa = [Oe[0]+hw*perp[0], Oe[1]+hw*perp[1]]
    Ob = [Oe[0]-hw*perp[0], Oe[1]-hw*perp[1]]
    Ea = [E[0]+hw*perp[0], E[1]+hw*perp[1]]
    Eb = [E[0]-hw*perp[0], E[1]-hw*perp[1]]
    return Oa, Ob, Eb, Ea

# =========================================================
# F3 Left slot pocket (+35deg)
# Sketch: XZ plane (same as F2). local X->global X, local Y->global Z, normal->global -Y.
# Pocket: Length 2.124 Midplane symmetric in Y, Reversed=False, through upper thk.
# Material: VOID top-open (empty hole). Outer end = outline pos + 0.05 flagged overshoot.
# =========================================================
MSG("F3 START: Left slot +35deg width 0.5.")
LCa, LCb, LCc, LCd = slot_corners(OL_ext, EL, perpL)
sk3 = body.newObject("Sketcher::SketchObject", "Sketch_SlotLeft")
sk3.MapMode = "Deactivated"
sk3.Placement = FreeCAD.Placement(FreeCAD.Vector(0,0,0), FreeCAD.Rotation(FreeCAD.Vector(1,0,0), 90))
# construction datum point I
pI3 = sk3.addGeometry(Part.Point(FreeCAD.Vector(IX, IZ, 0)), True)
# datum line: I -> I+uL*1.0
dL_end = [IX+uL[0]*1.0, IZ+uL[1]*1.0]
g_dL = sk3.addGeometry(Part.LineSegment(FreeCAD.Vector(IX,IZ,0), FreeCAD.Vector(dL_end[0],dL_end[1],0)), True)
# rectangle
g3_0 = sk3.addGeometry(Part.LineSegment(FreeCAD.Vector(LCa[0],LCa[1],0), FreeCAD.Vector(LCb[0],LCb[1],0)), False)
g3_1 = sk3.addGeometry(Part.LineSegment(FreeCAD.Vector(LCb[0],LCb[1],0), FreeCAD.Vector(LCc[0],LCc[1],0)), False)
g3_2 = sk3.addGeometry(Part.LineSegment(FreeCAD.Vector(LCc[0],LCc[1],0), FreeCAD.Vector(LCd[0],LCd[1],0)), False)
g3_3 = sk3.addGeometry(Part.LineSegment(FreeCAD.Vector(LCd[0],LCd[1],0), FreeCAD.Vector(LCa[0],LCa[1],0)), False)
# closure
safe_add(sk3, Sketcher.Constraint("Coincident", g3_0, 2, g3_1, 1), "F3 c0")
safe_add(sk3, Sketcher.Constraint("Coincident", g3_1, 2, g3_2, 1), "F3 c1")
safe_add(sk3, Sketcher.Constraint("Coincident", g3_2, 2, g3_3, 1), "F3 c2")
safe_add(sk3, Sketcher.Constraint("Coincident", g3_3, 2, g3_0, 1), "F3 c3")
# datum fixes (origin distances, values negated per point=-value rule, try origin form)
for (gi,pos,tx,ty,nm) in [(pI3,1,IX,IZ,"F3 I")]:
    try:
        sk3.addConstraint(Sketcher.Constraint("DistanceX", gi, pos, -1, 1, -tx))
    except Exception as e:
        MSG("F3 datum X origin fail " + nm + ": " + str(e))
    try:
        sk3.addConstraint(Sketcher.Constraint("DistanceY", gi, pos, -1, 1, -ty))
    except Exception as e:
        MSG("F3 datum Y origin fail " + nm + ": " + str(e))
safe_add(sk3, Sketcher.Constraint("Coincident", g_dL, 1, pI3, 1), "F3 datum coincident")
# fix datum end via origin distances
try:
    sk3.addConstraint(Sketcher.Constraint("DistanceX", g_dL, 2, -1, 1, -dL_end[0]))
except Exception as e:
    MSG("F3 datum end X fail: " + str(e))
try:
    sk3.addConstraint(Sketcher.Constraint("DistanceY", g_dL, 2, -1, 1, -dL_end[1]))
except Exception as e:
    MSG("F3 datum end Y fail: " + str(e))
# fix two adjacent outer corners to set position+angle (short side 0.5), no Angle API
for (gi,pos,tx,ty,nm) in [(g3_0,1,LCa[0],LCa[1],"F3 Oa"),(g3_0,2,LCb[0],LCb[1],"F3 Ob")]:
    try:
        sk3.addConstraint(Sketcher.Constraint("DistanceX", gi, pos, -1, 1, -tx))
    except Exception as e:
        MSG("F3 corner X fail " + nm + ": " + str(e))
    try:
        sk3.addConstraint(Sketcher.Constraint("DistanceY", gi, pos, -1, 1, -ty))
    except Exception as e:
        MSG("F3 corner Y fail " + nm + ": " + str(e))
# long side length + 90deg inner end
llenL = math.hypot(LCa[0]-LCd[0], LCa[1]-LCd[1])
# llen should be ~0.9571+overshoot
add_c(sk3, lambda: Sketcher.Constraint("Distance", g3_3, 1, g3_3, 2, llenL), "F3 long len", doc, "/tmp/crown_F3_diag.fcstd")
safe_add(sk3, Sketcher.Constraint("Perpendicular", g3_0, g3_1), "F3 perp")
doc.recompute()
try:
    if not sk3.Shape.Wires[0].isClosed():
        fail_guidance("F3 SlotLeft", "sketch", "slot rect not closed", "missing Coincident", "tried 4 Coincidents", "Which corner gap?", doc, "/tmp/crown_F3_diag.fcstd")
except Exception as e:
    fail_guidance("F3 SlotLeft", "sketch check", str(e), "datum/rect build", "tried datum point+line+rect", "Send solver message.", doc, "/tmp/crown_F3_diag.fcstd")

pk3 = body.newObject("PartDesign::Pocket", "Pocket_SlotLeft")
pk3.Profile = sk3
pk3.Length = CROWN_THK
pk3.Midplane = True
pk3.Reversed = False
doc.recompute()
try:
    nsol = len(body.Shape.Solids)
    valid = body.Shape.isValid()
    MSG("F3 check: solids=%d valid=%s" % (nsol, str(valid)))
    if nsol != 1 or not valid:
        fail_guidance("F3 SlotLeft", "pocket", "solids=%d valid=%s" % (nsol, str(valid)), "coincident outline boundary OCC or rect outside?", "tried exact outline +0.05 flagged overshoot, Midplane 2.124", "Reduce overshoot to 0.01? Or extend to 0.1?", doc, "/tmp/crown_F3_diag.fcstd")
except Exception as e:
    fail_guidance("F3 SlotLeft", "post-pocket", str(e), "pocket fail", "tried Y symmetric 2.124", "Send exact error.", doc, "/tmp/crown_F3_diag.fcstd")
save_step(doc, "/tmp/crown_F3.fcstd")
MSG("F3 PASS: Left slot VOID top-open, width 0.5, +35deg, inner -1.7484, outer 0.0 at datum I OVERLAP (FIX3 attempt2).")

# =========================================================
# F4 Right slot pocket (-55deg)
# Sketch: XZ plane, normal -Y. Pocket Y symmetric 2.124, Reversed=False. VOID top-open.
# =========================================================
MSG("F4 START: Right slot -55deg width 0.5.")
RCa, RCb, RCc, RCd = slot_corners(OR_ext, ER, perpR)
sk4 = body.newObject("Sketcher::SketchObject", "Sketch_SlotRight")
sk4.MapMode = "Deactivated"
sk4.Placement = FreeCAD.Placement(FreeCAD.Vector(0,0,0), FreeCAD.Rotation(FreeCAD.Vector(1,0,0), 90))
pI4 = sk4.addGeometry(Part.Point(FreeCAD.Vector(IX, IZ, 0)), True)
dR_end = [IX+uR[0]*1.0, IZ+uR[1]*1.0]
g_dR = sk4.addGeometry(Part.LineSegment(FreeCAD.Vector(IX,IZ,0), FreeCAD.Vector(dR_end[0],dR_end[1],0)), True)
g4_0 = sk4.addGeometry(Part.LineSegment(FreeCAD.Vector(RCa[0],RCa[1],0), FreeCAD.Vector(RCb[0],RCb[1],0)), False)
g4_1 = sk4.addGeometry(Part.LineSegment(FreeCAD.Vector(RCb[0],RCb[1],0), FreeCAD.Vector(RCc[0],RCc[1],0)), False)
g4_2 = sk4.addGeometry(Part.LineSegment(FreeCAD.Vector(RCc[0],RCc[1],0), FreeCAD.Vector(RCd[0],RCd[1],0)), False)
g4_3 = sk4.addGeometry(Part.LineSegment(FreeCAD.Vector(RCd[0],RCd[1],0), FreeCAD.Vector(RCa[0],RCa[1],0)), False)
safe_add(sk4, Sketcher.Constraint("Coincident", g4_0, 2, g4_1, 1), "F4 c0")
safe_add(sk4, Sketcher.Constraint("Coincident", g4_1, 2, g4_2, 1), "F4 c1")
safe_add(sk4, Sketcher.Constraint("Coincident", g4_2, 2, g4_3, 1), "F4 c2")
safe_add(sk4, Sketcher.Constraint("Coincident", g4_3, 2, g4_0, 1), "F4 c3")
try:
    sk4.addConstraint(Sketcher.Constraint("DistanceX", pI4, 1, -1, 1, -IX))
except Exception as e:
    MSG("F4 datum X fail: " + str(e))
try:
    sk4.addConstraint(Sketcher.Constraint("DistanceY", pI4, 1, -1, 1, -IZ))
except Exception as e:
    MSG("F4 datum Y fail: " + str(e))
safe_add(sk4, Sketcher.Constraint("Coincident", g_dR, 1, pI4, 1), "F4 datum coincident")
try:
    sk4.addConstraint(Sketcher.Constraint("DistanceX", g_dR, 2, -1, 1, -dR_end[0]))
except Exception as e:
    MSG("F4 datum end X fail: " + str(e))
try:
    sk4.addConstraint(Sketcher.Constraint("DistanceY", g_dR, 2, -1, 1, -dR_end[1]))
except Exception as e:
    MSG("F4 datum end Y fail: " + str(e))
for (gi,pos,tx,ty,nm) in [(g4_0,1,RCa[0],RCa[1],"F4 Oa"),(g4_0,2,RCb[0],RCb[1],"F4 Ob")]:
    try:
        sk4.addConstraint(Sketcher.Constraint("DistanceX", gi, pos, -1, 1, -tx))
    except Exception as e:
        MSG("F4 corner X fail " + nm + ": " + str(e))
    try:
        sk4.addConstraint(Sketcher.Constraint("DistanceY", gi, pos, -1, 1, -ty))
    except Exception as e:
        MSG("F4 corner Y fail " + nm + ": " + str(e))
llenR = math.hypot(RCa[0]-RCd[0], RCa[1]-RCd[1])
add_c(sk4, lambda: Sketcher.Constraint("Distance", g4_3, 1, g4_3, 2, llenR), "F4 long len", doc, "/tmp/crown_F4_diag.fcstd")
safe_add(sk4, Sketcher.Constraint("Perpendicular", g4_0, g4_1), "F4 perp")
doc.recompute()
try:
    if not sk4.Shape.Wires[0].isClosed():
        fail_guidance("F4 SlotRight", "sketch", "slot rect not closed", "missing Coincident", "tried 4 Coincidents", "Which corner gap?", doc, "/tmp/crown_F4_diag.fcstd")
except Exception as e:
    fail_guidance("F4 SlotRight", "sketch check", str(e), "datum/rect", "tried datum+rect", "Send solver message.", doc, "/tmp/crown_F4_diag.fcstd")

pk4 = body.newObject("PartDesign::Pocket", "Pocket_SlotRight")
pk4.Profile = sk4
pk4.Length = CROWN_THK
pk4.Midplane = True
pk4.Reversed = False
doc.recompute()
try:
    nsol = len(body.Shape.Solids)
    valid = body.Shape.isValid()
    bb = body.Shape.BoundBox
    MSG("F4 check: solids=%d valid=%s bbox=%.4f x %.4f x %.4f" % (nsol, str(valid), bb.XLength, bb.YLength, bb.ZLength))
    if nsol != 1 or not valid:
        fail_guidance("F4 SlotRight", "pocket", "solids=%d valid=%s" % (nsol, str(valid)), "coincident boundary OCC", "tried outline+0.05 overshoot", "Adjust overshoot?", doc, "/tmp/crown_F4_diag.fcstd")
except Exception as e:
    fail_guidance("F4 SlotRight", "post-pocket", str(e), "pocket fail", "tried Y symmetric 2.124", "Send exact error.", doc, "/tmp/crown_F4_diag.fcstd")
save_step(doc, "/tmp/crown_F4.fcstd")
MSG("F4 PASS: Right slot VOID top-open, width 0.5, -55deg, inner +1.2994, outer 0.0 at datum I OVERLAP (FIX3 attempt2).")

# ---------------- final ----------------
doc.recompute()
bb = body.Shape.BoundBox
MSG("FINAL: solids=%d valid=%s bbox=%.4f x %.4f x %.4f Zmin=%.4f Zmax=%.4f" % (len(body.Shape.Solids), str(body.Shape.isValid()), bb.XLength, bb.YLength, bb.ZLength, bb.ZMin, bb.ZMax))
MSG("Tree: Body > Sketch_Base > Pad_Base > Sketch_Crown > Pad_Crown > Sketch_SlotLeft > Pocket_SlotLeft > Sketch_SlotRight > Pocket_SlotRight")
save_step(doc, "/home/hatch/workspace/drawing-to-parametric-cad/models/new_drawing_macro_v5_fix3.fcstd")
try:
    body.Shape.exportStep("/home/hatch/workspace/drawing-to-parametric-cad/exports/new_drawing_macro_v5_fix3.step")
    MSG("STEP EXPORT OK: /tmp/crown_final.step")
except Exception as e:
    try:
        Part.export([body], "/home/hatch/workspace/drawing-to-parametric-cad/exports/new_drawing_macro_v5_fix3.step")
        MSG("STEP EXPORT OK via Part.export")
    except Exception as e2:
        MSG("STEP EXPORT FAIL: " + str(e2))
MSG("DONE. Compare to drawing: base 3.6x3.15x2.8, crown 4.800 wide peak ~4.5 thk 2.124, slots 0.5 +35/-55 top-open VOID.")
