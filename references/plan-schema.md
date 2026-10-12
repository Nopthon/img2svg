# Painting plan

Read the current `palette.json` before choosing indices. Coordinates refer to `coordinate_size` (same aspect ratio as the original); output uses original pixel dimensions.

```json
{
  "title": "Reference reconstruction",
  "coordinate_size": [640, 960],
  "checkpoints": [{"id": "key-detail", "box": [70,30,290,240], "critical": true}],
  "default": {"id": "background", "name": "Background", "base": "#fffaf3", "phase": "background"},
  "roles": {"ink": [0]},
  "regions": [
    {
      "id": "main-shape", "name": "Main shape",
      "polygon": [[80,40],[300,50],[340,240],[100,250]],
      "include_colors": [0,2,3,4], "base": "#b6dab3", "phase": "color",
      "roles": {"ink": [0], "shadow": [3], "highlight": [4]}
    }
  ]
}
```

- `default` owns initially unassigned pixels; if omitted it becomes `unassigned`, an ordinary color region.
- `regions` apply in array order; later matches replace ownership. They partition the visible pixels.
- `polygon` has at least three x,y pairs; `polygons` may hold several. Shapes outside the image are clipped.
- `include_colors`/`exclude_colors` restrict a mask to palette indices.
- `selector: "colors"` selects every pixel matching `include_colors` exactly, including thin marks and holes, without storing polygons. It requires nonempty `include_colors` and cannot be combined with polygons. Use polygons to separate objects sharing the same colours; metadata-only regions without selectors still await assignments.
- `id` is unique, semantic, lowercase. `base` is a six-digit hex region reference colour.
- `phase` is the fallback (`background`, `color`, `shadow`, `highlight`, `detail`, `ink`). Regional `roles` override global `roles`, which override `phase`. A color cannot hold two roles in one map.

Inspect coverage in `trace-report.json`; large unassigned foreground means an incomplete plan. Distinguish true line art from dark fills and reflective highlights; dark clothing and vegetation are not automatically ink.

## Parameters

- `prepare --colors N` (range 1–256) overrides the fidelity-derived colour count; fewer for icons, more for gradients.
- `--denoise 12`: bilateral filtering for palette assignment; `0` for crisp pixel art. Palette RGB is recomputed from original pixels.
- Repeat `--focus x,y,w,h` (original pixels) to weight important areas.
- `trace --epsilon .55`: contour tolerance; `.1–.25` for small icons or delicate lines.
- `--overlap`: same-colour edge-backing stroke width for opaque paint (default from fidelity, roughly `0.7–0.8`); ink uses `.55`. Excessive overlap biases adjacent colours darker because later pigment strokes cover earlier ones. Transparent paths use narrower overlap and whole-path opacity.
- `draft-plan --work W --output P` defaults to exact colour selectors: compact scaffolding, not semantic objects. Group or split these regions after viewing the image. `--geometry polygons` retains the optional simplified-polygon route; only that route uses `--min-area` and `--epsilon`. `--max-regions` and opt-in `--ink-threshold` still apply. Auto uses one shared colour region so near-colour merging can reduce the final geometry.
- `--fidelity 0..100` (or `faithful`/`balanced`/`compact`, default `balanced`) is the single detail-vs-size axis, interpolated linearly, accepted by `prepare`, `trace` and `auto`: it sets the colour count (Compact 32, Balanced 76, Faithful 112 by default) and label despeckling at prepare time, and `epsilon`/`overlap`/`merge-colors` at trace time. The resolved value is recorded as `fidelity` in the reports.
- `trace --merge-colors N` (0–60, default from fidelity: balanced=11) merges near colours within each region and resolved role. It changes trace masks and paint, but not the stored prepared data or plan indices. Regional `trace.merge_colors` overrides this, including `0` to protect fine detail. `merged_color_indices` counts eliminated indices across regions.
- Every merged group has a bounded full RGB diameter, preventing chains of individually close colours from swallowing distant hues. Opaque sources receive an opaque native canvas beneath their contours; transparent sources keep their alpha geometry.
- Agent-free single-region plans created by `auto` apply a second, fidelity-dependent merge diameter limit (8–12 RGB units) so merging unrelated light pigments cannot exaggerate faint shadows. When the original image remains available and hash-matches its preparation report, low-gradient local shading can be reconstructed from source colour statistics as nested native SVG paths with very small per-layer RGB differences (`--soft-tones-mode gradient`, the default). This simulates a soft colour transition while remaining compatible with PyMuPDF, which may render SVG gradient paints black. `--soft-tones-mode recolor` restores the previous solid local median-colour correction; `--no-weak-tones` disables both local correction and merge protection. Manually authored semantic plans are unchanged. Review the trace report's `weak_tones.gradient_components`, `recolored_components` and source status. Gradient fitting remains heuristic; it does not guarantee a continuous mathematical gradient or perfect reconstruction.
- Balanced preparation can merge small near-colour islands. Faithful disables that step, but still quantizes colours and approximates contours. Choose preparation before planning; trace candidates cannot restore already removed detail.

