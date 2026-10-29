# SceneLock

Turn reference photos into matching start and end frames (same characters, props and light), then animate between them, with no continuity drift.

SceneLock is an open-source rebuild of paid character-consistency and keyframe-to-video features. v0.1 is a four-stage pipeline on the [Comfy Developer Platform](https://cloud.comfy.org):

1. **Start frame.** Character and location references go through an image model (`GeminiImage2Node`, `gemini-3-pro-image-preview` by default).
2. **End frame.** An edit of the chosen start frame, so the table, props, background, and lighting stay locked and only the poses change.
3. **First/last-frame video.** `ByteDanceFirstLastFrameNode` (`seedance-1-5-pro-251215`) between those stills. The template locks the camera. The example scene is 8 seconds at 720p, 9:16.
4. **QA.** ffmpeg grabs frames. A contact sheet and 2x crops are written for a person to review. An optional vision-model reviewer can flag defects. It does not decide.

This is a work-in-progress entry for the [Open Source Higgsfield challenge](https://comfy.org/open-source-higgsfield/) (deadline Fri 2026-10-30 9am PT). You bring photos of people who consented, or photos you have rights to. The tool makes a start frame, edits that frame into an end frame with the scene locked, animates between those two frames, then writes QA notes for a person to sign off.

Generations go through Comfy Cloud partner nodes and need `COMFY_API_KEY`.

One live end-to-end Comfy Cloud run finished on 2026-10-10 using CC0 Wikimedia photos. It spent **98.80** credits: start frame 35.95, end-frame edit 35.28, Seedance 5s 720p video 27.57. That run used two people. One-person mode is new and has not been validated in a live paid run. Dashboard live buttons, 6–8s clips, and 2K stills were not part of that run.

```mermaid
flowchart LR
  refs[Reference photos] --> start[1. Start frame]
  start --> pickStart[Pick a start]
  pickStart --> endNode[2. End frame edit]
  endNode --> pickEnd[Pick an end]
  pickEnd --> video[3. First and last frame video]
  video --> qa[4. Frame grabs and QA notes]
  qa --> human[Human writes CONFIRMED or NOT FOUND]
```

## Setup

- Python 3.10+
- ffmpeg on `PATH` (QA frame grabs)
- A Comfy Cloud account
- An API key exported as `COMFY_API_KEY` ([platform.comfy.org](https://platform.comfy.org/profile/api-keys))

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Optional, for hand crops instead of centre crops: `pip install mediapipe`. QA still runs without it.

## Quickstart

Dry-run fills the workflows and does not need photos or a key:

```bash
python -m scenelock run --scene examples/backyard-burgers/scene.yaml --dry-run
python -m scenelock run --scene examples/solo-portrait/scene.yaml --dry-run
```

Copy one of those scenes, point `refs` at photos you have consent or rights to use, then:

```bash
export COMFY_API_KEY=your-key
python -m scenelock start --scene my-scene.yaml -n 4 --yes
python -m scenelock end --scene my-scene.yaml --start outputs/my-scene/start/start_s61001.png -n 2 --yes
python -m scenelock video --scene my-scene.yaml --start outputs/my-scene/start/start_s61001.png --end outputs/my-scene/end/end_s62011.png --yes
python -m scenelock qa --scene my-scene.yaml --video outputs/my-scene/video/video_s64001.mp4 --start outputs/my-scene/start/start_s61001.png --end outputs/my-scene/end/end_s62011.png
```

`run` does all four stages and pauses for a start pick and an end pick. `--auto-pick` keeps variation 0. `--yes` is required before any submit. The CLI prints an approximate credit total first.

```bash
python -m scenelock run --scene my-scene.yaml -n 4 --yes
```

Local dashboard (upload refs, edit the scene, preview prompts, dry-run or spend, pick from a grid):

```bash
python -m scenelock dashboard
```

Opens at `http://127.0.0.1:7860`. The spend checkbox is the dashboard's `--yes`. The key stays in the environment.

## Scene file

`examples/backyard-burgers/scene.yaml` is the two-person shape. `examples/solo-portrait/scene.yaml` is the one-person shape. You supply the photos. A scene is a location plus 1 or 2 people.

| Field | Role |
| --- | --- |
| `refs.location` | Location photo. Reference image 1 in the start prompt. |
| `characters` | 1 or 2 people. List order is reference image 2, then reference image 3 when a second person is present. `slot` is left or right. With two people, one sits left and one sits right. Optional `appearance` (for example "the man") is how the end prompt names who reaches. With two people, the first character is the one who places a hand; the second keeps their hands on the plate. With one person, the end frame is only a pose or position change, and identity, hair, and clothing stay the same unless `end_pose` explicitly changes them. |
| `held_object`, `held_hand` | The object stays in that one hand. The other hand gestures. |
| `table_lock` | Props that must not change. Injected into the start prompt, the end prompt, and the video prompt. |
| `start_pose`, `end_pose`, `motion_beat` | What the people do. Guardrails are added around this text. |
| `duration` | Seconds for the video node. 6–8 is the intended range. |
| `aspect_ratio` | Quote it. `"9:16"`. |
| `image_resolution`, `video_resolution` | Example uses `1K` and `720p`. The Cloud run this graph was taken from sent `2K` on the same image node. |
| `table_bbox` | Optional `[x, y, width, height]` in start-frame pixels. QA crops the table region before the SSIM check. |
| `seeds` | Integers per stage. The CLI extends the list when `--count` is larger. |

Quote `aspect_ratio`. Unquoted `9:16` is not a string in YAML.

## Architecture

ComfyUI API-format templates live in `workflows/`. The runner replaces `{{PLACEHOLDERS}}` and submits the graph.

`ImageBatch` centre-crops later images to the first image's size. Before the start-frame graph is submitted, character photos are letterboxed onto the location canvas so a face at the top of a tall portrait is not cut off. The fit pads; it does not crop.

The two-person start graph batches the location, then person A, then person B. The one-person graph, `workflows/start_frame_1p.json`, batches the location and then the one person, so `GeminiImage2Node` sees reference image 1 as the location and reference image 2 as the person. The end-frame edit and first/last-frame video graphs are unchanged. They already take images.

| Call | Use |
| --- | --- |
| `POST /api/upload/image` | Multipart upload. `LoadImage` receives the returned `name`. |
| `POST /api/prompt` | Body `{"prompt": workflow, "extra_data": {"api_key_comfy_org": KEY}}`. Header `X-API-Key`. |
| `GET /api/history_v2/{prompt_id}` | Poll until the job succeeds or fails. |
| `GET /api/view?filename&type&subfolder` | Download images and video. |

Base URL: `https://cloud.comfy.org`.

`workflows/reference/i2v_seedance_v1.json` is the older single-image image-to-video graph. The CLI does not run it. An edit for the end frame is what keeps the table still.

## Repo layout

```
workflows/     start_frame.json (2 people), start_frame_1p.json (1 person), end_frame_edit.json, flf_video.json
scenelock/     CLI and API client (`python -m scenelock`)
qa/            ffmpeg frame grabs, crops, QA_NOTES.md
app/           Gradio dashboard
examples/      backyard-burgers (2 people) and solo-portrait (1 person), no photos
tests/         pytest, no network
```

Generated files go to `outputs/`, which is gitignored. So are `refs/`, `*.safetensors`, and `.env`.

## Cost

Printed estimates use these approximations. They are not fetched from the account, they do not change with resolution, and partner pricing changes. Confirm the balance before `--yes`.

| Step | Approximate credits |
| --- | --- |
| Nano Banana Pro image (each start or end frame) | ~36 |
| Seedance 1.5 Pro, 720p, 5s, no audio | 27.57 |
| Seedance 1.5 Pro, 720p, 8s | ~44 |

The 5s figure is the charge from the 2026-10-10 run. The same run's 1K stills were 35.95 and 35.28, so the image line stays a flat ~36. 8s was not measured. 6s and 7s are a straight interpolation of 27.57 and 44 (~33.05 and ~38.52). Anything outside 5–8s is marked as extrapolated. A 4-start, 4-end, one 8s video dry-run prints **~332**.

Partner-node rates: [Comfy partner node pricing](https://docs.comfy.org/tutorials/partner-nodes/pricing).

## Lessons baked in

The prompt builders add these on every run. If your pose text fights them, the CLI prints a warning and still includes both.

- Do not start a character mid-action (for example mid-bite, or both hands on the object). Hands melt when the model has to let go. Keep the held object in one hand for the whole clip and gesture with the free hand.
- Make the end frame an edit of the chosen start frame, not a new generation. That is what keeps the table identical. The `table_lock` list is repeated, with the sentence "Do not add, remove, move, resize or relabel any object."
- With two people, keep each person's seat the same in the start prompt and the end prompt. The end prompt names who reaches and who is touched, by appearance and seat, and says not to swap them. The first character places their free hand on the second character's upper arm. The second character's hands stay on the plate. With one person, there is no second person and no hand-on-the-other's-arm rule. The end frame is a pose or position change (for example sitting up, then sitting down). Identity, hair, and clothing stay the same unless the end pose explicitly changes them.
- Object counts are exact. "Exactly one ketchup cup" means one, not two. Each burger stays in one hand.
- The video prompt says no new accessories or props, so a wristwatch cannot appear mid-clip.
- Static camera, in the prompt and as `camera_fixed: true` on the video node. Put the key gesture at about 70% of the clip so it lands before the end frame. Keep motion slow and small. Prefer closed-mouth smiles (open laughing mouths fuse teeth). Keep hands away from faces and necks.
- Pick an end pose that is physically reachable. A hand may rest on the upper arm or shoulder, not the neck.
- Video-review models hallucinate extra limbs from motion blur. QA writes flags into `QA_NOTES.md` with an empty **CONFIRMED / NOT FOUND** column. A human checks the full-res frame grabs and decides. The reviewer hook is off unless you pass `--reviewer package.module:ClassName`. A reviewer subclasses `qa.reviewer.VisionReviewer` and only returns flags.

## QA

`python -m scenelock qa` uses ffmpeg to save the first frame, the last frame, and frames at `--interval` seconds (default 1). It builds `contact_sheet.jpg`, writes 2x zoom crops (MediaPipe hands when that package imports, otherwise the centre of the frame), and compares the first and last video frames to the start and end stills. Before scoring, the video frame is resized onto the still and a vertical scale from 0.97 to 1.05 is searched, because Seedance 720p is a slightly different aspect and stretches the picture by about 2%. With `table_bbox` set, that comparison is the table crop on the aligned frames. SSIM under 0.8, or a mean absolute grayscale difference above 12, is labeled possible prop drift. Flat areas can keep a high SSIM while the color changes, which is why both numbers are there. They are heuristics, not a measured error rate.

## Likeness and consent

Only use photos of people who consented, or photos you have rights to. The repo ships no private likeness models and no personal photos. The example scenes have no alcohol and no branded products. Do not put either into examples you commit.

## Tests

```bash
pytest
```

Template filling, scene parsing, prompt text, the cost gate, dry-run, and QA all run locally. Nothing in the tests calls Comfy Cloud.

## What that live run confirmed, and what is still open

Confirmed on 2026-10-10 (CC0 Wikimedia photos, 98.80 credits, three submits, no retries):

- `POST /api/upload/image` returns a content-addressed name that `LoadImage` accepts. The downloaded file matched the uploaded bytes.
- `GeminiImage2Node` at `1K` produced the start frame (35.95 credits) and the end-frame edit (35.28).
- `SaveVideo` output was listed in history and downloaded. The 5s 720p clip, audio off, cost 27.57 credits.
- `GET /api/history_v2/{prompt_id}` returns 404 while the job is queued or running. The client treats that 404 as still running. The same prompt id is billed even if a later poll fails, and the ledger records it at submit time.

Still open:

- One-person start frames. The graph and prompts are covered by dry-run tests. One-person mode is new and has not been validated in a live paid run.
- Dashboard buttons that submit, the variation grid, and playback
- 6–8s clips and `2K` stills
- More than one seed in a single stage

`/api/history_v2/{prompt_id}` is the ComfyUI-compatible poll used here. Cloud docs also list `/api/jobs/{job_id}` for the same id.

## License

MIT. See [LICENSE](LICENSE).
