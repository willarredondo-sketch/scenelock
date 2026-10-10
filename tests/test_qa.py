import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from qa.check import align_frame_to_still, contact_sheet, mean_abs_diff, run_qa, ssim_score
from scenelock.scene import load_scene

EXAMPLE = Path("examples/backyard-burgers/scene.yaml")


def test_ssim_is_one_for_the_same_image():
    image = Image.new("RGB", (32, 48), (180, 40, 40))
    assert ssim_score(image, image) == pytest.approx(1.0)
    other = Image.new("RGB", (32, 48), (20, 20, 180))
    assert ssim_score(image, other) < 0.8


def test_alignment_undoes_a_small_vertical_stretch():
    # Thin horizontal stripes make a ~3% vertical shift obvious. The frame is the
    # inverse of a 1.03 width-fit: pad, scale to the video size, so alignment
    # at 1.03 centre-crops back to the still and a plain resize does not.
    still = _striped((160, 284))
    frame_size = (150, 273)
    vertical = 1.03
    # Same height the aligner will produce at this scale, before the centre crop.
    content_h = int(round(frame_size[1] * (still.width / frame_size[0]) * vertical))
    assert content_h > still.height
    distorted = _inverse_of_vertical_scale(still, frame_size, content_h)
    naive = distorted.resize(still.size, Image.Resampling.LANCZOS)
    aligned, scale = align_frame_to_still(still, distorted)
    assert aligned.size == still.size
    assert scale == 1.03
    assert mean_abs_diff(still, aligned) < mean_abs_diff(still, naive)


def _striped(size: tuple[int, int]) -> Image.Image:
    image = Image.new("RGB", size)
    pixels = image.load()
    width, height = size
    for y in range(height):
        color = ((y * 37) % 256, (y * 17) % 256, (y * 53) % 256)
        for x in range(width):
            pixels[x, y] = color
    return image


def _inverse_of_vertical_scale(
    still: Image.Image, frame_size: tuple[int, int], content_h: int
) -> Image.Image:
    """Build a frame that `_resize_with_vertical_scale(..., vertical)` turns back into `still`."""
    frame_w, frame_h = frame_size
    pad = content_h - still.height
    top_pad = pad // 2
    canvas = Image.new("RGB", (still.width, content_h), (0, 0, 0))
    canvas.paste(still, (0, top_pad))
    return canvas.resize((frame_w, frame_h), Image.Resampling.LANCZOS)


def test_contact_sheet_and_notes(tmp_path):
    frames = []
    for index, color in enumerate(((200, 30, 30), (200, 30, 30), (20, 20, 200))):
        path = tmp_path / f"frame_{index}.png"
        Image.new("RGB", (64, 96), color).save(path)
        frames.append(path)
    sheet = contact_sheet(frames, tmp_path / "sheet.jpg")
    assert sheet.is_file()
    assert Image.open(sheet).size[0] > 10


def test_qa_flags_prop_drift_and_leaves_the_decision_blank(tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not installed")
    start = tmp_path / "start.png"
    end = tmp_path / "end.png"
    Image.new("RGB", (64, 96), (180, 40, 40)).save(start)
    Image.new("RGB", (64, 96), (20, 40, 180)).save(end)
    video = tmp_path / "clip.mp4"
    _encode_solid(video, "red")
    scene = load_scene(EXAMPLE)
    scene.table_bbox = (0, 48, 64, 48)
    report = run_qa(scene, video, start, end, tmp_path / "qa", interval=1.0)
    notes = report.notes_path.read_text(encoding="utf-8")
    assert report.notes_path.name == "QA_NOTES.md"
    assert "CONFIRMED / NOT FOUND" in notes
    assert "motion blur" in notes
    assert "reviewer off" in notes
    assert "one small ketchup cup" in notes
    assert report.contact_sheet.is_file()
    assert list((tmp_path / "qa" / "crops").glob("*center.png"))
    assert report.start_ssim is not None and report.start_ssim > 0.8
    assert "start-frame prop drift" not in report.flags
    assert "end-frame prop drift" in report.flags
    assert report.end_mae is not None and report.end_mae > 12
    assert "possible prop drift" in notes
    # The human column stays empty. The header is the only place those words are a label.
    assert "| possible prop drift |" not in notes
    decision_cells = [line.split("|")[-2].strip() for line in notes.splitlines() if line.startswith("| ") and "Check" not in line and "---" not in line]
    assert decision_cells
    assert all(cell == "" for cell in decision_cells)


def test_reviewer_flags_are_listed_for_a_human(tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not installed")
    still = tmp_path / "still.png"
    Image.new("RGB", (32, 48), (10, 140, 10)).save(still)
    video = tmp_path / "clip.mp4"
    _encode_solid(video, "green")
    scene = load_scene(EXAMPLE)
    report = run_qa(
        scene,
        video,
        still,
        still,
        tmp_path / "qa",
        reviewer_path="tests.sample_reviewer:FlaggingReviewer",
    )
    notes = report.notes_path.read_text(encoding="utf-8")
    assert "extra finger" in notes
    assert "check the full-res grab" in notes
    assert "reviewer off" not in notes
    assert "CONFIRMED" not in notes.split("Reviewer flags", 1)[-1].split("Frames", 1)[0].replace("CONFIRMED / NOT FOUND", "")


def _encode_solid(dest: Path, color: str) -> None:
    completed = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=64x96:d=1",
            "-r",
            "8",
            "-pix_fmt",
            "yuv420p",
            str(dest),
        ],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        pytest.skip(completed.stderr[-200:])
