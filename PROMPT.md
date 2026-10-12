# Portable agent request

Use with a host that can execute Python, edit files and deliver images to a multimodal model. Replace paths.

```text
Use the img2svg toolkit at "{toolkit directory}" to reconstruct "{reference image}" as a native SVG in "{output directory}".

Read SKILL.md as the workflow source of truth. Visually inspect the reference and critical crops; author an image-specific semantic plan with protected detail regions; compare size/quality candidates and make the final visual selection. Keep a better baseline during local repairs. Do not substitute the agent-free auto command for semantic planning or claim visual acceptance from metrics alone.

Deliver the selected SVG, with the file size and validation actually performed. If you cannot receive image content, state that visual acceptance remains unverified.
```
