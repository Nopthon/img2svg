# Consolidated finished vectors (opt-in)

Read when the goal is a clean enlarged look: pixel-like antialias speckles, near-duplicate ink shades, pale edge bands and hairline seams hurt more than exact sample fidelity. This mode changes the finished art; keep the faithful trace as the baseline and compare before accepting. It reuses the faithful polyline contour engine — no curve fitting, so magnified boundaries show honest segments.

## Generation

```text
python scripts/consolidate_trace.py --work work/palette --plan work/consolidate-plan.json --output outputs/consolidated.svg
```

The plan uses the same schema and palette fingerprint as the faithful plan; regions may add a `consolidate` settings block.

## Mechanics

- `consolidate` merges near-duplicate palette colors per role with a pixel-count-weighted mean. Only `ink` consolidates by default; other roles keep the shared global palette (`role_merge_distances` 0), so a small pale region cannot turn white. Explicit nonzero overrides are opt-in and need boundary inspection.
- Merging the pale antialias transition pigments into their dominant neighbors is what removes the washed-out, slightly-light look of the faithful trace around edges and shadows.
- `merge_fragments` reassigns tiny pigment islands to the nearest surviving local paint, never to transparency. Ink/detail/highlight use a lower discard threshold; a thin component survives via `keep_long`. If every component of a group is tiny, its largest representative is kept. Discarded ink pieces are recolored within compatible ink pigments, so a dotted-looking line stays one continuous ribbon.
- `component_backings` paints detached edge pieces with the actual local pigment mean, not the region base: a pale highlight must not inherit a dark outline color. Broad silhouettes keep the authored base color.
- `close_small_holes` optionally repairs compact enclosed pinholes (`base_hole_area`, `ink_hole_area`; default OFF). Thin crescents and slits are real negative space and stay open.
- Opaque sources get an opaque native canvas rect. Partial-alpha sources are rejected; use the faithful route there.
- Output keeps semantic `data-region`/`data-tone` groups for editing and visual review.

## Regional settings (`consolidate` block)

| Setting | Effect / caution |
|---|---|
| `merge_distance` 0–50 | RGB distance for ink consolidation; too large flattens ink shading. |
| `role_merge_distances` | Optional per-role overrides, e.g. `{"ink":22,"color":12}`. Nonzero fill distances are opt-in. |
| `epsilon` .05–2 | Contour tolerance, same meaning as the faithful trace. |
| `min_area` 1–100 | Tiny fill-island threshold; long components survive via `keep_long`. |
| `protected_area` 1–100 | Lower threshold for ink/detail/highlight. Not a semantic guarantee. |
| `keep_long` ≥1 | Preserve a thin component whose bounding-box extent reaches this length. |
| `overlap` 0–2 | Same-paint stroke width; ink overlap is capped. Too much thickens boundaries. |
| `base_hole_area`, `ink_hole_area` 0–100 | Compact pinhole repair; opaque sources only. |

CLI: `--merge-distance 22 --min-area 12 --epsilon .55 --overlap .4`. Every distance/area is in original pixels; scale for different resolutions.

## Review and regression

Run the normal `visual_review.py compare` against the reference, then inspect zoom crops of long contours, thin strokes, highlights and region boundaries at native magnification. Removing speckles must not erase a real curved line or thicken a stroke; a full-frame metric cannot see either defect. Compare `lab_cast`/`lab_delta_e00_mean` in `comparison.json` to confirm the consolidated route actually reduces the lightness bias.

After changing the algorithm run `python scripts/consolidate_test.py --work work/consolidate-tests` (separate scratch directory). It checks ink consolidation, island absorption, role palette preservation, protected highlights, opaque canvas and partial-alpha rejection. These are regressions, not proof that a new image looks right.
