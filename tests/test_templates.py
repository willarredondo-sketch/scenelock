import json
from pathlib import Path

from scenelock.prompts import TABLE_RULE
from scenelock.scene import load_scene
from scenelock.pipeline import build_end_workflow, build_start_workflow, build_video_workflow
from scenelock.templates import fill_workflow, load_template

EXAMPLE = Path("examples/backyard-burgers/scene.yaml")
ROOT = Path(__file__).resolve().parents[1]
BANNED = ("osatoshi", "pepsi", "marco", "chris")


def test_templates_keep_the_node_graph_and_placeholders():
    start = load_template("start_frame.json")
    end = load_template("end_frame_edit.json")
    video = load_template("flf_video.json")
    assert start["6"]["class_type"] == "GeminiImage2Node"
    assert start["6"]["inputs"]["images"] == ["5", 0]
    assert start["1"]["inputs"]["image"] == "{{LOCATION_IMAGE}}"
    assert end["2"]["inputs"]["images"] == ["1", 0]
    assert video["3"]["class_type"] == "ByteDanceFirstLastFrameNode"
    assert video["3"]["inputs"]["camera_fixed"] is True
    assert video["3"]["inputs"]["first_frame"] == ["1", 0]
    assert video["3"]["inputs"]["last_frame"] == ["2", 0]
    reference = json.loads((ROOT / "workflows/reference/i2v_seedance_v1.json").read_text())
    assert reference["2"]["class_type"] == "ByteDanceImageToVideoNode"


def test_fill_replaces_placeholders_and_types_numbers():
    filled = fill_workflow(
        load_template("flf_video.json"),
        {
            "START_FRAME_IMAGE": "start.png",
            "END_FRAME_IMAGE": "end.png",
            "VIDEO_PROMPT": "static camera",
            "VIDEO_MODEL": "seedance-1-5-pro-251215",
            "VIDEO_RESOLUTION": "720p",
            "ASPECT_RATIO": "9:16",
            "DURATION": 8,
            "SEED": 64001,
            "FILENAME_PREFIX": "scenelock/video_s64001",
        },
    )
    assert filled["3"]["inputs"]["seed"] == 64001
    assert filled["3"]["inputs"]["duration"] == 8
    assert isinstance(filled["3"]["inputs"]["seed"], int)
    assert filled["3"]["inputs"]["camera_fixed"] is True
    assert "{{" not in json.dumps(filled)


def test_built_workflows_use_scene_text_and_generic_prefixes():
    scene = load_scene(EXAMPLE)
    start, _warnings = build_start_workflow(scene, 61001)
    end, _warnings = build_end_workflow(scene, 62011, Path("chosen-start.png"))
    video, _warnings = build_video_workflow(scene, 64001, Path("chosen-start.png"), Path("chosen-end.png"))
    blob = json.dumps([start, end, video])
    assert "{{" not in blob
    assert "scenelock/start_s61001" in blob
    assert "scenelock/end_s62011" in blob
    assert "scenelock/video_s64001" in blob
    assert TABLE_RULE in start["6"]["inputs"]["prompt"]
    assert TABLE_RULE in end["2"]["inputs"]["prompt"]
    assert "one small ketchup cup" in start["6"]["inputs"]["prompt"]
    assert "one small ketchup cup" in end["2"]["inputs"]["prompt"]
    assert start["6"]["inputs"]["model"] == "gemini-3-pro-image-preview"
    assert video["3"]["inputs"]["model"] == "seedance-1-5-pro-251215"
    assert video["3"]["inputs"]["resolution"] == "720p"
    for word in BANNED:
        assert word not in blob.lower()


def test_repo_has_no_personal_or_brand_references():
    allowed_suffixes = {".py", ".md", ".json", ".yaml", ".yml", ".txt"}
    skip = {".git", "tests", "__pycache__", ".pytest_cache", "outputs", ".venv"}
    offenders = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in allowed_suffixes:
            continue
        if any(part in skip for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for word in BANNED:
            if word in text:
                offenders.append(f"{word} in {path}")
    assert offenders == []
