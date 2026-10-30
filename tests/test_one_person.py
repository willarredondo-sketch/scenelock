"""One-person scenes: loading, prompts, and a dry-run start graph."""

import json
from pathlib import Path

import pytest
from PIL import Image

from app.dashboard import _scene_from_form
from scenelock.cli import main
from scenelock.pipeline import build_start_workflow, run_start
from scenelock.prompts import TABLE_RULE, build_end_prompt, build_start_prompt, build_video_prompt
from scenelock.scene import SceneError, load_scene
from scenelock.templates import load_template

SOLO = "examples/solo-portrait/scene.yaml"
IDENTITY = (
    "Keep the person's identity, hair, and clothing the same "
    "unless the requested pose explicitly changes them."
)
FORBIDDEN = (
    "second person",
    "two people",
    "other person",
    "other person's",
    "upper arm",
    "those seats",
    "reference image 3",
    "swap their seats",
    "who touches",
    "each person",
)


def test_solo_portrait_scene_loads():
    scene = load_scene(SOLO)
    assert scene.title == "Solo portrait"
    assert len(scene.characters) == 1
    assert scene.characters[0].name == "Person A"
    assert scene.characters[0].appearance == "the person"
    assert scene.characters[0].slot == "left"
    assert scene.characters[0].held_hand == "right"
    assert scene.location_image.name == "location.png"
    assert scene.characters[0].image.name == "person.png"
    assert scene.warnings == []
    assert "sitting up" in scene.start_pose
    assert "sitting down" in scene.end_pose


def test_one_person_prompts_skip_the_second_person():
    scene = load_scene(SOLO)
    start, start_warnings = build_start_prompt(scene)
    end, end_warnings = build_end_prompt(scene)
    video, video_warnings = build_video_prompt(scene)
    assert start_warnings == []
    assert end_warnings == []
    assert video_warnings == []

    assert start.startswith("Photorealistic")
    assert "One person at" in start
    assert "The location matches reference image 1." in start
    assert "Person A (reference image 2)" in start
    assert "The face, hair, and clothing match reference image 2." in start
    assert "room above the head." in start

    assert end.startswith("Edit this photo")
    assert "Person A stays on the left." in end
    assert IDENTITY in end
    assert "This is only a pose or position change." in end
    assert "Person A still holds the same object in the same one hand" in end
    assert "sitting up to sitting down" in end
    assert TABLE_RULE in end

    assert video.startswith("Static locked-off camera")
    assert "Person A stays on the left." in video
    assert "They stay in that seat." in video
    assert "The motion is only a pose or position change." in video
    assert "identity, hair, and clothing" in video
    assert "about 70%" in video

    blob = " ".join((start, end, video)).lower()
    for phrase in FORBIDDEN:
        assert phrase not in blob


def test_one_person_neck_warning_stays_off_the_other_arm():
    scene = load_scene(SOLO)
    scene.end_pose = "The person rests a hand on their neck."
    prompt, warnings = build_end_prompt(scene)
    assert any("away from the face and neck" in warning for warning in warnings)
    assert all("upper arm" not in warning for warning in warnings)
    assert "upper arm" not in prompt
    assert "other person" not in prompt.lower()
    assert IDENTITY in prompt


def test_one_person_template_orders_location_then_person():
    template = load_template("start_frame_1p.json")
    assert template["1"]["inputs"]["image"] == "{{LOCATION_IMAGE}}"
    assert template["2"]["inputs"]["image"] == "{{PERSON_A_IMAGE}}"
    assert template["3"]["class_type"] == "ImageBatch"
    assert template["3"]["inputs"]["image1"] == ["1", 0]
    assert template["3"]["inputs"]["image2"] == ["2", 0]
    assert template["4"]["class_type"] == "GeminiImage2Node"
    assert template["4"]["inputs"]["images"] == ["3", 0]
    assert template["5"]["class_type"] == "SaveImage"
    assert "PERSON_B" not in json.dumps(template)
    two = load_template("start_frame.json")
    assert two["3"]["inputs"]["image"] == "{{PERSON_B_IMAGE}}"
    assert two["6"]["inputs"]["images"] == ["5", 0]


