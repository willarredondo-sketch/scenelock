from pathlib import Path

import pytest

from scenelock.scene import SceneError, load_scene, seeds_for

EXAMPLE = Path("examples/backyard-burgers/scene.yaml")


def test_example_scene_parses():
    scene = load_scene(EXAMPLE)
    assert scene.title == "Backyard burgers"
    assert scene.duration == 8
    assert scene.aspect_ratio == "9:16"
    assert scene.image_resolution == "1K"
    assert scene.video_resolution == "720p"
    assert [character.name for character in scene.characters] == ["Person A", "Person B"]
    assert scene.characters[0].slot == "left"
    assert scene.characters[0].held_hand == "left"
    assert scene.table_bbox is None
    assert any("ketchup" in item for item in scene.table_lock)
    assert scene.location_image.name == "location.png"
    assert scene.warnings == []


def test_seeds_extend_when_count_is_larger():
    scene = load_scene(EXAMPLE)
    assert seeds_for(scene, "video", 1) == [64001]
    assert seeds_for(scene, "start", 5)[:4] == [61001, 61011, 61021, 61031]
    assert seeds_for(scene, "start", 5)[-1] == 61041


def test_two_characters_required(tmp_path):
    text = EXAMPLE.read_text(encoding="utf-8")
    start = text.index("  - name: Person B")
    end = text.index("table_lock:")
    broken = text[:start] + text[end:]
    path = tmp_path / "scene.yaml"
    path.write_text(broken, encoding="utf-8")
    with pytest.raises(SceneError, match="exactly two"):
        load_scene(path)


def test_aspect_ratio_must_be_quoted(tmp_path):
    text = EXAMPLE.read_text(encoding="utf-8").replace('aspect_ratio: "9:16"', "aspect_ratio: 9:16")
    path = tmp_path / "scene.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(SceneError, match="aspect_ratio"):
        load_scene(path)


def test_table_bbox_and_duration_warning(tmp_path):
    scene = load_scene(EXAMPLE)
    data_path = tmp_path / "scene.yaml"
    text = EXAMPLE.read_text(encoding="utf-8").replace("duration: 8", "duration: 5")
    text = text.replace("table_bbox: null", "table_bbox: [10, 20, 30, 40]")
    data_path.write_text(text, encoding="utf-8")
    parsed = load_scene(data_path)
    assert parsed.table_bbox == (10, 20, 30, 40)
    assert parsed.duration == 5
    assert any("6-8" in warning for warning in parsed.warnings)
    assert scene.duration == 8
