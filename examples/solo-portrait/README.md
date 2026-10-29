# Solo portrait

A generic one-person scene. The scene file points at:

- `refs/location.png` — the place (reference image 1)
- `refs/person.png` — the person (reference image 2)

Those files are not in the repo. Use a photo of someone who consented, or a photo you have rights to, and keep it out of git (`refs/` is ignored).

There is no second person and no hand placed on someone else's arm. The end frame is a pose change from sitting up to sitting down. Identity, hair, and clothing stay the same. The mug stays in one hand.

One-person mode is new and has not been validated in a live paid run.

```bash
python -m scenelock run --scene examples/solo-portrait/scene.yaml --dry-run
```

Dry-run does not need the photo or an API key. A live run does. Generations go through Comfy Cloud partner nodes and need `COMFY_API_KEY`.
