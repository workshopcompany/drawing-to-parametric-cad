# Outline Profile Guide

How to make an outline profile with the **outline snap tool**
(`outline_snap_tool.html`), and how that profile is used by the
drawing-to-parametric-CAD program.

The tool runs entirely in your browser. Nothing is uploaded anywhere.
The language toggle in the header switches between English (default)
and Korean; if a Korean string is missing, English is shown instead.

## What an outline profile is

An outline profile is the **shape** of one feature, traced as an ordered
list of points on top of the drawing image. The program treats it as a
shape candidate: it copies the traced points exactly, and takes
dimensions and datums from the drawing itself — never from pixel
positions. A profile is not a dimensioned sketch. It answers "what
shape?", while the drawing answers "how big, and measured from where?"

A profile is used for the feature it shows (for example the front jaw
of the bracket). Things the profile cannot show — extrusion thickness,
a base or lower section, a feature not visible in that view — are still
asked as questions or taken from the drawing.

## Open the tool

- From the run program home page: **Recent runs** card →
  **outline snap tool** (opens in a new tab), or
- Open `outline_snap_tool.html` directly from disk as a local file.

Then click **Open drawing** and pick a PNG/JPG scan or capture of the
drawing. Drag and drop onto the page works too.

## 1. Calibration (px → mm)

A profile is useless without a scale. Calibration turns pixels into mm.

1. Click the **Calibration** mode, then click two points on the drawing
   whose real distance you know, and enter that distance. The tool
   computes the scale (mm/px). If X and Y scales differ, enter them
   separately.
2. Click the **Origin** mode and click the point that is mm (0, 0).
3. If the drawing has a datum line (for example datum B), click the
   **Datum line** mode and click its horizontal position. Y values are
   then measured from that line (above is +).
4. For scans stitched from pieces with different scales, use
   **piecewise calibration**: the datum line splits the drawing into an
   above section and a below section, each with its own center X and
   scales.

Without calibration the tool shows "no calibration (mm conversion
unavailable)" and exports pixel coordinates only.

## 2. Trace the outline

### Point selection (default mode)

Click roughly along the outline. Each click snaps to the **center** of
the nearest dark line within the snap radius — this is the point of the
mode: you click approximately, the tool finds the line.

- **Snap radius** (Snap settings): how far from your click the tool may
  look for a line. If a point lands on the wrong line, lower the radius
  or raise the **ink threshold** (the mask preview shows which pixels
  count as ink; raise the threshold if thin lines disappear).
- **Snap on click** (on by default): turn it off when you need a point
  exactly where you clicked, not on a line. The point is then tagged
  "manual".
- **Re-snap on drop**: when on, dragging a point re-snaps it to the
  nearest line on release; when off, the dragged position is final.
- **Loupe**: a 6× magnifier that follows the cursor, so you can see
  exactly which pixel you are clicking.
- Points are numbered (# labels) in click order. The point table shows
  snapped px, mm, and click order. Click a row to select a point;
  double-click on the canvas inserts a point there (later point numbers
  shift by +1, click order stays); right-click a point deletes it.
  Everything is undoable.

### Line selection mode

Click the middle of a line (not a crossing). The tool follows that line
in its tangent direction, bridging small dashed gaps, and stops at
crossings. It produces an ordered polyline for that line only.

### Straight draw mode

Click vertices in order for straight edges (base sides, slot corners).
Double-click, Enter, or **Finish** ends the line; clicking near the
first vertex closes it. Use this for edges you want to set by eye, not
by tracing ink.

## 3. Check closure and fill

A closed outline is a body. The **Fill** panel tells you, for the point
outline, whether it is closed ("closed — filled") or open ("open — no
auto fill"), and its area. The canvas fills a closed outline in green.

- Green inside = body. Holes and slots must stay EMPTY (white). If a
  slot or hole is filled green, the outline is wrong — fix the points.
- Top-open notches in the outline **are** the slots. Do not cut them
  again as separate pockets later; the profile already contains them.
- If the outline does not close automatically, or the drawing has no
  line to follow, use **Paint** mode: drag the brush, or tap inside a
  face to fill that whole face at once. Tap with the eraser on to clear
  one face. A face that is not closed is not filled (the tool says so
  instead of flooding the drawing).

## 4. Smooth curves, then one curve

Straight chords between sparse points look polygonal on a curved edge.
Two steps:

1. **Connect with curve**: enter a start and end point number and
   press **Connect with curve**. The range is connected with a
   Catmull-Rom spline through your points, and intermediate points are
   added along it (teal diamonds, "smooth" tag). The curve passes
   exactly through your points; only the chords between them become
   curved. Edit the point curve as you like (drag, delete, insert).
2. **Make one curve**: with the same start/end numbers, press
   **Make one curve**. The many points of that range become **one
   curve**: the intermediate smooth points are removed and the range is
   drawn and exported as a single spline through the remaining points
   (teal line, "curve" tag). After merging, dragging an anchor reshapes
   the curve; inserting a point inside the range extends it; deleting
   an endpoint dissolves it back to chords. **Unmerge** only removes
   the curve display — removed intermediate points come back with undo
   only. Ranges that overlap an existing curve are rejected; ranges
   that only touch at an endpoint are allowed.

Do not merge a whole outline into one curve when it has sharp corners
(slot corners, base corners): a single spline would round them. Merge
curved runs only; keep straight runs as lines and corners as corners.

## 5. Export

- **Export JSON**: the point list (rough px, snapped px, mm, click
  order, how each point was added), the line polylines, merged curves
  (anchors + sampled spline, px and mm), and the fill polygons for
  closed outlines. This is the file the run program reads.
- **Fill PNGs** ("drawing + fill" and "fill only"): pictures of the
  filled shape for checking by eye. Send both when describing a shape:
  one shows position on the drawing, the other shows the shape alone.

## 6. Attach to a run

In the run program form, attach the exported JSON under **Outline
attachment**. A JSON outline carries its own calibration, so no width
is needed. (For an outline *image* traced by the program instead, the
real width in mm is required so pixels become mm.)

## How the run program uses the profile

- If the outline is closed, the run uses the filled polygon (which
  follows merged curves) as the feature's shape, and builds the sketch
  as a polyline through those points, in order, closing back to the
  first point.
- Merged curves are exported as curve spans (`curves` in the JSON:
  anchors + sampled spline) so a later model stage can build one
  B-spline per span instead of a polyline. The current run stage still
  builds the polyline; the curve spans mark which runs are single
  curves.
- The profile never overrides the drawing: if a traced size disagrees
  with a dimension, the dimension wins and the profile is re-checked.

## Things to avoid

- Do not trace dimension lines, extension lines, center lines, or the
  title block. Trace the part edges only.
- Ignore handwriting, red/blue inspection marks, and marker lines.
- Do not guess a shape the drawing does not show: if extension or
  datum lines block the reading, ask for a cleaner outline instead of
  inventing points.
- Do not scale or move the drawing image after calibrating; the
  calibration belongs to that image size.
- One outline per feature view. A front-view profile does not describe
  the base section or the thickness — those come from their own views
  or dimensions.
