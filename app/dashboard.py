"""Minimal local dashboard: edit a scene, dry-run or submit, pick variations."""

from __future__ import annotations

import shutil
from pathlib import Path

import gradio as gr

from scenelock.client import ComfyError
from scenelock.cost import SpendRequired, estimate_run
from scenelock.pipeline import ledger_text, preview_text, run_end, run_start, run_video
from scenelock.scene import SceneError, load_scene, scene_from_mapping
from scenelock.templates import TemplateError

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "backyard-burgers" / "scene.yaml"
WORK = ROOT / "outputs" / "dashboard"


def main(host: str = "127.0.0.1", port: int = 7860) -> None:
    demo = build_demo()
    demo.launch(server_name=host, server_port=port, share=False)


def build_demo() -> gr.Blocks:
    with gr.Blocks(title="SceneLock") as demo:
        gr.Markdown(
            "# SceneLock\n\n"
            "Turn reference photos into a start frame and an edited end frame, then a short clip between them.\n\n"
            "Use photos of people who have consented. Dry-run prints the workflow and does not spend credits. "
            "A live stage runs only when **Spend Comfy credits** is checked, and it reads `COMFY_API_KEY` from the environment."
        )
        with gr.Row():
            location = gr.File(label="Location reference", file_types=["image"])
            person_a_file = gr.File(label="Person A reference", file_types=["image"])
            person_b_file = gr.File(label="Person B reference", file_types=["image"])
        with gr.Row():
            title = gr.Textbox(label="Title", value="Backyard burgers")
            setting = gr.Textbox(label="Setting", value="a wooden backyard table in warm afternoon light")
        with gr.Row():
            name_a = gr.Textbox(label="Person A name", value="Person A")
            slot_a = gr.Dropdown(["left", "right"], value="left", label="Person A seat")
            object_a = gr.Textbox(label="Person A held object", value="a burger")
            hand_a = gr.Dropdown(["left", "right"], value="left", label="Person A held hand")
        with gr.Row():
            name_b = gr.Textbox(label="Person B name", value="Person B")
            slot_b = gr.Dropdown(["left", "right"], value="right", label="Person B seat")
            object_b = gr.Textbox(label="Person B held object", value="a burger")
            hand_b = gr.Dropdown(["left", "right"], value="left", label="Person B held hand")
        table_lock = gr.Textbox(label="Table lock (one prop per line)", lines=4)
        start_pose = gr.Textbox(label="Start pose", lines=3)
        end_pose = gr.Textbox(label="End pose", lines=3)
        motion_beat = gr.Textbox(label="Motion beat", lines=3)
        with gr.Row():
            duration = gr.Slider(4, 12, value=8, step=1, label="Duration (seconds)")
            count = gr.Slider(1, 8, value=4, step=1, label="Variations")
            aspect = gr.Textbox(label="Aspect ratio", value="9:16")
            image_resolution = gr.Textbox(label="Image resolution", value="1K")
            video_resolution = gr.Textbox(label="Video resolution", value="720p")
        agree = gr.Checkbox(label="Spend Comfy credits (required for a live run, same as --yes)")
        with gr.Row():
            load_btn = gr.Button("Load example scene")
            preview_btn = gr.Button("Preview prompts and cost")
            dry_btn = gr.Button("Dry-run start")
        with gr.Row():
            start_btn = gr.Button("Run start")
            end_btn = gr.Button("Run end from picked start")
            video_btn = gr.Button("Run video")
            qa_btn = gr.Button("Run QA")
        with gr.Row():
            start_index = gr.Number(label="Start variation index", value=0, precision=0)
            end_index = gr.Number(label="End variation index", value=0, precision=0)
        log = gr.Textbox(label="Log", lines=18)
        gallery = gr.Gallery(label="Variations", columns=4, height=320)
        with gr.Row():
            video = gr.Video(label="Video")
            sheet = gr.Image(label="QA contact sheet")
        cost = gr.Textbox(label="Cost so far")
        start_files = gr.State([])
        end_files = gr.State([])
        video_path = gr.State(None)

        field_inputs = [
            title, setting, name_a, slot_a, object_a, hand_a, name_b, slot_b, object_b, hand_b,
            table_lock, start_pose, end_pose, motion_beat, duration, aspect, image_resolution,
            video_resolution, count, location, person_a_file, person_b_file,
        ]

        load_btn.click(_load_example, outputs=[title, setting, name_a, slot_a, object_a, hand_a, name_b, slot_b, object_b, hand_b, table_lock, start_pose, end_pose, motion_beat, duration, aspect, image_resolution, video_resolution])
        preview_btn.click(_preview, inputs=field_inputs, outputs=[log, cost])
        dry_btn.click(_dry_start, inputs=field_inputs, outputs=[log, gallery, cost])
        start_btn.click(
            _run_start,
            inputs=field_inputs + [agree],
            outputs=[log, gallery, cost, start_files],
        )
        end_btn.click(
            _run_end,
            inputs=field_inputs + [agree, start_files, start_index],
            outputs=[log, gallery, cost, end_files],
        )
        video_btn.click(
            _run_video,
            inputs=field_inputs + [agree, start_files, end_files, start_index, end_index],
            outputs=[log, video, cost, video_path],
        )
        qa_btn.click(
            _run_qa,
            inputs=[title, setting, name_a, slot_a, object_a, hand_a, name_b, slot_b, object_b, hand_b, table_lock, start_pose, end_pose, motion_beat, duration, aspect, image_resolution, video_resolution, count, location, person_a_file, person_b_file, start_files, end_files, video_path, start_index, end_index],
            outputs=[log, sheet, cost],
        )
    return demo


