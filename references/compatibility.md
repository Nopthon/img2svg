# Native SVG output profile

Everything this toolkit writes is portable, static, native SVG. `validate()` runs before every write, so paint that cannot be represented literally fails instead of shipping.

- Root SVG namespace, positive `viewBox`, original dimensions, `preserveAspectRatio="xMidYMid meet"`.
- Visible paths, circles, rectangles, ellipses, lines, polygons, polylines and groups only. No raster, foreign content, external links, scripts, event-handler attributes or font-dependent text. Unsupported elements, attribute namespaces and attributes are rejected; data-* and aria-* metadata are allowed.
- Explicit `fill` and `stroke`: `#RRGGBB`, `none`, or a verified local `url(#gradient-id)`; numeric opacity. Local linear/radial gradients are the only allowed reusable `<defs>`; `clipPath`, `mask`, `filter`, `pattern` and `symbol` are rejected, not silently dropped.
- No CSS `var()`, `currentColor`, stylesheets, modern colors, eight-digit hex, `<use>` or symbol dependencies.
- Preserve fill rules, holes and transforms. Do not copy group opacity onto every child, or transparency composites twice.
- Gradients use literal `#RRGGBB` stops.

## Verify

```text
python scripts/svg_compat.py "outputs/illustration.svg" --check
python scripts/render_check.py "outputs/illustration.svg" --png "work/independent.png" --reference "reference.png" --report "work/render-report.json"
```

`svg_compat.py --check` confirms the profile without rewriting. Independent rendering needs optional `PyMuPDF` (`requirements-render.txt`); the report gives colored-pixel fraction and RGB error metrics, which locate differences but do not prove fidelity. Add `--quantized-preview work/palette/quantized-preview.png` to distinguish signed RGB shifts arising *after* palette preparation (`rendered_vs_prepared_rgb_bias`) from colour errors already present in the prepared preview. The post-preparation measurement also includes optional trace-time pigment merging, not just geometric antialiasing. Inspect full images and crops.

## Regression checks

After changing scripts run `python scripts/self_test.py --work "work/regression"` and `python scripts/quality_test.py --work "work/quality-regression"`. Also run `python scripts/consolidate_test.py --work "work/consolidate-regression"` and `python scripts/integrity_test.py`. Use fresh work directories. These are synthetic tests and cannot replace visual inspection.
