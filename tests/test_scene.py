from pathlib import Path

import pytest

from scenelock.scene import SceneError, load_scene, scene_from_mapping, seeds_for

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


def test_one_or_two_characters(tmp_path):
    text = EXAMPLE.read_text(encoding="utf-8")
    start = text.index("  - name: Person B")
    end = text.index("table_lock:")
    path = tmp_path / "scene.yaml"
    path.write_text(text[:start] + text[end:], encoding="utf-8")
    scene = load_scene(path)
    assert [character.name for character in scene.characters] == ["Person A"]
    assert scene.characters[0].slot == "left"

    both_left = text.replace("slot: right", "slot: left")
    path.write_text(both_left, encoding="utf-8")
    with pytest.raises(SceneError, match="left and the other on the right"):
        load_scene(path)


def test_character_count_rejects_zero_and_three():
    with pytest.raises(SceneError, match="1 or 2"):
        scene_from_mapping(_people(0), Path("."))
    with pytest.raises(SceneError, match="1 or 2"):
        scene_from_mapping(_people(3), Path("."))
    solo = scene_from_mapping(_people(1, slot="right"), Path("."))
    assert len(solo.characters) == 1
    assert solo.characters[0].slot == "right"
    pair = scene_from_mapping(_people(2), Path("."))
    assert [character.slot for character in pair.characters] == ["left", "right"]


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


def _people(count: int, slot: str = "left") -> dict:
    characters = []
    for index in range(count):
        if count == 1:
            seat = slot
        else:
            seat = "left" if index % 2 == 0 else "right"
        characters.append(
            {
                "name": f"Person {index + 1}",
                "image": f"person_{index + 1}.png",
                "slot": seat,
                "held_object": "a mug",
                "held_hand": "right",
            }
        )
    return {
        "title": "Count",
        "setting": "a room",
        "start_pose": "sitting up",
        "end_pose": "sitting down",
        "motion_beat": "settles back",
        "duration": 8,
        "refs": {"location": "location.png"},
        "characters": characters,
        "table_lock": ["exactly one mug"],
    }
