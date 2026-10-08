# Painting plan

Read the current `palette.json` before choosing indices. Coordinates refer to `coordinate_size` (same aspect ratio as the original); output uses original pixel dimensions.

```json
{
  "title": "Reference reconstruction",
  "coordinate_size": [640, 960],
  "checkpoints": [{"id": "leaf-edge", "box": [70,30,290,240], "critical": true}],
  "default": {"id": "paper", "name": "Background paper", "base": "#fffaf3", "phase": "background"},
  "roles": {"ink": [0]},
  "regions": [
    {
      "id": "leaf-ornament", "name": "Leaf ornament",
      "polygon": [[80,40],[300,50],[340,240],[100,250]],
      "include_colors": [0,2,3,4], "base": "#b6dab3", "phase": "color", "ink_order": 0,
      "roles": {"ink": [0], "shadow": [3], "highlight": [4]}
    }
  ],
  "construction": [{"d": "M80 40 Q260 20 340 240", "stroke": "#8c9690", "width": 1.4}]
}
```

- `default` owns initially unassigned pixels; if omitted it becomes `unassigned`, an ordinary color region.
- `regions` apply in array order; later matches replace ownership. They partition the visible pixels.
- `polygon` has at least three x,y pairs; `polygons` may hold several. Shapes outside the image are clipped.
- `include_colors`/`exclude_colors` restrict a mask to palette indices.
- `id` is unique, semantic, lowercase. `base` is six-digit hex used for demo underpainting.
- `phase` is the fallback (`background`, `color`, `shadow`, `highlight`, `detail`, `ink`). Regional `roles` override global `roles`, which override `phase`. A color cannot hold two roles in one map.
- `ink_order` orders centerline strokes independently of final layering.
- `construction` is a few Bézier guides that fade during painting; omit if misleading.

Inspect coverage in `trace-report.json`; large unassigned foreground means an incomplete plan. Distinguish eyelid outlines from iris bodies and glints; dark clothes and foliage are not automatically ink.

## Parameters

- `prepare --colors 80` (range 1–256): fewer for icons, more for gradients.
- `--denoise 12`: bilateral filtering for palette assignment; `0` for crisp pixel art. Palette RGB is recomputed from original pixels.
- Repeat `--focus x,y,w,h` (original pixels) to weight important areas.
- `trace --epsilon .55`: contour tolerance; `.1–.25` for small icons or delicate lines.
- `--overlap 1.4`: same-color stroke width for opaque paint; ink uses `.55`. Transparent paths use narrower overlap and whole-path opacity.
- `draft-plan --work W --output P` proposes one region per palette color with simplified outer polygons from connected components (`--min-area 12`, `--epsilon 1.5`, `--max-regions 0`, `--ink-threshold 0`), so you rename regions and assign roles instead of drawing polygons from scratch.
- `trace --merge-colors N` (0–60, default 0) merges near-duplicate pigments within the same role per region to their pixel-count-weighted mean, reducing pale antialias bands without changing geometry or indices; the count is reported as `merged_color_indices` in `trace-report.json`.
- Small connected regions are not removed automatically, so large or noisy images produce large files. Discuss fidelity/size tradeoffs instead of silently dropping marks.

## Palette stability

Copy `palette.json`'s `fingerprint` into top-level `palette_fingerprint`; trace and plan review reject mismatches. Re-preparing requires rereading the atlas and rebuilding indices. Optional `source_sha256` binds a plan to one exact input.

To merge two colors after reviewing the atlas, run `vectorize.py palette-merge <work> --from <j> --into <i>` instead of re-preparing: slot `j` becomes an empty tombstone so all other indices stay valid, slot `i` becomes the pixel-weighted mean, a new fingerprint is derived, and the merge is recorded in `prepare-report.json`. Tombstoned slots cannot be merged again; splitting a color still requires re-preparing. Add `--plan path` (optionally `--plan-out`) to rewrite every `include_colors`/`exclude_colors`/`roles` reference from `<j>` to `<i>` and refresh `palette_fingerprint`, so the plan keeps working after a merge. Every report records the `toolkit_version` that wrote it.

Regions may declare metadata without a polygon; ordered `assignments` refine ownership:

```json
{"assignments": [
  {"region": "hanging-ivy", "polygon": [[0,0],[640,0],[640,960],[0,960]], "include_colors": [2,3], "only_from": ["backdrop"]},
  {"region": "right-hand", "polygon": [[220,810],[300,820],[310,865],[225,862]], "include_colors": [4,5]}
]}
```

`region` names an existing unique region; `only_from` constrains current ownership; assignment order changes ownership, not final stacking. Coordinates use the declared size.

`checkpoints` are semantic crop boxes `[x,y,width,height]` in plan coordinates with a unique ASCII `id` and `critical` (default true). CLI `--roi name:x,y,width,height` instead uses original pixels.

## Local contour and cleanup

Each region (including default) may set:

```json
{"trace": {"epsilon": 0.25, "overlap": 0.8},
 "cleanup": {"enabled": true, "max_area": 3, "max_rgb_distance": 10,
             "max_aspect": 2, "protect_roles": ["ink","detail","highlight"]}}
```

`epsilon`/`overlap` override CLI defaults for that region; optional `dark_epsilon`/`dark_threshold` apply a separate tolerance to pigments whose maximum RGB channel is below the threshold. Cleanup defaults off: it merges small compact opaque same-role islands within the RGB distance, preserving ownership/alpha and avoiding region edges. Bounds: area 1–64, RGB distance 0–60, aspect ratio 1–4. It is not a semantic denoiser; a real low-contrast dot can pass the same test.

## Replay and repeatability

Top-level `replay` sets `max_half_width`, `min_length` and `epsilon` in original pixels. `--pencil-mode connected` (default) or `legacy` affects only the separate line-art SVG, not final pigment contours. Connected replay avoids diagonal shortcuts, pairs near-opposite branches at junctions, fits cubic segments with an ink-support check and falls back to lines; short discarded fragments remain in the finished ink layer.

`prepare --sample-step N` makes palette sampling explicit. Preserve prepare/trace reports, plan hashes and library versions when comparing runs; a seed alone does not guarantee cross-version clustering equivalence.
