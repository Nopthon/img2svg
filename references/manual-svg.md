# Hand-authored native SVG

Use standard SVG paths and primitives with literal paints and preserve the image's dimensions and aspect ratio. `svg_compat.py --check` applies to manually authored and traced SVGs alike; no tracing step is required.

Keep semantic regions as optional editable groups. They help identify which colours, details and contours belong to an object, without changing its final paint order.

```xml
<svg xmlns="http://www.w3.org/2000/svg" version="1.1"
     width="120" height="80" viewBox="0 0 120 80"
     preserveAspectRatio="xMidYMid meet">
  <g id="artwork">
    <g id="shape" data-region="shape" data-base="#89b97a">
      <path id="shape-body" d="M20 60 Q20 15 100 20 Q90 65 20 60 Z"
            fill="#89b97a" stroke="none"/>
      <path id="shape-line" d="M20 60 Q60 40 100 20"
            fill="none" stroke="#435e42" stroke-width="2"/>
    </g>
  </g>
</svg>
```

- Every `id` must be unique; `data-region` can identify the associated visual object.
- Optional `data-tone` values such as `background`, `color`, `ink`, `shadow`, `highlight` and `detail` may help inspect and edit grouped paint.
- SVG document order determines stacking and occlusion. Preserve the intended visible geometry and colour coverage.
- Apply opacity to the actual shape or a suitable local group; avoid unexpectedly multiplying overlapping alpha.
- Use shadows and highlights visible in the source, not imagined extra details.
- Prefer literal `#RRGGBB` paints and allowed native primitives. See [compatibility](compatibility.md).

Validate any hand-authored output:

```text
python scripts/svg_compat.py outputs/illustration.svg --check
```

Use `render_check.py` and `visual_review.py compare` when a raster reference is available. Numerical similarity is not a substitute for checking the original image at 1:1 and on important crops.
