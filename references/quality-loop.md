# Evidence-driven local repair

Retain the first acceptable SVG. For each defect record crop, observation, hypothesis, one targeted change and the reinspection outcome.

| Defect | Likely cause | Action |
|---|---|---|
| Object disappears or paints in the wrong phase | Ownership/role | Check overlay; repair polygon, filter or late assignment |
| Detail already wrong in quantized preview | Palette preparation | Adjust focus/colors/denoise; re-author stale palette IDs |
| Fine line lost only in SVG | Tolerance/overlap | Lower regional epsilon; inspect original-resolution crop |
| Isolated dots on a flat patch | Noise or real texture | Compare the reference; selectively enable conservative cleanup |
| Thick edges, halos, dark intersections | Overlap/compositing | Reduce regional overlap; check alpha and white-background RGB |
| Finished image correct but replay fragments | Centerline graph | Compare connected/legacy pencil; adjust replay or author curves |
| Angular replay | Simplification | Lower replay epsilon or hand-fit a Bézier |
| Different colors across apps | Unsupported paint or style | Use literal paint; render independently |

Faithful tracing retains texture and small pigment islands. One path can hold thousands of disconnected subpaths; fewer fragments is not automatically better.

Connected replay estimates one width per centerline and cannot recover pressure, hidden strokes or exact order. Final filled outlines keep visible width variation; exact tapered replay needs authored geometry.

## Local cleanup

Enable cleanup only in a chosen region. It merges compact tiny opaque islands into neighboring paint of the SAME role, bounded by RGB distance; it does not erase to transparency or cross object/alpha boundaries. Ink, detail and highlight roles are protected by default. Recheck changed pixels: low-contrast marks may be deliberate. Never replace a better baseline only because a new file is smaller.

## Acceptance evidence

Comparison includes the full render, critical crops and high-error tiles; RGB is measured on white, alpha separately, and edge recall/precision within two original pixels. These locate differences, not semantic correctness. After viewing, fill the review with feature-specific observations (e.g. "small highlights stay separate; outline continuous; adjacent fills do not bleed across a boundary"). Use fail/unverified where appropriate; never infer passes from metrics. After geometry changes, regenerate comparison and update review hashes. When tools prevent further inspection, deliver the best result with specific unverified limits.
