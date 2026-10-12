# img2svg

Turn a reference image into a **native, editable SVG**.

This repository is an **AI-agent skill**. The agent interprets your image and authors a per-image painting plan; the bundled scripts trace it into clean vector geometry, compare the result against the original and apply local repairs.

## What you get

- `illustration.svg` — the reconstructed artwork as SVG.
- Optional preparation data, SVG render comparisons and quality reports in the work directory.

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

The delivered SVG has no runtime dependencies.

## Usage

Two ways, same engine:

- **As a skill (best quality):** ask your agent in natural language, for example:

  > Reconstruct `reference.png` as an SVG and compare the important details against the reference.

  The agent identifies defining visual details, authors semantic regions and local compression budgets, compares rendered candidates, selects a result and repairs defects. Numerical scores do not make the visual decision. You do not run the scripts by hand.

- **As a plain CLI (no agent):** run the whole pipeline in one command:

  ```text
  python scripts/vectorize.py auto "reference.png" --output outputs --fidelity balanced
  ```

`--fidelity 0..100` (or `faithful`/`balanced`/`compact`, default `balanced`) is a single axis trading detail for file size, applied across `prepare`, `trace` and `auto`: `faithful` is the highest-detail preset, while `compact` merges shades and coarsens contours. All presets still quantize colours and approximate contours; `faithful` is not lossless. The CLI uses denoising by default. Near-colour merging respects each region's resolved pigment roles and excludes fully transparent pixels.

Agent-free `auto` additionally protects weak tonal transitions: it limits how far unrelated near-colours can merge and, when the original source is available and hash-verified, locally reconstructs sufficiently large, soft-edged colour patches. By default, low-contrast patches use fine-grained **literal-colour vector bands** to approximate a radial soft transition; this avoids renderer-dependent native SVG gradients (PyMuPDF can render native gradients black). It does not infer semantic shadows, blur the source, or change manually authored semantic plans. Use `--soft-tones-mode recolor` for the previous flat local-colour correction, or `--no-weak-tones` to disable both protection stages. The trace report records the correction and vector-gradient counts; the source image must remain accessible for automatic local corrections.

The fidelity presets now use 32 (Compact), 76 (Balanced), and 112 (Faithful) palette colours. `prepare --colors N` still overrides the profile when you need a particular colour budget. Higher fidelity generally preserves finer pigments at the cost of SVG size and processing time; more palette entries alone do not guarantee better visual fidelity.

## How it works

1. Inspect the reference and prepare a color palette.
2. The model authors an image-specific plan: regions, color roles and checkpoints.
3. Scripts trace the plan into native SVG geometry.
4. Renders are compared against the reference, and defects are repaired locally.

See `SKILL.md` for the full workflow, and `references/` for the plan schema and the output profile.

## Smaller files without blind global simplification

- Draft plans use exact colour-mask selectors instead of repeated contour polygons. `--geometry polygons` remains available for manual reshaping.
- Automatic tracing uses a shared region so nearby colours can actually merge. Agent plans can protect focal details with regional `trace.merge_colors: 0` and lower `epsilon`.
- SVG path commands are shortened without changing their quarter-pixel geometry.
- Compare candidates on one prepared image and plan:

```text
python scripts/visual_review.py candidates reference.png --work work/palette --plan work/plan.json --output work/candidates --max-bytes 500000
```

The output includes a contact sheet, critical crops, byte counts and a numerical
proposal. No candidate is automatically accepted; the multimodal agent inspects
the evidence and records its selection. If none meets the budget and error limits,
the proposal is null. See `SKILL.md` for the agent workflow.

## Reliability and tests

Palette merges validate the plan and both live colour slots before writing.
Stale plans are rejected. Palette metadata requires a matching plan fingerprint.
Palette merges and trace outputs (SVG and report) are staged
before committing, with rollback on ordinary write errors; this is not crash-safe
storage. Do not run concurrent writers against
the same work directory. If rollback fails, the error lists retained recovery backups.

The automatic route uses one shared colour region but does not infer semantic ink, shadow or
highlight roles. Agent-authored plans can provide more precise region and detail budgets.

Run the regression suites with separate, fresh scratch directories:

```text
python scripts/self_test.py --work work/self
python scripts/quality_test.py --work work/quality
python scripts/consolidate_test.py --work work/consolidate
python scripts/integrity_test.py
```

The integrity suite uses isolated temporary directories. If the system temporary
folder is restricted, set `TMP`/`TEMP` to a writable scratch directory.

## Documentation

- `SKILL.md` — agent workflow.
- `PROMPT.md` — vendor-neutral prompt for hosts without skill support.
- `references/` — plan schema, output profile, quality loop, visual access, manual SVG, consolidated vectors.

## Notes

Quantization and contour fitting are approximations, so always inspect the rendered result against the reference.

## License

MIT — see [LICENSE](LICENSE).
