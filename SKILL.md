# Drawing to Parametric CAD

## Build the reading sheet first

- Build a reading sheet before you build any geometry.

- Map every dimension and callout on the drawing to one planned feature.

- Mark each mapping with a confidence level and mark every unmapped or conflicting dimension as an open question.

- Record the view that supports each mapping so a later correction can trace back to the drawing.

- Never invent a dimension from a midpoint or a similar feature when the drawing does not state it.

- Read a chain dimension as a partition and a sub-dimension as a position inside one segment, never as an extra segment. A sub-dimension can be the length of a feature inside the segment (a flat section, a shaft protrusion from a face) or the consequence of another feature, so check the arithmetic before inventing a new feature for it (a remaining thickness equals the nominal minus the grind depth).

- Decide a cross-section shape from the end view's outer shape, not from a diameter label alone. A diameter label can be a misread square symbol, a dashed reference or pitch circle, or another feature's representation, so when the end view's outer shape is square the housing is square and the round feature is dropped, not kept alongside it.

- When a size is undimensioned, use the user's estimate and flag it as an estimate, never as a drawing dimension, and never default to a coincident number from another feature.

- Omit a protrusion that is undimensioned and unidentified instead of building it from a guess, and keep it on the omitted list for a later round.

## Ask before you build

- Send the reading sheet and its open questions to the user and wait for confirmation before you build.

- Treat an ambiguous direction as an open question instead of choosing the reading that looks plausible at a glance.

- Check internal gear teeth against external gear teeth explicitly by asking how the teeth face and what they mate with.

- Check a standard dimension against a nonstandard reading explicitly when the standard value and the by-eye value disagree.

- Omit a dimension the user tells you to ignore instead of building it from a guess.

- Build only the features the user confirmed and keep the remaining questions open for the next round.

- Finish one variant before starting the next, and drop a variant the user calls too similar instead of building a near-duplicate to complete a set.

## Build with standard tools and per-feature gates

- Use the standard tool for a standard part before you draw a hand approximation.

- Use the built-in involute gear profile for a gear and keep its module and tooth count parametric.

- Model a threaded hole as a tap drill hole plus a tap callout when the thread is nonstandard or the hole tool cannot hold a custom size.

- Calculate tap drill size as major diameter minus pitch and check it against the basic minor diameter before you cut the hole.

- Verify that the hole tool kept your custom diameters after a recompute before you trust the result.

- Bury tooth wires into the root disk so the gear fuses into one solid instead of touching the rim at points.

- Prefer one sketch with all teeth and one pad when a patterned feature proves unstable on recompute.

- Check each feature after you create it for sketch closure and solid validity and volume and a single solid and a correct feature tree.

- Regenerate only the failed feature instead of rebuilding the whole model when a gate fails.

- Exclude a finishing operation that would destroy a verified face such as a flat rectangle and record the exclusion.

- Mark every feature as body material or a separate or inserted component or a void or slot, and record whether it protrudes or is recessed or is inserted.

- Treat a validation pass that allows one or more solids as a failure of the gate, and require exactly one solid.

- Require a delegated build to deliver the model files first and keep its report to gate numbers and file paths.

- Measure a tapped hole's depth from its face along the tool travel, even when the tool passes through air between solids, and report the material breakdown (face material plus the next solid's stub, gap zero) instead of the nominal depth alone.

- Check the single-solid gate separately from any harness whose overall pass allows one or more solids, and require exactly one solid before delivery.

- For a B-spline model, report the STEP tessellation and the Y=0 section as the true size, because the parametric file's bounding box inflates from the spline poles.

- Verify a delegated build from disk and from an independent STEP read (solids, volume, bounding box, validity, section) before presenting it as finished, and never present a delegate's preview numbers alone.

## Close curved loops from one outline

- Build each curved band as one loop that follows its outer edge and its tip curl and its inner edge and its base segment in order.

- Never close a curved band with a straight line across its interior when its edges do not meet.

- Stop and name the exact missing endpoints and the empty interval between them when a loop cannot close from the supplied outlines.

- Treat a gap with no ink in the supplied outline as missing input instead of permission to invent a straight closure.

- Ask only for the named missing segment, and never ask again for a segment the user already supplied or a later correction shows does not exist.

- Use the plain words the user used for a part instead of inventing a new part name.

- Rebuild from a corrected filled region boundary as one connected loop when that region shows separate arm loops were the wrong topology.

- Label every closure segment that is not a drawing line in the report and give its distance to the nearest drawing ink.

- Seed outline tracing from the trace points the user supplied in the order they supplied them, and never seed it from a prior model curve.

- Smooth only within one selected line, and never average across parallel lines.

- Report a function test as a function test, and leave a live drawing check untested until the user confirms it on the real drawing.

## Compare the model with the drawing

- Compare front and top and side projections of the finished model against the drawing views before delivery.

- Check each confirmed dimension against the model and each open question against the list of omitted features.

- Render preview images from the STEP export with smooth shading and no edge triangulation lines.

- Report the final volume and the gate results and the omitted features with the model files.

- Attach a side view, an end view, and a closeup for any subtle feature (a shallow flat, a small step) with each version, guide the reader to what changed in each view, and name tessellation fan or diagonal lines as rendering artifacts, not geometry.

- Re-attach the key previews and files in the delivery message and point to a durable home for them instead of referring the reader back up the chat.

- When the interior cannot be verified, model the exterior as a single solid on that explicit premise, confirmed by the user, and keep the interior out of scope and on the omitted list.

- For an outline drawing, the test is outline, loop, and shape fidelity, not machining reproduction, so machining information is not required and a catalog outline drawing is a valid input.

## Available connectors

- [GitHub](/opt/hatch/connectors/github/CONNECTOR.md) for storing build scripts and model exports in the project repository.

- Use `muse.connector_search` to find other connectors and `muse.skill_search` to find related skills.

- If nothing here fits, look on the web for a maintained API or MCP server and set it up with [Custom Connectors and MCPs](/opt/muse/skills/custom-connector-setup/SKILL.md), or build a custom connector.

## Alternatives for better results

- Ask for a clearer drawing or a text specification when the drawing leaves a feature unmapped.

- Build from a dictated text specification first when the drawing cannot support a confident reading sheet.

- Keep STEP as an export only and keep the parametric file as the primary artifact so later edits stay in the feature tree.