def _load_example():
    scene = load_scene(EXAMPLE)
    return (
        scene.title,
        scene.setting,
        scene.characters[0].name,
        scene.characters[0].slot,
        scene.characters[0].held_object,
        scene.characters[0].held_hand,
        scene.characters[1].name,
        scene.characters[1].slot,
        scene.characters[1].held_object,
        scene.characters[1].held_hand,
        "\n".join(scene.table_lock),
        scene.start_pose,
        scene.end_pose,
        scene.motion_beat,
        scene.duration,
        scene.aspect_ratio,
        scene.image_resolution,
        scene.video_resolution,
    )


def _preview(*values):
    try:
        scene, count = _scene_from_form(*values)
    except (SceneError, TemplateError) as exc:
        return f"error: {exc}", ""
    estimate = estimate_run(count, count, scene.duration)
    return preview_text(scene) + "\n\n" + estimate.format(), estimate.format()


def _dry_start(*values):
    try:
        scene, count = _scene_from_form(*values)
        result = run_start(scene, count, True, False, WORK)
    except (SceneError, TemplateError, ComfyError) as exc:
        return f"error: {exc}", [], ""
    return result.render(), [], ledger_text(WORK)


def _run_start(*values):
    *form, agree = values
    if not agree:
        return "Check Spend Comfy credits before a live run. Nothing was submitted.", [], ledger_text(WORK), []
    try:
        scene, count = _scene_from_form(*form)
        result = run_start(scene, count, False, True, WORK)
    except SpendRequired as exc:
        return exc.estimate.format() + "\nNothing was submitted.", [], ledger_text(WORK), []
    except (SceneError, TemplateError, ComfyError) as exc:
        return f"error: {exc}", [], ledger_text(WORK), []
    files = [str(path) for path in result.files]
    return result.render(), files, ledger_text(WORK), files


def _run_end(*values):
    *form, agree, files, index = values
    if not agree:
        return "Check Spend Comfy credits before a live run. Nothing was submitted.", [], ledger_text(WORK), []
    chosen = _choose(files, index, "start")
    if isinstance(chosen, str) and chosen.startswith("error:"):
        return chosen, [], ledger_text(WORK), []
    try:
        scene, count = _scene_from_form(*form)
        result = run_end(scene, chosen, count, False, True, WORK)
    except (SceneError, TemplateError, ComfyError, SpendRequired) as exc:
        text = exc.estimate.format() if isinstance(exc, SpendRequired) else f"error: {exc}"
        return text, [], ledger_text(WORK), []
    saved = [str(path) for path in result.files]
    return result.render(), saved, ledger_text(WORK), saved


