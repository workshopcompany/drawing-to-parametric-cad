# Gear Creation Reference - use ONLY when the drawing contains a gear

File name: `GEAR_CREATION_REFERENCE.md`
Language: English only. This file is in English only.

This file is included in the macro prompt ONLY when the drawing contains a gear.
It does not contain part dimensions. Module, tooth count, pressure angle, thickness,
and axis come from the drawing / user-confirmed Q&A for that part.
Do not copy dimensions from another part into this file.

## When to use
- The drawing shows a gear (spur gear, external or internal).
- Use the standard gear tool first. Do not hand-draw trapezoid teeth.
- Do not fall back to a plain cylinder if the gear tool fails. Stop, present
  an alternative or ask a question, per the top principle.

## Tool
- FreeCAD PartDesign InvoluteGear, via the InvoluteGearFeature module.
- This is the headless-safe API. Other creation forms fail headless.

## Exact steps (headless FreeCAD 1.1.4)
1. Import the module:
   `import InvoluteGearFeature`
2. Create the gear profile with a SINGLE string argument only (the name).
   Do NOT pass document, tooth count, module, or pressure angle as arguments.
   `gear = InvoluteGearFeature.makeInvoluteGear("InvoluteGear")`
3. Set properties AFTER creation, from the drawing / Q&A:
   - `gear.NumberOfTeeth = <teeth>`
   - `gear.Modules = "<module> mm"` (example format only, e.g. "0.5 mm")
   - `gear.PressureAngle = "<pressure angle> deg"` (example format only, e.g. "20 deg")
   - `gear.ExternalGear = True` for an external gear, `False` for an internal gear.
   - Standard coefficients, unless the drawing / Q&A says otherwise:
     `gear.AddendumCoefficient = 1.0`
     `gear.DedendumCoefficient = 1.25`
     `gear.RootFilletCoefficient = 0.38`
     `gear.ProfileShiftCoefficient = 0.0`
   - `gear.HighPrecision = True`
4. Add the gear to the Body and recompute:
   `body.Group = body.Group + [gear]`
   `doc.recompute()`
5. Pad the gear profile to the gear thickness from the drawing / Q&A:
   `pad = body.newObject("PartDesign::Pad", "Pad_Gear")`
   `pad.Profile = gear`
   `pad.Length = <gear thickness>`
   `doc.recompute()`
6. Axis mapping - state it explicitly, do not assume it:
   - The InvoluteGear profile is in the XY plane, normal +Z, by default.
   - Map the gear axis to the part axis from the origin rule / Q&A
     (for example, +X output direction, or +Z axial direction).
   - State the local->global mapping with +/- signs for the gear feature,
     as required by principle 2, and place the gear at the correct axial start.

## What NOT to do
- Do NOT use `body.newObject("PartDesign::InvoluteGear")` or
  `doc.addObject("PartDesign::InvoluteGear", ...)`.
  That form is not a document object type in headless FreeCAD 1.1.4
  and fails at the first feature.
- Do NOT use multi-argument `makeInvoluteGear(...)` forms
  (document + name + teeth + module + pressure angle, or similar).
  The verified form takes exactly one string argument: the name.
- Do NOT guess property names. Use exactly: NumberOfTeeth, Modules,
  PressureAngle, ExternalGear, AddendumCoefficient, DedendumCoefficient,
  RootFilletCoefficient, ProfileShiftCoefficient, HighPrecision.
  Note the plural `Modules`, not `Module`.
- Do NOT fall back to a plain tip cylinder, a knurled cylinder, or
  hand-drawn teeth if the gear tool fails. Stop and ask, per the top principle.

## Verification after the gear feature (drawing comparison, NOT volume)
After the gear Pad is complete, before the next feature, verify by comparing
with the drawing for this feature only:
- Tooth count from the profile (wires/edges, not volume).
- Tip diameter, pitch diameter, and root diameter from the profile:
  for an external gear, pitch = module x teeth,
  tip = module x (teeth + 2) with standard addendum,
  root = pitch - 2 x dedendum x module with standard dedendum,
  unless the drawing / Q&A gives different diameters - then the drawing wins.
- Gear thickness (Pad length) against the drawing axial dimension.
- Gear axis direction and axial start position against the drawing / Q&A.
If any of these do not match the drawing, stop at this feature, present
an alternative or ask a question. Do not proceed to the next feature
with a wrong gear profile, and do not judge the gear by volume alone.
