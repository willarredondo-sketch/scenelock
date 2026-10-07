"""Frame grabs, contact sheet, hand crops, and a human QA checklist."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from qa.reviewer import ReviewFlag, load_reviewer
from scenelock.scene import Scene

# Heuristics, not a measured error rate. Flat regions can keep a high SSIM
# while the color still changed, so the mean absolute difference is checked too.
SSIM_FLAG_BELOW = 0.8
MAE_FLAG_ABOVE = 12.0


@dataclass
class QaReport:
    notes_path: Path
    contact_sheet: Path | None
    frames: list[Path] = field(default_factory=list)
    crops: list[Path] = field(default_factory=list)
    start_ssim: float | None = None
    end_ssim: float | None = None
    start_mae: float | None = None
    end_mae: float | None = None
    flags: list[str] = field(default_factory=list)


def run_qa(
    scene: Scene,
    video: str | Path,
    start_image: str | Path,
    end_image: str | Path,
    output: str | Path,
    interval: float = 1.0,
    reviewer_path: str | None = None,
) -> QaReport:
    video_path = Path(video)
    start_path = Path(start_image)
    end_path = Path(end_image)
    for path in (video_path, start_path, end_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    destination = Path(output)
    frame_dir = destination / "frames"
    crop_dir = destination / "crops"
    frame_dir.mkdir(parents=True, exist_ok=True)
    crop_dir.mkdir(parents=True, exist_ok=True)

    first = frame_dir / "first.png"
    last = frame_dir / "last.png"
    _grab_first(video_path, first)
    _grab_last(video_path, last)
    interval_frames = _grab_interval(video_path, frame_dir, interval)
    frames = [first, *interval_frames, last]

    sheet_path = destination / "contact_sheet.jpg"
    contact_sheet(frames, sheet_path)

    crop_paths, crop_note = _write_crops(frames, crop_dir)
    start_diff = _compare(start_path, first, scene)
    end_diff = _compare(end_path, last, scene)

    reviewer = load_reviewer(reviewer_path)
    review_flags = reviewer.review(video_path, frames)
    notes_path = destination / "QA_NOTES.md"
    _write_notes(
        notes_path,
        scene,
        video_path,
        start_path,
        end_path,
        frames,
        crop_paths,
        crop_note,
        sheet_path,
        start_diff,
        end_diff,
        review_flags,
        reviewer_path,
    )
    tool_flags = []
    if start_diff.flagged:
        tool_flags.append("start-frame prop drift")
    if end_diff.flagged:
        tool_flags.append("end-frame prop drift")
    tool_flags.extend(flag.claim for flag in review_flags)
    return QaReport(
        notes_path,
        sheet_path,
        frames,
        crop_paths,
        start_diff.ssim,
        end_diff.ssim,
        start_diff.mae,
        end_diff.mae,
        tool_flags,
    )


def contact_sheet(frames: list[Path], dest: Path, columns: int = 4, thumb: int = 240) -> Path:
    images = [Image.open(path).convert("RGB") for path in frames]
    if not images:
        raise ValueError("No frames for the contact sheet")
    columns = max(1, min(columns, len(images)))
    rows = (len(images) + columns - 1) // columns
    fitted = [_fit(image, thumb) for image in images]
    cell_w = max(image.width for image in fitted)
    cell_h = max(image.height for image in fitted)
    sheet = Image.new("RGB", (columns * cell_w, rows * cell_h), "white")
    for index, image in enumerate(fitted):
        x = (index % columns) * cell_w
        y = (index // columns) * cell_h
        sheet.paste(image, (x, y))
    dest.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dest, quality=85)
    return dest


def ssim_score(left: Image.Image, right: Image.Image) -> float:
    """Global SSIM on a small grayscale pair. Identical images score 1."""
    a, b = _gray_pair(left, right)
    count = len(a)
    mean_a = sum(a) / count
    mean_b = sum(b) / count
    var_a = sum((pixel - mean_a) ** 2 for pixel in a) / (count - 1)
    var_b = sum((pixel - mean_b) ** 2 for pixel in b) / (count - 1)
    cov = sum((pixel_a - mean_a) * (pixel_b - mean_b) for pixel_a, pixel_b in zip(a, b)) / (count - 1)
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2
    numerator = (2 * mean_a * mean_b + c1) * (2 * cov + c2)
    denominator = (mean_a**2 + mean_b**2 + c1) * (var_a + var_b + c2)
    if denominator == 0:
        return 1.0
    return numerator / denominator


def mean_abs_diff(left: Image.Image, right: Image.Image) -> float:
    """Mean absolute difference on the same grayscale pair, 0 to 255."""
    a, b = _gray_pair(left, right)
    return sum(abs(pixel_a - pixel_b) for pixel_a, pixel_b in zip(a, b)) / len(a)


def _gray_pair(left: Image.Image, right: Image.Image) -> tuple[list[int], list[int]]:
    size = (128, 128)
    a = list(left.convert("L").resize(size).tobytes())
    b = list(right.convert("L").resize(size).tobytes())
    return a, b


def center_box(image: Image.Image) -> tuple[int, int, int, int]:
    width, height = image.size
    crop_w = max(1, width // 2)
    crop_h = max(1, height // 2)
    left = (width - crop_w) // 2
    top = (height - crop_h) // 2
    return (left, top, left + crop_w, top + crop_h)


def zoom_crop(image: Image.Image, box: tuple[int, int, int, int], scale: int = 2) -> Image.Image:
    crop = image.crop(box)
    return crop.resize((max(1, crop.width * scale), max(1, crop.height * scale)), Image.Resampling.LANCZOS)


def hand_boxes(image: Image.Image) -> list[tuple[int, int, int, int]]:
    """Return pixel boxes around detected hands, or an empty list."""
    try:
        import mediapipe as mp
        import numpy as np
    except ImportError:
        return []
    try:
        rgb = np.asarray(image.convert("RGB"))
        hands = mp.solutions.hands.Hands(static_image_mode=True, max_num_hands=4)
        try:
            result = hands.process(rgb)
        finally:
            hands.close()
    except Exception:
        return []
    if not result or not result.multi_hand_landmarks:
        return []
    width, height = image.size
    boxes = []
    for hand in result.multi_hand_landmarks:
        xs = [landmark.x for landmark in hand.landmark]
        ys = [landmark.y for landmark in hand.landmark]
        pad = 0.08
        x0 = max(0.0, min(xs) - pad)
        y0 = max(0.0, min(ys) - pad)
        x1 = min(1.0, max(xs) + pad)
        y1 = min(1.0, max(ys) + pad)
        left = int(x0 * width)
        top = int(y0 * height)
        right = max(left + 1, int(x1 * width))
        bottom = max(top + 1, int(y1 * height))
        boxes.append((left, top, right, bottom))
    return boxes


def _write_crops(frames: list[Path], crop_dir: Path) -> tuple[list[Path], str]:
    saved: list[Path] = []
    used_hands = False
    fell_back = False
    # First, a middle frame, and last are enough to inspect. Cap the rest.
    chosen = _sample(frames, limit=8)
    for frame_path in chosen:
        image = Image.open(frame_path).convert("RGB")
        boxes = hand_boxes(image)
        if boxes:
            used_hands = True
            for index, box in enumerate(boxes):
                crop = zoom_crop(image, box)
                dest = crop_dir / f"{frame_path.stem}_hand{index}.png"
                crop.save(dest)
                saved.append(dest)
        else:
            fell_back = True
            crop = zoom_crop(image, center_box(image))
            dest = crop_dir / f"{frame_path.stem}_center.png"
            crop.save(dest)
            saved.append(dest)
    if used_hands and not fell_back:
        note = "2x crops around MediaPipe hand boxes"
    elif used_hands and fell_back:
        note = "2x hand crops where MediaPipe found a hand; centre crops otherwise"
    else:
        note = "2x centre crops (MediaPipe not installed or no hands found)"
    return saved, note


@dataclass
class FrameDiff:
    ssim: float
    mae: float
    region: str

    @property
    def flagged(self) -> bool:
        return self.ssim < SSIM_FLAG_BELOW or self.mae > MAE_FLAG_ABOVE


def _compare(still_path: Path, frame_path: Path, scene: Scene) -> FrameDiff:
    still = Image.open(still_path).convert("RGB")
    frame = Image.open(frame_path).convert("RGB")
    if scene.table_bbox:
        still_crop = _crop_bbox(still, scene.table_bbox, still.size)
        frame_crop = _crop_bbox(frame, scene.table_bbox, still.size)
        region = "table bbox"
    else:
        still_crop = still
        frame_crop = frame
        region = "full frame (no table_bbox in the scene)"
    return FrameDiff(ssim_score(still_crop, frame_crop), mean_abs_diff(still_crop, frame_crop), region)


def _crop_bbox(image: Image.Image, bbox: tuple[int, int, int, int], reference_size: tuple[int, int]) -> Image.Image:
    ref_w, ref_h = reference_size
    scale_x = image.width / ref_w
    scale_y = image.height / ref_h
    x, y, width, height = bbox
    left = int(x * scale_x)
    top = int(y * scale_y)
    right = int((x + width) * scale_x)
    bottom = int((y + height) * scale_y)
    left = max(0, min(left, image.width - 1))
    top = max(0, min(top, image.height - 1))
    right = max(left + 1, min(right, image.width))
    bottom = max(top + 1, min(bottom, image.height))
    return image.crop((left, top, right, bottom))


def _write_notes(
    path: Path,
    scene: Scene,
    video: Path,
    start: Path,
    end: Path,
    frames: list[Path],
    crops: list[Path],
    crop_note: str,
    sheet: Path,
    start_diff: FrameDiff,
    end_diff: FrameDiff,
    review_flags: list[ReviewFlag],
    reviewer_path: str | None,
) -> None:
    start_result = _diff_result(start_diff)
    end_result = _diff_result(end_diff)
    if reviewer_path:
        reviewer_result = f"{len(review_flags)} flag(s) from {reviewer_path}"
    else:
        reviewer_result = "reviewer off"
    rows = [
        ("Full-res frame grabs", f"{len(frames)} frames in {frames[0].parent}"),
        ("Contact sheet", str(sheet)),
        ("Hand / centre crops", f"{len(crops)} crops. {crop_note}"),
        ("Start still vs first video frame", start_result),
        ("End still vs last video frame", end_result),
        ("Melted hands, extra fingers, prop swaps", "not judged automatically"),
        ("Vision-model flags", reviewer_result),
    ]
    lines = [
        "# QA notes",
        "",
        "The tool flags. A human writes CONFIRMED or NOT FOUND. "
        "Video-review models hallucinate extra limbs from motion blur, so check every flag "
        "against the full-res frames before treating it as real.",
        "",
        f"- Video: `{video}`",
        f"- Start frame: `{start}`",
        f"- End frame: `{end}`",
        "",
        "## Table lock",
        "",
    ]
    for item in scene.table_lock:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Checklist",
            "",
            "| Check | Tool result | CONFIRMED / NOT FOUND |",
            "| --- | --- | --- |",
        ]
    )
    for check, result in rows:
        lines.append(f"| {check} | {result} |  |")
    if review_flags:
        lines.extend(["", "## Reviewer flags", ""])
        lines.append("These are flags only. Confirm each one on the full-res frame named here.")
        lines.append("")
        lines.append("| Claim | Frame | Note | CONFIRMED / NOT FOUND |")
        lines.append("| --- | --- | --- | --- |")
        for flag in review_flags:
            lines.append(
                f"| {_cell(flag.claim)} | {_cell(flag.frame or '')} | {_cell(flag.note)} |  |"
            )
    lines.extend(["", "## Frames", ""])
    for frame in frames:
        lines.append(f"- `{frame}`")
    lines.extend(["", "## Crops", ""])
    for crop in crops:
        lines.append(f"- `{crop}`")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _diff_result(diff: FrameDiff) -> str:
    label = "possible prop drift" if diff.flagged else "within the heuristic band"
    return f"SSIM {diff.ssim:.3f}, mean abs diff {diff.mae:.1f} on {diff.region}; {label}"


def _cell(value: str) -> str:
    return value.replace("|", "/")


def _fit(image: Image.Image, thumb: int) -> Image.Image:
    copy = image.copy()
    copy.thumbnail((thumb, thumb))
    return copy


def _sample(frames: list[Path], limit: int) -> list[Path]:
    if len(frames) <= limit:
        return list(frames)
    step = (len(frames) - 1) / (limit - 1)
    indexes = {round(step * i) for i in range(limit)}
    return [frames[index] for index in sorted(indexes)]


def _grab_first(video: Path, dest: Path) -> None:
    _ffmpeg(["-y", "-i", str(video), "-frames:v", "1", "-update", "1", str(dest)])
    if not dest.is_file():
        raise RuntimeError(f"ffmpeg did not write {dest.name}")


def _grab_last(video: Path, dest: Path) -> None:
    # Reverse then take one frame. These clips are a few seconds long.
    _ffmpeg(["-y", "-i", str(video), "-vf", "reverse", "-frames:v", "1", "-update", "1", str(dest)])
    if not dest.is_file():
        raise RuntimeError(f"ffmpeg did not write {dest.name}")


def _grab_interval(video: Path, frame_dir: Path, interval: float) -> list[Path]:
    if interval <= 0:
        raise ValueError("interval must be positive")
    pattern = str(frame_dir / "interval_%04d.png")
    fps = 1.0 / interval
    _ffmpeg(["-y", "-i", str(video), "-vf", f"fps={fps}", pattern])
    return sorted(frame_dir.glob("interval_*.png"))


def _ffmpeg(args: list[str]) -> None:
    binary = shutil.which("ffmpeg")
    if not binary:
        raise RuntimeError("ffmpeg is required for QA frame grabs")
    completed = subprocess.run([binary, *args], capture_output=True, text=True)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        tail = detail[-1] if detail else "ffmpeg failed"
        raise RuntimeError(tail)

