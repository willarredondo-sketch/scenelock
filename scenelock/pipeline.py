"""Build workflows and, when asked, submit them to Comfy Cloud."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from scenelock.client import ComfyClient, ComfyError
from scenelock.cost import CostEstimate, SpendRequired, estimate_run, estimate_stage
from scenelock.prompts import build_end_prompt, build_start_prompt, build_video_prompt
from scenelock.scene import Scene, output_dir_for, seeds_for
from scenelock.templates import fill_workflow, load_template


@dataclass
class StageResult:
    stage: str
    submitted: bool
    estimate: CostEstimate
    workflows: list[dict]
    files: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    prompt_ids: list[str] = field(default_factory=list)
    seeds: list[int] = field(default_factory=list)

    def render(self) -> str:
        lines = [self.estimate.format(), ""]
        for warning in self.warnings:
            lines.append(f"warning: {warning}")
        if self.warnings:
            lines.append("")
        if self.submitted:
            lines.append(f"Submitted {self.stage}.")
            for prompt_id, path in zip(self.prompt_ids, self.files):
                lines.append(f"  {prompt_id} -> {path}")
        else:
            lines.append(f"Dry-run {self.stage}. No API calls. Image fields are local paths.")
            for seed, workflow in zip(self.seeds, self.workflows):
                lines.append(f"--- {self.stage} seed {seed} ---")
                lines.append(json.dumps(workflow, indent=2))
        return "\n".join(lines)


@dataclass
class PipelineResult:
    stages: list[StageResult]
    qa_notes: Path | None = None
    message: str = ""
    header: str = ""

    def render(self) -> str:
        parts = []
        if self.header:
            parts.append(self.header)
        parts.extend(stage.render() for stage in self.stages)
        if self.message:
            parts.append(self.message)
        if self.qa_notes:
            parts.append(f"QA notes: {self.qa_notes}")
        return "\n\n".join(parts)


def run_start(
    scene: Scene,
    count: int,
    dry_run: bool,
    yes: bool,
    output: str | Path | None = None,
    client: ComfyClient | None = None,
) -> StageResult:
    seeds = seeds_for(scene, "start", count)
    workflows = []
    warnings: list[str] = list(scene.warnings)
    for seed in seeds:
        workflow, prompt_warnings = build_start_workflow(scene, seed)
        workflows.append(workflow)
        warnings.extend(prompt_warnings)
    estimate = estimate_stage("start", len(seeds), scene.duration)
    return _finish(
        scene,
        "start",
        seeds,
        workflows,
        warnings,
        estimate,
        dry_run,
        yes,
        output,
        client,
        image_paths=[scene.location_image, scene.characters[0].image, scene.characters[1].image],
    )


def run_end(
    scene: Scene,
    start_image: str | Path,
    count: int,
    dry_run: bool,
    yes: bool,
    output: str | Path | None = None,
    client: ComfyClient | None = None,
) -> StageResult:
    seeds = seeds_for(scene, "end", count)
    workflows = []
    warnings: list[str] = list(scene.warnings)
    start_path = Path(start_image)
    for seed in seeds:
        workflow, prompt_warnings = build_end_workflow(scene, seed, start_path)
        workflows.append(workflow)
        warnings.extend(prompt_warnings)
    estimate = estimate_stage("end", len(seeds), scene.duration)
    return _finish(
        scene,
        "end",
        seeds,
        workflows,
        warnings,
        estimate,
        dry_run,
        yes,
        output,
        client,
        image_paths=[start_path],
    )


def run_video(
    scene: Scene,
    start_image: str | Path,
    end_image: str | Path,
    dry_run: bool,
    yes: bool,
    output: str | Path | None = None,
    client: ComfyClient | None = None,
) -> StageResult:
    seeds = seeds_for(scene, "video", 1)
    warnings: list[str] = list(scene.warnings)
    workflow, prompt_warnings = build_video_workflow(scene, seeds[0], Path(start_image), Path(end_image))
    warnings.extend(prompt_warnings)
    estimate = estimate_stage("video", 1, scene.duration)
    return _finish(
        scene,
        "video",
        seeds,
        [workflow],
        warnings,
        estimate,
        dry_run,
        yes,
        output,
        client,
        image_paths=[Path(start_image), Path(end_image)],
    )


def run_pipeline(
    scene: Scene,
    count: int,
    dry_run: bool,
    yes: bool,
    auto_pick: bool,
    output: str | Path | None = None,
    client: ComfyClient | None = None,
    picker=None,
    reviewer: str | None = None,
) -> PipelineResult:
    """Run start, end, and video. A live run pauses for a start pick and an end pick."""
    estimate = estimate_run(count, count, scene.duration)
    if dry_run:
        start = run_start(scene, count, True, False, output, client)
        placeholder_start = "dry-run/chosen-start.png"
        placeholder_end = "dry-run/chosen-end.png"
        end = run_end(scene, placeholder_start, count, True, False, output, client)
        video = run_video(scene, placeholder_start, placeholder_end, True, False, output, client)
        # The per-stage estimates already printed inside each result. Replace the
        # first block's estimate with the full-run total by prepending it here.
        header = "Full-run estimate:\n" + estimate.format()
        message = (
            "Dry-run only. No API calls. A live run pauses to pick a start frame "
            "and an end frame unless you pass --auto-pick. QA runs after a video exists."
        )
        return PipelineResult([start, end, video], message=message, header=header)

    if not yes:
        raise SpendRequired(estimate)
    _require_key(client)
    missing = [
        str(path)
        for path in (scene.location_image, scene.characters[0].image, scene.characters[1].image)
        if not path.is_file()
    ]
    if missing:
        raise ComfyError("Missing image files:\n" + "\n".join(missing))
    print(estimate.format(), flush=True)
    print("Submitting the full run.", flush=True)

    destination = output_dir_for(scene, output)
    start = run_start(scene, count, False, True, destination, client)
    chosen_start = _pick(start.files, auto_pick, "start", picker)
    end = run_end(scene, chosen_start, count, False, True, destination, client)
    chosen_end = _pick(end.files, auto_pick, "end", picker)
    video = run_video(scene, chosen_start, chosen_end, False, True, destination, client)
    qa_notes = None
    message = ""
    if video.files:
        try:
            from qa.check import run_qa

            report = run_qa(
                scene,
                video.files[0],
                chosen_start,
                chosen_end,
                destination / "qa",
                reviewer_path=reviewer,
            )
            qa_notes = report.notes_path
        except Exception as exc:  # noqa: BLE001 - keep the downloaded video if QA fails
            message = f"Video downloaded. QA failed: {exc}"
    return PipelineResult([start, end, video], qa_notes=qa_notes, message=message)


def build_start_workflow(scene: Scene, seed: int) -> tuple[dict, list[str]]:
    prompt, warnings = build_start_prompt(scene)
    workflow = fill_workflow(
        load_template("start_frame.json"),
        {
            "LOCATION_IMAGE": str(scene.location_image),
            "PERSON_A_IMAGE": str(scene.characters[0].image),
            "PERSON_B_IMAGE": str(scene.characters[1].image),
            "START_PROMPT": prompt,
            "IMAGE_MODEL": scene.image_model,
            "SEED": seed,
            "ASPECT_RATIO": scene.aspect_ratio,
            "IMAGE_RESOLUTION": scene.image_resolution,
            "FILENAME_PREFIX": f"scenelock/start_s{seed}",
        },
    )
    return workflow, warnings


def build_end_workflow(scene: Scene, seed: int, start_image: Path) -> tuple[dict, list[str]]:
    prompt, warnings = build_end_prompt(scene)
    workflow = fill_workflow(
        load_template("end_frame_edit.json"),
        {
            "START_FRAME_IMAGE": str(start_image),
            "END_PROMPT": prompt,
            "IMAGE_MODEL": scene.image_model,
            "SEED": seed,
            "ASPECT_RATIO": scene.aspect_ratio,
            "IMAGE_RESOLUTION": scene.image_resolution,
            "FILENAME_PREFIX": f"scenelock/end_s{seed}",
        },
    )
    return workflow, warnings


def build_video_workflow(
    scene: Scene, seed: int, start_image: Path, end_image: Path
) -> tuple[dict, list[str]]:
    prompt, warnings = build_video_prompt(scene)
    workflow = fill_workflow(
        load_template("flf_video.json"),
        {
            "START_FRAME_IMAGE": str(start_image),
            "END_FRAME_IMAGE": str(end_image),
            "VIDEO_PROMPT": prompt,
            "VIDEO_MODEL": scene.video_model,
            "VIDEO_RESOLUTION": scene.video_resolution,
            "ASPECT_RATIO": scene.aspect_ratio,
            "DURATION": scene.duration,
            "SEED": seed,
            "FILENAME_PREFIX": f"scenelock/video_s{seed}",
        },
    )
    return workflow, warnings


def preview_text(scene: Scene) -> str:
    start, start_warnings = build_start_prompt(scene)
    end, end_warnings = build_end_prompt(scene)
    video, video_warnings = build_video_prompt(scene)
    blocks = []
    for label, text, warnings in (
        ("Start", start, start_warnings),
        ("End", end, end_warnings),
        ("Video", video, video_warnings),
    ):
        blocks.append(f"## {label}\n{text}")
        for warning in warnings:
            blocks.append(f"warning: {warning}")
    for warning in scene.warnings:
        blocks.append(f"warning: {warning}")
    return "\n\n".join(blocks)


def _finish(
    scene: Scene,
    stage: str,
    seeds: list[int],
    workflows: list[dict],
    warnings: list[str],
    estimate: CostEstimate,
    dry_run: bool,
    yes: bool,
    output: str | Path | None,
    client: ComfyClient | None,
    image_paths: list[Path],
) -> StageResult:
    destination = output_dir_for(scene, output)
    # One warning line per distinct message. Repeated seeds share the same pose warning.
    unique_warnings = list(dict.fromkeys(warnings))
    if dry_run:
        _write_workflows(destination / "dry-run", stage, seeds, workflows)
        return StageResult(stage, False, estimate, workflows, [], unique_warnings, [], seeds)
    if not yes:
        raise SpendRequired(estimate)
    missing = [str(path) for path in image_paths if not Path(path).is_file()]
    if missing:
        raise ComfyError("Missing image files:\n" + "\n".join(missing))
    _require_key(client)
    print(estimate.format(), flush=True)
    print(f"Submitting {stage}.", flush=True)
    api = client or ComfyClient.from_env()
    files, prompt_ids, submitted = _submit_all(api, destination, stage, seeds, workflows)
    _record(destination, stage, seeds, estimate, prompt_ids)
    return StageResult(stage, True, estimate, submitted, files, unique_warnings, prompt_ids, seeds)


def _submit_all(client: ComfyClient, destination: Path, stage: str, seeds: list[int], workflows: list[dict]):
    cache: dict[str, str] = {}
    files: list[Path] = []
    prompt_ids: list[str] = []
    submitted: list[dict] = []
    for seed, workflow in zip(seeds, workflows):
        prepared = _upload_load_images(client, workflow, cache)
        prompt_id = client.submit(prepared)
        prompt_ids.append(prompt_id)
        submitted.append(prepared)
        print(f"submitted {stage} seed {seed} prompt_id {prompt_id}", file=sys.stderr)
        remote_files = client.wait_for_files(prompt_id)
        saved = _download_outputs(client, remote_files, destination / stage, stage, seed)
        files.extend(saved)
    _write_workflows(destination / "submitted", stage, seeds, submitted)
    return files, prompt_ids, submitted


def _upload_load_images(client: ComfyClient, workflow: dict, cache: dict[str, str]) -> dict:
    prepared = json.loads(json.dumps(workflow))
    for node in prepared.values():
        inputs = node.get("inputs") or {}
        image = inputs.get("image")
        if not isinstance(image, str):
            continue
        if image not in cache:
            cache[image] = client.upload_image(image)
        inputs["image"] = cache[image]
    return prepared


def _download_outputs(client: ComfyClient, remote_files: list[dict], directory: Path, stage: str, seed: int) -> list[Path]:
    saved: list[Path] = []
    for index, item in enumerate(remote_files):
        suffix = Path(str(item.get("filename", ""))).suffix or _default_suffix(stage)
        stem = f"{stage}_s{seed}" if len(remote_files) == 1 else f"{stage}_s{seed}_{index}"
        dest = directory / f"{stem}{suffix}"
        saved.append(client.download(item, dest))
    return saved


def _default_suffix(stage: str) -> str:
    return ".mp4" if stage == "video" else ".png"


def _write_workflows(directory: Path, stage: str, seeds: list[int], workflows: list[dict]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for seed, workflow in zip(seeds, workflows):
        path = directory / f"{stage}_s{seed}.json"
        path.write_text(json.dumps(workflow, indent=2) + "\n", encoding="utf-8")


def _record(directory: Path, stage: str, seeds: list[int], estimate: CostEstimate, prompt_ids: list[str]) -> None:
    path = directory / "ledger.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = {"entries": [], "approximate": True}
    data["entries"].append(
        {
            "stage": stage,
            "seeds": seeds,
            "credits": estimate.total,
            "approximate": True,
            "prompt_ids": prompt_ids,
        }
    )
    data["total_credits"] = sum(entry["credits"] for entry in data["entries"])
    directory.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def ledger_text(directory: Path) -> str:
    path = directory / "ledger.json"
    if not path.exists():
        return "No spend recorded. Dry-runs are not added to the ledger."
    data = json.loads(path.read_text(encoding="utf-8"))
    total = data.get("total_credits", 0)
    return (
        f"Recorded approximate spend: ~{total} credits "
        f"across {len(data.get('entries', []))} stage(s). Dry-runs are not included."
    )


def _require_key(client: ComfyClient | None) -> None:
    if client is not None:
        return
    if not os.environ.get("COMFY_API_KEY", "").strip():
        raise ComfyError("Set COMFY_API_KEY to a Comfy Cloud API key.")


def _pick(paths: list[Path], auto_pick: bool, label: str, picker) -> Path:
    if not paths:
        raise ComfyError(f"No {label} files to pick from")
    print(f"{label} variations:", file=sys.stderr)
    for index, path in enumerate(paths):
        print(f"  [{index}] {path}", file=sys.stderr)
    if auto_pick:
        print(f"Auto-picked [0] {paths[0]}", file=sys.stderr)
        return paths[0]
    if picker is None:
        if not sys.stdin.isatty():
            raise ComfyError(f"Pass --auto-pick to choose the first {label} variation when stdin is not a terminal.")
        raw = input(f"Pick a {label} index: ").strip()
    else:
        raw = str(picker(label, paths)).strip()
    try:
        index = int(raw)
        return paths[index]
    except (ValueError, IndexError) as exc:
        raise ComfyError(f"Pick a {label} index from 0 to {len(paths) - 1}") from exc
