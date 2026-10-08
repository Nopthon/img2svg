# Hand-authored geometry and replay metadata

Use SVG paths/primitives with literal paints and preserve the image's dimensions and ratio. `svg_compat.py --check` applies to manual and traced SVGs alike; no tracing step is required.

For `make_demo.py`, place semantic region groups directly inside `<g id="artwork">`, and all visible geometry inside tone groups:

```xml
<svg xmlns="http://www.w3.org/2000/svg" version="1.1"
     width="120" height="80" viewBox="0 0 120 80"
     preserveAspectRatio="xMidYMid meet">
  <g id="artwork">
    <g id="shape" data-region="shape" data-base="#89b97a" data-order="0">
      <g id="shape-color" data-tone="color" data-order="0">
        <path id="shape-body" d="M20 60 Q20 15 100 20 Q90 65 20 60 Z"
              fill="#89b97a" stroke="none"/>
      </g>
      <g id="shape-ink" data-tone="ink" data-order="0">
        <path id="shape-line" d="M20 60 Q60 40 100 20"
              fill="none" stroke="#435e42" stroke-width="2"/>
      </g>
    </g>
  </g>
</svg>
```

- Every `id` must be unique. `data-region` names the visible object; `data-base` is its literal six-digit base color.
- `data-tone` is one of `background`, `ink`, `color`, `shadow`, `highlight`, `detail`. `data-order` is 0–1, controlling onset within that stage; it does not change SVG stacking order.
- SVG document order controls final occlusion; keep geometry in its final stack even though replay reveals it by role.
- Tone groups are animation wrappers: do not encode intrinsic transparency in their `opacity`. Put intrinsic alpha on shapes or a nested non-tone group.
- Use only real reference shadows/highlights; empty stages are omitted.
- Optional `--line-art work/lines.svg` enables stroke-by-stroke replay. It needs the same `viewBox`, literal paints, unique IDs that do not collide with the main artwork, and open centerline paths with `fill="none"`. Final ink shapes stay in the main artwork.
- Optional `--plan work/plan.json` adds `coordinate_size` and `construction` guides per the painting-plan schema.

Then run `python scripts/make_demo.py outputs/illustration.svg --output outputs/index.html` with the optional line-art and plan arguments.
