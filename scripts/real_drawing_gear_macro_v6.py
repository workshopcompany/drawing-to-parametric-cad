# Gear macro v6 - FreeCAD 1.1.4 headless-safe
# Drawings + GEAR_QA_CONFIRMED + USER CORRECTIONS applied
#
# ORIGIN RULE: X=0 gear tip, +X output toward body. All X from origin with signs.
# STACK: gear 0-5 (D tip 16.001) + step 5-6 (D16x1) + body 6-13 (D22x7)
#        + boss 13-14.5 (D10x1.5 Pad) / recess 13-11.5 (D12-D10 ring Pocket 1.5)
#        + bore D7.93 through 0-14.5 + body chamfer C0.5x2 + flat -Z (remain 21)
#        + 3x tap-drill D3.73 radial to bore at X=9.5, angles 270,30,150 deg
#        0deg=+Y, 90deg=+Z in YZ plane. Flat centre 270deg (-Z) is datum.
#
# FEATURE ORDER MUST STAY:
#  1 Pad_Gear, 2 Pad_Step, 3 Pad_Body, 4 Pad_Boss, 5 Pocket_Recess,
#  6 Pocket_Bore, 7 Chamfer_Body, 8 Pocket_Flat, 9 Pocket_Tap x3
# QUESTIONS / PROVISIONAL (ask user if wrong, do not invent as drawing):
#  Q-A Tap axial X=9.5 is provisional (body mid 6-13). Confirm if drawing gives other.
#  Q-B Tap pocket length 8.0 is design choice to break into bore and stop in air.
#      Wall 7.035 (round) / 6.035 (flat), 8.0 stops inside bore void, not opposite wall.
#  Q-C Flat plane Z=-10 (1mm off D22), Y oversize +/-11.5 for clean cut. Confirm side -Z.
#  Q-D Chamfer edge auto-search radius 11 at X=6/13. If names differ, macro stops and asks.
# Bolt: separate fastener, modelling excluded.

import FreeCAD as App
import Part
import Sketcher
import math
import InvoluteGearFeature

DOC_NAME = "GearPart"
FCSTD_FINAL = "/tmp/gear_v6.fcstd"
STEP_FINAL = "/tmp/gear_v6.step"

def log(msg):
    print("[GEAR_V6] " + msg)

def save_step(doc, path):
    try:
        doc.saveAs(path)
        log("PASS save " + path)
    except Exception as e:
        log("WARN save failed " + path + " : " + str(e))

def check_single_valid(body, step):
    doc = App.ActiveDocument
    doc.recompute()
    sh = body.Shape
    if sh.isNull():
        raise RuntimeError(step + " FAILED null shape")
    if not sh.isValid():
        raise RuntimeError(step + " FAILED invalid shape")
    ns = len(sh.Solids)
    if ns != 1:
        raise RuntimeError(step + " FAILED solids=%d expected 1" % ns)
    log("PASS " + step + " valid single solid")
    return sh

def add_distX_to_origin(sk, gidx, pos, target):
    # Principle 2 note: (point,origin) solves as point = -value, so value = -target
    v = -float(target)
    try:
        sk.addConstraint(Sketcher.Constraint('DistanceX', gidx, pos, -1, 1, v))
        return
    except Exception as e1:
        pass
    # fallback RootPoint -3
    sk.addConstraint(Sketcher.Constraint('DistanceX', gidx, pos, -3, 1, v))

def add_distY_to_origin(sk, gidx, pos, target):
    v = -float(target)
    try:
        sk.addConstraint(Sketcher.Constraint('DistanceY', gidx, pos, -1, 1, v))
        return
    except Exception as e1:
        pass
    sk.addConstraint(Sketcher.Constraint('DistanceY', gidx, pos, -3, 1, v))

def constrain_circle_at_origin(sk, idx, diameter):
    sk.addConstraint(Sketcher.Constraint('Diameter', idx, float(diameter)))
    add_distX_to_origin(sk, idx, 3, 0.0)
    add_distY_to_origin(sk, idx, 3, 0.0)

YZ_ROT = App.Rotation(App.Vector(1, 1, 1), 120)
# YZ sketch mapping: local X -> global +Y, local Y -> global +Z, normal -> global +X

