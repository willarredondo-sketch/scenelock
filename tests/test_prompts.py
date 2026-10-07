from scenelock.prompts import build_end_prompt, build_start_prompt, build_video_prompt
from scenelock.scene import load_scene

EXAMPLE = "examples/backyard-burgers/scene.yaml"


def test_prompts_bake_in_the_run_lessons():
    scene = load_scene(EXAMPLE)
    start, start_warnings = build_start_prompt(scene)
    end, end_warnings = build_end_prompt(scene)
    video, video_warnings = build_video_prompt(scene)
    assert start_warnings == []
    assert end_warnings == []
    assert video_warnings == []

    assert "reference image 1" in start
    assert "Person A (reference image 2)" in start
    assert "Person B (reference image 3)" in start
    assert "left hand only" in start
    assert "both hands" in start
    assert "Static camera" in start

    assert start.startswith("Photorealistic")
    assert end.startswith("Edit this photo")
    assert "Person A stays on the left." in end
    assert "Person B stays on the right." in end
    assert "Do not swap their seats." in end
    assert "upper arm or shoulder" in end
    assert "never the neck" in end
    assert "Closed-mouth smiles" in end

    assert video.startswith("Static locked-off camera")
    assert "about 70%" in video
    assert "same one hand for the whole clip" in video
    assert "Hands stay away from faces and necks." in video


def test_risky_pose_text_warns_but_stays_in_the_prompt():
    scene = load_scene(EXAMPLE)
    scene.start_pose = "Person A is mid-bite with both hands on the burger."
    scene.end_pose = "Person A puts a hand on Person B's neck while laughing."
    scene.motion_beat = "They laugh with open mouths."
    _start, start_warnings = build_start_prompt(scene)
    end, end_warnings = build_end_prompt(scene)
    _video, video_warnings = build_video_prompt(scene)
    assert any("both hands" in warning for warning in start_warnings)
    assert any("neck" in warning for warning in end_warnings)
    assert any("open mouth" in warning or "Open laughter" in warning for warning in video_warnings)
    assert "neck" in end
    assert "never the neck" in end
