# Evidence-driven local repair

Retain the first acceptable SVG. For each defect record crop, observation, hypothesis, one targeted change and the reinspection outcome.

| Defect | Likely cause | Action |
|---|---|---|
| Object disappears or paints in the wrong phase | Ownership/role | Check overlay; repair polygon, filter or late assignment |
| Detail already wrong in quantized preview | Palette preparation | Adjust focus/colors/denoise; re-author stale palette IDs |
| Fine line lost only in SVG | Tolerance/overlap | Lower regional epsilon; inspect original-resolution crop |
| Isolated dots on a flat patch | Noise or real texture | Compare the reference; selectively enable conservative cleanup |
| Thick edges, halos, dark intersections | Overlap/compositing | Reduce regional overlap; check alpha and white-background RGB |
| Different colors across apps | Unsupported paint or style | Use literal paint; render independently |

Faithful tracing retains texture and small pigment islands. One path can hold thousands of disconnected subpaths; fewer fragments is not automatically better.

## Local cleanup

Enable cleanup only in a chosen region. It merges compact tiny opaque islands into neighboring paint of the SAME role, bounded by RGB distance; it does not erase to transparency or cross object/alpha boundaries. Ink, detail and highlight roles are protected by default. Recheck changed pixels: low-contrast marks may be deliberate. Never replace a better baseline only because a new file is smaller.

## Acceptance evidence

Comparison includes the full render, critical crops and high-error tiles; RGB is measured on white, alpha separately, and edge recall/precision within two original pixels. These locate differences, not semantic correctness. After viewing, fill the review with feature-specific observations (e.g. "small highlights stay separate; outline continuous; adjacent fills do not bleed across a boundary"). Use fail/unverified where appropriate; never infer passes from metrics. After geometry changes, regenerate comparison and update review hashes. When tools prevent further inspection, deliver the best result with specific unverified limits.

## Multimodal decisions that scripts cannot make

| Agent observation | Concrete intervention | Evidence to re-open |
|---|---|---|
| Two similarly coloured areas are different overlapping objects | Separate spatial regions with local colour roles | Ownership overlay and overlap crop |
| A tiny mark changes expression or recognition | Tight checkpoint and protected regional epsilon/merge budget | Reference and candidate crop at original scale |
| A large dark patch is material, not an outline | Keep its colour role; assign ink only to observed contours | Role overlay and comparison crop |
| Texture is intentional only in one area | Preserve that region and permit cleanup elsewhere | Matching texture crops, not whole-image averages |
| Smaller output has halos or changes negative space | Reject it or lower overlap only in the affected region | Same crop on light and dark backgrounds |

The model can author a small native curve or primitive for a sparse graphic where tracing makes needless nodes; use the manual route. Never fill in invisible structure from imagination.

## Bounded candidate comparison

`visual_review.py candidates IMAGE --work W --plan PLAN --output NEW_DIRECTORY`
generates faithful/balanced/compact trace candidates by default. `--fidelities 100,75,55`
narrows the search; at most five are accepted. Preparation is fixed so comparisons
remain meaningful. Existing candidate directories are not overwritten.

Colour error is screened on white and black backgrounds, alpha separately, and
edges plus every critical crop individually. `--max-bytes` is a real screening
constraint here; it remains a warning in ordinary trace. A null proposal means
no candidate met the requested numeric constraints. Do not quietly relax them.

The agent must still compare the panels and crops, record its selected candidate
and why it preserves the image's defining features, and audit the selected review.
Audit verifies evidence records and SVG identity, not whether anyone truly saw the
image. If the visual decision conflicts with a numerical screen, explain the
specific mismatch and any unmet user constraint rather than declaring a silent pass.

Changing preparation invalidates palette indices; changing the plan requires a new
comparison. Keep the accepted baseline, and explain each local repair with its
observed result. Fewer paths or smaller XML alone is not better reconstruction.
