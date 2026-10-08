# Visual access

Confirm the reference reaches the model as image content, not just a path or model branding. Establish pixel-grounded observations: major objects, an overlap relationship and a distinctive detail.

`visual_review.py inspect` produces an overview grid, original-resolution tiles and a coordinate manifest. Captions sit outside crops; boxes refer to EXIF-normalized original pixels. `--roi` and CLI ROI args use original pixels; plan coordinates may be scaled while preserving aspect ratio.

Without actual visual access, deterministic structural checks may continue, but label the result visually unverified.

## Reduce interpretation load

- Review ownership, roles, contour detail and replay separately, with fixed crop coordinates between iterations.
- Use palette IDs from the actual atlas; never transplant example indices.
- Tools supply exact contours; the model supplies semantic masks and corrections. Broad polygons plus color filters often suffice.
- Repair uncertain overlaps with late assignments to existing regions, then recheck the crop.
- Handwrite curves only for a small observed feature; do not invent hidden anatomy.

## Handoff

Keep the inspection manifest, tiles, `palette.json`, `prepared.npz`, prepare reports, `plan.json`, best SVG, comparison panels, `comparison.json` and the authored review. Palette fingerprints catch stale color IDs; SVG hashes catch reviewing an old output. Give the next agent a specific defect, not a vague "improve quality".

## Fair comparison

Use identical prepared data, plan and script versions; differences there reflect configuration, not semantic ability. Hold preparation fixed and compare independently authored plans on identical crops. A simple fixture passing does not demonstrate complex-illustration skill.
