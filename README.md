# SceneLock

Turn reference photos into matching start and end frames (same characters, props and light), then animate between them, with no continuity drift.

## What it is

Open-source rebuild of the paid character-consistency and keyframe-to-video features. The design is a 4-stage pipeline:

1. **Start frame** from character and location reference images via an image model (for example Nano Banana Pro / Gemini image through Comfy Router).
2. **End frame** produced as an edit of the chosen start frame, so the table, props, background, and lighting stay locked and only poses change.
3. **First/last-frame video** between those frames (for example the Seedance 1.5 Pro first/last-frame node, 6–8s, static camera).
4. **Automated QA**, where a video-review model flags anatomy and continuity defects (melted hands, extra fingers, prop changes). Each flag is verified against full-resolution frame grabs before a human signs off.

Workflows, the CLI, and the QA script are still to be written. This repository does not run the pipeline yet, and it publishes no benchmarks.

## Built on the Comfy Developer Platform

SceneLock is built on the Comfy Developer Platform:

- **Comfy API** — [cloud.comfy.org](https://cloud.comfy.org) REST: `/api/upload/image`, `/api/prompt`, `/api/history_v2/{id}`
- **Comfy Router** for partner models
- **ComfyUI workflow JSON**

## Status

Work in progress, challenge entry. Workflows and scripts land here before 10/19.

Entry for the [Comfy Dev Platform Challenge](https://blog.comfy.org/p/open-call-comfy-dev-platform-challenge) (deadline 2026-10-19 9am PT).

## Planned repo layout

These folders are part of the plan. They are not in the tree yet:

- `workflows/` — ComfyUI API-format JSON per stage
- `scenelock/` — Python CLI that uploads refs, submits each stage, polls, and downloads
- `qa/` — flag-and-verify script with ffmpeg frame grabs
- `examples/`

## Setup

Intended setup, once the project files exist:

1. Python 3.10+
2. ffmpeg
3. A Comfy Cloud account, with an API key exported as `COMFY_API_KEY`
4. Install dependencies with `pip install -r requirements.txt` (`requirements.txt` is coming)
5. Run command (coming soon):

```bash
python -m scenelock run --refs refs/ --prompt prompt.txt
```

## Likeness & safety

Only use reference photos of people who have consented. The repo ships no private likeness models or personal photos. Examples include no alcohol and no unlicensed IP.

## License

MIT. See [LICENSE](LICENSE).