## Palette stability

Copy `palette.json`'s `fingerprint` into top-level `palette_fingerprint`; this is required whenever `palette.json` exists. Trace and plan review reject missing or mismatched fingerprints, as well as mismatched palette metadata. Re-preparing requires rereading the atlas and rebuilding indices. Optional `source_sha256` binds a plan to one exact input.

To merge two colors after reviewing the atlas, run `vectorize.py palette-merge <work> --from <j> --into <i>` instead of re-preparing: slot `j` becomes an empty tombstone so all other indices stay valid, slot `i` becomes the pixel-weighted mean, a new fingerprint is derived, and the merge is recorded in `prepare-report.json`. Tombstoned slots cannot be merged again; splitting a color still requires re-preparing. Add `--plan path` (optionally `--plan-out`) to rewrite every `include_colors`/`exclude_colors`/`roles` reference from `<j>` to `<i>` and refresh `palette_fingerprint`, so the plan keeps working after a merge. Every report records the `toolkit_version` that wrote it.

Regions may declare metadata without a polygon; ordered `assignments` refine ownership:

```json
{"assignments": [
  {"region": "overlay-top", "polygon": [[0,0],[640,0],[640,960],[0,960]], "include_colors": [2,3], "only_from": ["backdrop"]},
  {"region": "subject-detail", "polygon": [[220,810],[300,820],[310,865],[225,862]], "include_colors": [4,5]}
]}
```

`region` names an existing unique region; `only_from` constrains current ownership; assignment order changes ownership, not final stacking. Coordinates use the declared size.

`checkpoints` are semantic crop boxes `[x,y,width,height]` in plan coordinates with a unique ASCII `id` and `critical` (default true). CLI `--roi name:x,y,width,height` instead uses original pixels.

## Local contour and cleanup

Each region (including default) may set:

```json
{"trace": {"epsilon": 0.25, "overlap": 0.8, "merge_colors": 0},
 "cleanup": {"enabled": true, "max_area": 3, "max_rgb_distance": 10,
             "max_aspect": 2, "protect_roles": ["ink","detail","highlight"]}}
```

`epsilon`/`overlap`/`merge_colors` override CLI defaults for that region; optional `dark_epsilon`/`dark_threshold` apply a separate tolerance to pigments whose maximum RGB channel is below the threshold. Cleanup defaults off: it merges small compact opaque same-role islands within the RGB distance, preserving ownership/alpha and avoiding region edges. Bounds: area 1–64, RGB distance 0–60, aspect ratio 1–4. It is not a semantic denoiser; a real low-contrast dot can pass the same test.

## Repeatability

`prepare --sample-step N` makes palette sampling explicit. Preserve prepare/trace reports, plan hashes and library versions when comparing runs; a seed alone does not guarantee cross-version clustering equivalence.

## Visual intent and candidate selection

Optional `visual_intent` records the agent's observations and reasoning; it is metadata, not an automatic vision model:

```json
{"visual_intent": {
  "observations": ["A narrow pale mark separates two overlapping objects"],
  "protected_features": [{"region": "overlap-detail", "reason": "The separation establishes depth"}],
  "simplify": [{"region": "backdrop", "reason": "Low-contrast speckles are absent in the reference"}]
}}
```

Encode decisions in actual regions, roles, trace settings and checkpoint boxes; a prose label alone does not protect pixels. Candidate generation varies only trace defaults, preserving those explicit decisions. Candidate directories contain independent trace/comparison reports and review templates. `trace --report PATH` redirects the report without overwriting the baseline work report.