def make_yz_sketch(body, name, x_off):
    sk = body.newObject('Sketcher::SketchObject', name)
    sk.MapMode = 'Deactivated'
    # sketch plane YZ, normal +X, placed at segment-start X
    sk.Placement = App.Placement(App.Vector(float(x_off), 0, 0), YZ_ROT)
    return sk

# ---- document / body ----
doc = App.newDocument(DOC_NAME)
App.setActiveDocument(DOC_NAME)
doc = App.ActiveDocument
body = doc.addObject('PartDesign::Body', 'Body')
doc.recompute()
log("PASS Body created")

try:
    # ================= 1. GEAR Pad =================
    # Gear profile in XY normal +Z by default.
    # Map: local X -> global -Z, local Y -> global +Y, normal -> global +X
    # Placement base (0,0,0) with Ry 90. Pad +X 5 => X 0-5 material, air +X beyond.
    log("STEP 1 Gear Pad D=mod0.5x30T thick 5 X0-5")
    gear = InvoluteGearFeature.makeInvoluteGear("InvoluteGear")
    gear.NumberOfTeeth = 30
    gear.Modules = "0.5 mm"
    gear.PressureAngle = "20 deg"
    gear.ExternalGear = True
    gear.AddendumCoefficient = 1.0
    gear.DedendumCoefficient = 1.25
    gear.RootFilletCoefficient = 0.38
    gear.ProfileShiftCoefficient = 0.0
    gear.HighPrecision = True
    gear.Placement = App.Placement(App.Vector(0, 0, 0), App.Rotation(App.Vector(0, 1, 0), 90))
    try:
        body.Group = body.Group + [gear]
    except:
        g = list(body.Group)
        g.append(gear)
        body.Group = g
    doc.recompute()
    pad_gear = body.newObject("PartDesign::Pad", "Pad_Gear")
    pad_gear.Profile = gear
    pad_gear.Length = 5.0
    # Pad direction +normal = +X, Reversed False, sketch at X=0 to +X
    pad_gear.Reversed = False
    doc.recompute()
    check_single_valid(body, "1 Pad_Gear tip~16.001 pitch15 root13.75 thick5")
    save_step(doc, "/tmp/gear_v6_s1_gear.fcstd")

    # ================= 2. STEP Pad D16x1 X5-6 =================
    # YZ sketch normal +X at X=5. Pad +X 1 => 5-6 material. Air -X gear side.
    log("STEP 2 Step Pad D16 thick1 X5-6")
    sk_step = make_yz_sketch(body, "Sketch_Step", 5.0)
    sk_step.addGeometry(Part.Circle(App.Vector(0, 0, 0), App.Vector(0, 0, 1), 8.0), False)
    constrain_circle_at_origin(sk_step, 0, 16.0)
    doc.recompute()
    pad_step = body.newObject("PartDesign::Pad", "Pad_Step")
    pad_step.Profile = sk_step
    pad_step.Length = 1.0
    pad_step.Reversed = False
    doc.recompute()
    check_single_valid(body, "2 Pad_Step D16 X5-6")
    save_step(doc, "/tmp/gear_v6_s2_step.fcstd")

    # ================= 3. BODY Pad D22x7 X6-13 =================
    # YZ normal +X at X=6. Pad +X 7 => 6-13. Start = prev end.
    log("STEP 3 Body Pad D22 thick7 X6-13")
    sk_body = make_yz_sketch(body, "Sketch_Body", 6.0)
    sk_body.addGeometry(Part.Circle(App.Vector(0, 0, 0), App.Vector(0, 0, 1), 11.0), False)
    constrain_circle_at_origin(sk_body, 0, 22.0)
    doc.recompute()
    pad_body = body.newObject("PartDesign::Pad", "Pad_Body")
    pad_body.Profile = sk_body
    pad_body.Length = 7.0
    pad_body.Reversed = False
    doc.recompute()
    check_single_valid(body, "3 Pad_Body D22 X6-13")
    save_step(doc, "/tmp/gear_v6_s3_body.fcstd")

    # ================= 4. BOSS Pad D10x1.5 X13-14.5 =================
    # YZ normal +X at X=13 (body end). Pad +X 1.5 outward to air. Material 13-14.5.
    log("STEP 4 Boss Pad D10x1.5 X13-14.5")
    sk_boss = make_yz_sketch(body, "Sketch_Boss", 13.0)
    sk_boss.addGeometry(Part.Circle(App.Vector(0, 0, 0), App.Vector(0, 0, 1), 5.0), False)
    constrain_circle_at_origin(sk_boss, 0, 10.0)
    doc.recompute()
    pad_boss = body.newObject("PartDesign::Pad", "Pad_Boss")
    pad_boss.Profile = sk_boss
    pad_boss.Length = 1.5
    pad_boss.Reversed = False
    doc.recompute()
    check_single_valid(body, "4 Pad_Boss D10 X13-14.5 protrude +1.5")
    save_step(doc, "/tmp/gear_v6_s4_boss.fcstd")

    # ================= 5. RECESS Pocket ring D12-D10 depth1.5 =================
    # YZ normal +X at X=13. Pocket -X by default (Reversed False) into body to 11.5.
    # Material side -X, air side +X. Ring only, boss D10 untouched.
    log("STEP 5 Recess Pocket ring D12/D10 depth1.5 X13-11.5")
    sk_rec = make_yz_sketch(body, "Sketch_Recess", 13.0)
    sk_rec.addGeometry(Part.Circle(App.Vector(0, 0, 0), App.Vector(0, 0, 1), 6.0), False)  # 0 outer D12
    sk_rec.addGeometry(Part.Circle(App.Vector(0, 0, 0), App.Vector(0, 0, 1), 5.0), False)  # 1 inner D10
    sk_rec.addConstraint(Sketcher.Constraint('Diameter', 0, 12.0))
    sk_rec.addConstraint(Sketcher.Constraint('Diameter', 1, 10.0))
    add_distX_to_origin(sk_rec, 0, 3, 0.0)
    add_distY_to_origin(sk_rec, 0, 3, 0.0)
    sk_rec.addConstraint(Sketcher.Constraint('Coincident', 0, 3, 1, 3))
    doc.recompute()
    pkt_rec = body.newObject("PartDesign::Pocket", "Pocket_Recess")
    pkt_rec.Profile = sk_rec
    pkt_rec.Length = 1.5
    pkt_rec.Reversed = False  # -X into body
    doc.recompute()
    check_single_valid(body, "5 Pocket_Recess ring D12-D10 depth1.5")
    save_step(doc, "/tmp/gear_v6_s5_recess.fcstd")

    # ================= 6. BORE Pocket D7.93 through 0-14.5 =================
    # YZ normal +X at X=14.5 (boss top). Pocket -X 14.5 to X=0.
    # Material both sides except bore void, cut goes -X through all.
    log("STEP 6 Bore Pocket D7.93 through X14.5-0")
    sk_bore = make_yz_sketch(body, "Sketch_Bore", 14.5)
    sk_bore.addGeometry(Part.Circle(App.Vector(0, 0, 0), App.Vector(0, 0, 1), 7.93 / 2.0), False)
    constrain_circle_at_origin(sk_bore, 0, 7.93)
    doc.recompute()
    pkt_bore = body.newObject("PartDesign::Pocket", "Pocket_Bore")
    pkt_bore.Profile = sk_bore
    pkt_bore.Length = 14.5
    pkt_bore.Reversed = False
    doc.recompute()
    check_single_valid(body, "6 Pocket_Bore D7.93 through 14.5")
    save_step(doc, "/tmp/gear_v6_s6_bore.fcstd")

    # ================= 7. BODY CHAMFER C0.5 x2 =================
    # Select body D22 outer circular edges at X=6 and X=13. NOT bore.
    # CRITICAL: capture previous feature BEFORE newObject to avoid self-link DAG.
    log("STEP 7 Body Chamfer C0.5 on D22 edges X6 X13")
    prev_feat = pkt_bore  # capture before Chamfer becomes Tip
    doc.recompute()
    pshape = prev_feat.Shape
    cand = []
    for i, e in enumerate(pshape.Edges):
        try:
            c = e.Curve
        except:
            continue
        if not hasattr(c, 'Radius'):
            continue
        try:
            r = float(c.Radius)
        except:
            continue
        if abs(r - 11.0) > 0.06:
            continue
        try:
            cx = float(c.Center.x)
            ax = c.Axis
            axx = abs(float(ax.x))
        except:
            continue
        if axx < 0.95:
            continue
        if abs(cx - 6.0) < 0.08 or abs(cx - 13.0) < 0.08:
            cand.append("Edge%d" % (i + 1))
    log("Chamfer candidates " + str(cand))
    if len(cand) < 2:
        # try fallback using body.Shape (same topology index may shift, still ask)
        log("WARN chamfer edge search found <2, will FAIL and ask")
        raise RuntimeError("7 Chamfer_Body FAILED edge search found " + str(cand) + " need 2 edges D22 at X6 X13. QUESTION: confirm body edge topology.")
    chm = body.newObject("PartDesign::Chamfer", "Chamfer_Body")
    chm.Base = (prev_feat, cand[:2])
    chm.Size = 0.5
    doc.recompute()
    check_single_valid(body, "7 Chamfer_Body C0.5 x2")
    # face presence: small conical faces from chamfer must exist
    cone_count = 0
    for f in body.Shape.Faces:
        try:
            s = f.Surface
        except:
            continue
        if isinstance(s, Part.Cone):
            try:
                # chamfer cone near r~10.7, half-angle ~45deg
                if abs(float(s.Radius) - 10.7) < 1.0:
                    cone_count += 1
            except:
                cone_count += 1
    log("Chamfer cone faces found %d" % cone_count)
    if cone_count < 2:
        # also accept small planar? log but do not silently pass
        log("WARN chamfer conical face check <2, inspect manually")
    save_step(doc, "/tmp/gear_v6_s7_chamfer.fcstd")

    # ================= 8. FLAT Grinding Pocket =================
    # YZ normal +X at X=13. Pocket -X 7 to X=6. Removes bottom strip Z -11.5 to -10.
    # Flat at -Z, remaining height 21 (top +11 to flat -10). Material +Z, air -Z.
    # Local X=global Y, local Y=global Z.
    log("STEP 8 Flat Pocket 1mm at -Z X13-6 remain21")
    sk_flat = make_yz_sketch(body, "Sketch_Flat", 13.0)
    x1, y1 = -11.5, -11.5
    x2, y2 = 11.5, -11.5
    x3, y3 = 11.5, -10.0
    x4, y4 = -11.5, -10.0
    sk_flat.addGeometry(Part.LineSegment(App.Vector(x1, y1, 0), App.Vector(x2, y2, 0)), False)  # 0 bottom
    sk_flat.addGeometry(Part.LineSegment(App.Vector(x2, y2, 0), App.Vector(x3, y3, 0)), False)  # 1 right
    sk_flat.addGeometry(Part.LineSegment(App.Vector(x3, y3, 0), App.Vector(x4, y4, 0)), False)  # 2 top
    sk_flat.addGeometry(Part.LineSegment(App.Vector(x4, y4, 0), App.Vector(x1, y1, 0)), False)  # 3 left
    sk_flat.addConstraint(Sketcher.Constraint('Coincident', 0, 2, 1, 1))
    sk_flat.addConstraint(Sketcher.Constraint('Coincident', 1, 2, 2, 1))
    sk_flat.addConstraint(Sketcher.Constraint('Coincident', 2, 2, 3, 1))
    sk_flat.addConstraint(Sketcher.Constraint('Coincident', 3, 2, 0, 1))
    sk_flat.addConstraint(Sketcher.Constraint('Horizontal', 0))
    sk_flat.addConstraint(Sketcher.Constraint('Horizontal', 2))
    sk_flat.addConstraint(Sketcher.Constraint('Vertical', 1))
    sk_flat.addConstraint(Sketcher.Constraint('Vertical', 3))
    sk_flat.addConstraint(Sketcher.Constraint('DistanceX', 0, 1, 0, 2, 23.0))
    sk_flat.addConstraint(Sketcher.Constraint('DistanceY', 1, 1, 1, 2, 1.5))
    # p1 (-11.5,-11.5): value = -target = +11.5 (inversion note)
    try:
        sk_flat.addConstraint(Sketcher.Constraint('DistanceX', 0, 1, -1, 1, 11.5))
    except:
        sk_flat.addConstraint(Sketcher.Constraint('DistanceX', 0, 1, -3, 1, 11.5))
    try:
        sk_flat.addConstraint(Sketcher.Constraint('DistanceY', 0, 1, -1, 1, 11.5))
    except:
        sk_flat.addConstraint(Sketcher.Constraint('DistanceY', 0, 1, -3, 1, 11.5))
    doc.recompute()
    pkt_flat = body.newObject("PartDesign::Pocket", "Pocket_Flat")
    pkt_flat.Profile = sk_flat
    pkt_flat.Length = 7.0
    pkt_flat.Reversed = False  # -X from 13 to 6
    doc.recompute()
    check_single_valid(body, "8 Pocket_Flat -Z remain21")
    save_step(doc, "/tmp/gear_v6_s8_flat.fcstd")

    # ================= 9. TAP Pockets 3x D3.73 =================
    # Radial holes at X=9.5 from outer surface to bore only (empty holes).
    # Angles: 270 (-Z flat centre), 30, 150. 0deg=+Y 90deg=+Z.
    # Each sketch: normal = outward radial dir, placed at outer point.
    # Pocket -normal = inward, Length 8.0, Reversed False. Material outward, air bore.
    log("STEP 9 Taps 3x D3.73 radial X9.5")
    tap_angles = [270.0, 30.0, 150.0]
    tap_diam = 3.73
    tap_len = 8.0
    tap_X = 9.5
    for k, th in enumerate(tap_angles):
        rad = math.radians(th)
        dy = math.cos(rad)
        dz = math.sin(rad)
        # outer radius: 10 at flat (270), 11 elsewhere
        outer_r = 10.0 if abs(th - 270.0) < 0.01 else 11.0
        ox = tap_X
        oy = dy * outer_r
        oz = dz * outer_r
        # rotation about X by (th-90) maps local +Z to outward dir
        ang = th - 90.0
        rot = App.Rotation(App.Vector(1, 0, 0), ang)
        sk = body.newObject('Sketcher::SketchObject', "Sketch_Tap%d" % (k + 1))
        sk.MapMode = 'Deactivated'
        # local Z -> global outward dir (0,dy,dz), local origin -> outer point
        sk.Placement = App.Placement(App.Vector(ox, oy, oz), rot)
        sk.addGeometry(Part.Circle(App.Vector(0, 0, 0), App.Vector(0, 0, 1), tap_diam / 2.0), False)
        constrain_circle_at_origin(sk, 0, tap_diam)
        doc.recompute()
        pkt = body.newObject("PartDesign::Pocket", "Pocket_Tap%d" % (k + 1))
        pkt.Profile = sk
        pkt.Length = tap_len
        pkt.Reversed = False  # -normal = inward to bore
        doc.recompute()
        check_single_valid(body, "9 Pocket_Tap%d angle%.0f" % (k + 1, th))
        save_step(doc, "/tmp/gear_v6_s9_tap%d.fcstd" % (k + 1))

    # ---- final face-presence verification (not volume) ----
    doc.recompute()
    cyl_tap = 0
    for f in body.Shape.Faces:
        try:
            s = f.Surface
        except:
            continue
        if isinstance(s, Part.Cylinder):
            try:
                if abs(float(s.Radius) - 1.865) < 0.03:
                    cyl_tap += 1
            except:
                pass
    log("Tap cylindrical faces r1.865 found %d need >=3" % cyl_tap)
    if cyl_tap < 3:
        raise RuntimeError("9 Taps FAILED face presence %d<3. QUESTION: check tap direction/length/angles." % cyl_tap)
    else:
        log("PASS taps face presence 3 places")

    # ---- save / export ----
    save_step(doc, FCSTD_FINAL)
    try:
        import Import
        Import.export([body], STEP_FINAL)
        log("PASS STEP export " + STEP_FINAL)
    except Exception as e:
        # fallback Part export
        body.Shape.exportStep(STEP_FINAL)
        log("PASS STEP fallback export " + STEP_FINAL)
    log("DONE gear v6 complete")
    log("Tree: Pad_Gear Pad_Step Pad_Body Pad_Boss Pocket_Recess Pocket_Bore Chamfer_Body Pocket_Flat Pocket_Tap1-3")

except Exception as ex:
    log("FAIL " + str(ex))
    try:
        doc.saveAs("/tmp/gear_v6_diagnostic.fcstd")
        log("Diagnostic saved /tmp/gear_v6_diagnostic.fcstd")
    except Exception as e2:
        log("Diagnostic save failed " + str(e2))
    # Re-raise with question for user per top principle
    # QUESTION TO USER: see message above (edge search / tap faces / chamfer). What is needed to proceed?
    raise
