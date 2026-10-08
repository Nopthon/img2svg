# img2svg

Turn a reference image into an **SVG**, with an optional offline drawing-replay demo.

This repository is an **AI-agent skill**. The agent interprets your image and authors a per-image painting plan; the bundled scripts trace it into clean vector geometry, compare the result against the original and apply local repairs.

## What you get

- `illustration.svg` — the reconstructed artwork as SVG.
- `index.html` — optional single-file, offline replay: sketch → line art → base color → shadow → highlight → finish, with play, pause, seek and speed control.
- `drawing-demo.zip` — the above, packaged.

## Install

Put this folder where your agent discovers skills, named after the skill:

```text
~/.config/opencode/skill/img2svg/          # OpenCode, global
```

Or register the directory through `skills.paths` in `opencode.json`. Any host that supports skills can load it; for hosts without skill discovery, use `PROMPT.md` with the same scripts.

### Requirements

- Python 3
- `pip install -r requirements.txt` (numpy, opencv-python-headless, Pillow)
- Optional independent renderer: `pip install -r requirements-render.txt` (PyMuPDF)
- Optional reproducible environment: `pip install -r requirements.lock` (exact versions the regression tests were validated against)

The delivered SVG and HTML have no runtime dependencies.

## Usage

Two ways, same engine:

- **As a skill (best quality):** ask your agent in natural language, for example:

  > Reconstruct `reference.png` as an SVG (and also give me the drawing-replay demo).

  The agent inspects the image, prepares a color palette, authors the plan, traces, compares renders, repairs defects, and returns the files. You do not run the scripts by hand.

- **As a plain CLI (no agent):** run the whole pipeline in one command:

  ```text
  python scripts/vectorize.py auto "reference.png" --output outputs --fidelity balanced --demo
  ```

`--fidelity 0..100` (or `faithful`/`balanced`/`compact`, default `balanced`) is a single axis trading detail for file size, applied across `prepare`, `trace` and `auto`: `faithful` keeps every contour, `compact` merges shades and coarsens contours.

## How it works

1. Inspect the reference and prepare a color palette.
2. The model authors an image-specific plan: regions, color roles, ink order and checkpoints.
3. Scripts trace the plan into SVG geometry plus a separate line-art layer.
4. Renders are compared against the reference, and defects are repaired locally.
5. Optionally, a self-contained replay HTML is produced.

See `SKILL.md` for the full workflow, and `references/` for the plan schema and the output profile.

## Documentation

- `SKILL.md` — agent workflow.
- `PROMPT.md` — vendor-neutral prompt for hosts without skill support.
- `references/` — plan schema, output profile, quality loop, visual access, manual SVG, consolidated vectors.

## Notes

Quantization and contour fitting are approximations, so always inspect the rendered result against the reference.

## License

MIT — see [LICENSE](LICENSE).
