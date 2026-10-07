import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from qa.check import contact_sheet, run_qa, ssim_score
from scenelock.scene import load_scene

EXAMPLE = Path("examples/backyard-burgers/scene.yaml")


def test_ssim_is_one_for_the_same_image():
    image = Image.new("RGB", (32, 48), (180, 40, 40))
    assert ssim_score(image, image) == pytest.approx(1.0)
    other = Image.new("RGB", (32, 48), (20, 20, 180))
    assert ssim_score(image, other) < 0.8


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