def _run_video(*values):
    *form, agree, starts, ends, start_index, end_index = values
    if not agree:
        return "Check Spend Comfy credits before a live run. Nothing was submitted.", None, ledger_text(WORK), None
    start = _choose(starts, start_index, "start")
    end = _choose(ends, end_index, "end")
    for chosen in (start, end):
        if isinstance(chosen, str) and chosen.startswith("error:"):
            return chosen, None, ledger_text(WORK), None
    try:
        scene, _count = _scene_from_form(*form)
        result = run_video(scene, start, end, False, True, WORK)
    except (SceneError, TemplateError, ComfyError, SpendRequired) as exc:
        text = exc.estimate.format() if isinstance(exc, SpendRequired) else f"error: {exc}"
        return text, None, ledger_text(WORK), None
    path = str(result.files[0]) if result.files else None
    return result.render(), path, ledger_text(WORK), path


def _run_qa(*values):
    *form, starts, ends, video_file, start_index, end_index = values
    start = _choose(starts, start_index, "start")
    end = _choose(ends, end_index, "end")
    for chosen in (start, end):
        if isinstance(chosen, str) and chosen.startswith("error:"):
            return chosen, None, ledger_text(WORK)
    if not video_file:
        return "Run video first. QA needs a downloaded clip.", None, ledger_text(WORK)
    try:
        from qa.check import run_qa

        scene, _count = _scene_from_form(*form)
        report = run_qa(scene, video_file, start, end, WORK / "qa")
    except (SceneError, TemplateError, ComfyError, FileNotFoundError, RuntimeError) as exc:
        return f"error: {exc}", None, ledger_text(WORK)
    notes = report.notes_path.read_text(encoding="utf-8")
    return notes, str(report.contact_sheet) if report.contact_sheet else None, ledger_text(WORK)


def _choose(files, index, label):
    if not files:
        return f"error: No {label} variations yet. Run that stage first."
    try:
        return files[int(index)]
    except (TypeError, ValueError, IndexError):
        return f"error: Pick a {label} index from 0 to {len(files) - 1}."


def _scene_from_form(
    title, setting, name_a, slot_a, object_a, hand_a, name_b, slot_b, object_b, hand_b,
    table_lock, start_pose, end_pose, motion_beat, duration, aspect, image_resolution,
    video_resolution, count, location, person_a_file, person_b_file,
):
    WORK.mkdir(parents=True, exist_ok=True)
    data = {
        "title": title,
        "setting": setting,
        "aspect_ratio": aspect,
        "image_resolution": image_resolution,
        "video_resolution": video_resolution,
        "duration": int(duration),
        "refs": {"location": _materialize(location, WORK / "refs" / "location.png")},
        "characters": [
            {
                "name": name_a,
                "image": _materialize(person_a_file, WORK / "refs" / "person_a.png"),
                "slot": slot_a,
                "held_object": object_a,
                "held_hand": hand_a,
            },
            {
                "name": name_b,
                "image": _materialize(person_b_file, WORK / "refs" / "person_b.png"),
                "slot": slot_b,
                "held_object": object_b,
                "held_hand": hand_b,
            },
        ],
        "table_lock": table_lock or "",
        "start_pose": start_pose,
        "end_pose": end_pose,
        "motion_beat": motion_beat,
    }
    scene = scene_from_mapping(data, WORK)
    return scene, max(1, int(count))


def _materialize(upload, dest: Path) -> str:
    source = _as_path(upload)
    if not source:
        return str(dest)
    src = Path(source)
    target = dest.with_suffix(src.suffix.lower() or dest.suffix)
    if src.resolve() == target.resolve():
        return str(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, target)
    return str(target)


def _as_path(value):
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return _as_path(value[0]) if value else None
    if isinstance(value, str):
        return value
    name = getattr(value, "name", None)
    return str(name) if name else None