def test_solo_dry_run_writes_one_person_workflow(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("COMFY_API_KEY", raising=False)
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network")),
    )
    code = main(
        ["run", "--scene", SOLO, "--dry-run", "-n", "1", "--output", str(tmp_path)]
    )
    assert code == 0
    output = capsys.readouterr().out
    assert "No API calls" in output
    assert "Dry-run start" in output
    assert "GeminiImage2Node" in output
    assert "ByteDanceFirstLastFrameNode" in output
    assert "{{" not in output
    lowered = output.lower()
    for phrase in FORBIDDEN:
        assert phrase not in lowered

    start = json.loads((tmp_path / "dry-run" / "start_s61001.json").read_text())
    assert set(start) == {"1", "2", "3", "4", "5"}
    assert start["1"]["inputs"]["image"].endswith("refs/location.png")
    assert start["2"]["inputs"]["image"].endswith("refs/person.png")
    assert start["3"]["class_type"] == "ImageBatch"
    assert start["3"]["inputs"] == {"image1": ["1", 0], "image2": ["2", 0]}
    assert start["4"]["class_type"] == "GeminiImage2Node"
    assert start["4"]["inputs"]["images"] == ["3", 0]
    assert isinstance(start["4"]["inputs"]["seed"], int)
    assert start["4"]["inputs"]["seed"] == 61001
    assert "One person at" in start["4"]["inputs"]["prompt"]
    assert "reference image 2" in start["4"]["inputs"]["prompt"]

    end = json.loads((tmp_path / "dry-run" / "end_s62001.json").read_text())
    assert end["2"]["class_type"] == "GeminiImage2Node"
    assert end["2"]["inputs"]["images"] == ["1", 0]
    assert IDENTITY in end["2"]["inputs"]["prompt"]
    assert "upper arm" not in end["2"]["inputs"]["prompt"]

    video = json.loads((tmp_path / "dry-run" / "video_s64001.json").read_text())
    assert video["3"]["class_type"] == "ByteDanceFirstLastFrameNode"
    assert "They stay in that seat." in video["3"]["inputs"]["prompt"]
    assert "those seats" not in video["3"]["inputs"]["prompt"]
    assert not (tmp_path / "ledger.json").exists()


def test_one_person_start_workflow_omits_person_b():
    scene = load_scene(SOLO)
    workflow, warnings = build_start_workflow(scene, 61001)
    assert warnings == []
    assert "PERSON_B_IMAGE" not in json.dumps(workflow)
    assert workflow["4"]["inputs"]["images"] == ["3", 0]
    assert workflow["2"]["inputs"]["image"].endswith("person.png")


def test_one_person_submit_uploads_location_then_person(tmp_path, monkeypatch):
    monkeypatch.delenv("COMFY_API_KEY", raising=False)
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network")),
    )
    refs = tmp_path / "refs"
    refs.mkdir()
    Image.new("RGB", (8, 12), "gray").save(refs / "location.png")
    Image.new("RGB", (8, 16), "blue").save(refs / "person.png")
    scene_path = tmp_path / "scene.yaml"
    scene_path.write_text(Path(SOLO).read_text(encoding="utf-8"), encoding="utf-8")

    class FakeClient:
        def __init__(self):
            self.uploads = []
            self.workflows = []

        def upload_image(self, path):
            self.uploads.append(path)
            return "remote-" + Path(path).name

        def submit(self, workflow):
            self.workflows.append(workflow)
            return "prompt-1"

        def wait_for_files(self, prompt_id):
            return [{"filename": "scenelock/start_00001_.png", "subfolder": "", "type": "output"}]

        def download(self, item, dest: Path):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"png")
            return dest

    fake = FakeClient()
    result = run_start(load_scene(scene_path), 1, False, True, tmp_path / "out", client=fake)
    assert result.submitted
    assert len(fake.uploads) == 2
    assert [Path(path).name for path in fake.uploads] == ["location.png", "person.png"]
    assert fake.workflows[0]["1"]["inputs"]["image"] == "remote-location.png"
    assert fake.workflows[0]["2"]["inputs"]["image"] == "remote-person.png"
    assert fake.workflows[0]["3"]["class_type"] == "ImageBatch"
    load_images = [node for node in fake.workflows[0].values() if node["class_type"] == "LoadImage"]
    assert len(load_images) == 2


def test_dashboard_person_b_file_selects_the_mode(tmp_path, monkeypatch):
    monkeypatch.setattr("app.dashboard.WORK", tmp_path)
    location = tmp_path / "location.png"
    person_a = tmp_path / "a.png"
    person_b = tmp_path / "b.png"
    Image.new("RGB", (4, 4), "white").save(location)
    Image.new("RGB", (4, 4), "red").save(person_a)
    Image.new("RGB", (4, 4), "blue").save(person_b)

    def form(person_b_file, name_b="", object_b=""):
        return _scene_from_form(
            "Solo portrait",
            "a window seat",
            "Person A",
            "left",
            "a ceramic mug",
            "right",
            name_b,
            "right",
            object_b,
            "left",
            "exactly one ceramic mug",
            "sitting upright",
            "sitting down",
            "settles into the seat",
            8,
            "9:16",
            "1K",
            "720p",
            1,
            str(location),
            str(person_a),
            person_b_file,
        )

    solo, count = form(None)
    assert count == 1
    assert [character.name for character in solo.characters] == ["Person A"]
    start, _warnings = build_start_prompt(solo)
    assert "One person at" in start
    assert "reference image 3" not in start

    pair, _count = form(str(person_b), name_b="Person B", object_b="a ceramic mug")
    assert [character.name for character in pair.characters] == ["Person A", "Person B"]
    start, _warnings = build_start_prompt(pair)
    assert "Two people at" in start
    assert "Person B (reference image 3)" in start

    with pytest.raises(SceneError, match="held_object"):
        form(str(person_b), name_b="Person B", object_b="")
