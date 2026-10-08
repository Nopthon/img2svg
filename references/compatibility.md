# Native SVG output profile

Everything this toolkit writes is portable, static, native SVG. `validate()` runs before every write, so paint that cannot be represented literally fails instead of shipping.

- Root SVG namespace, positive `viewBox`, original dimensions, `preserveAspectRatio="xMidYMid meet"`.
- Visible paths, circles, rectangles, ellipses, lines, polygons, polylines and groups only. No raster, foreign content, external links, scripts or font-dependent text.
- Explicit `fill` and `stroke`: `#RRGGBB`, `none`, or a verified local `url(#gradient-id)`; numeric opacity. Local linear/radial gradients are the only allowed reusable `<defs>`; `clipPath`, `mask`, `filter`, `pattern` and `symbol` are rejected, not silently dropped.
- No CSS `var()`, `currentColor`, stylesheets, modern colors, eight-digit hex, `<use>` or symbol dependencies.
- Preserve fill rules, holes and transforms. Do not copy group opacity onto every child, or transparency composites twice.
- Gradients use literal `#RRGGBB` stops.

## Verify

```text
python scripts/svg_compat.py "outputs/illustration.svg" --check
python scripts/render_check.py "outputs/illustration.svg" --png "work/independent.png" --reference "reference.png" --report "work/render-report.json"
```

`svg_compat.py --check` confirms the profile without rewriting. Independent rendering needs optional `PyMuPDF` (`requirements-render.txt`); the report gives colored-pixel fraction and RGB error metrics, which locate differences but do not prove fidelity. Inspect full images and crops.

For HTML, test initial color without JavaScript, play/pause/restart, seeking to both ends, stage ownership, narrow-viewport proportions, and the downloaded SVG in the independent renderer. Keep the source ratio: fixing width and max-height independently can letterbox.

## Regression checks

After changing scripts run `python scripts/self_test.py --work "work/regression"` and `python scripts/quality_test.py --work "work/quality-regression"`. Both are synthetic and cannot replace visual inspection.
