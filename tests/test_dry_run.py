import json
from pathlib import Path

import pytest
from PIL import Image

from scenelock.cli import main
from scenelock.pipeline import run_start

EXAMPLE = "examples/backyard-burgers/scene.yaml"


class BoomClient:
    def __init__(self, *args, **kwargs):
        raise AssertionError("Comfy client should not be constructed")

    def upload_image(self, path):
        raise AssertionError("upload")

    def submit(self, workflow):
        raise AssertionError("submit")


class FakeClient:
    def __init__(self):
        self.uploads = []
        self.workflows = []

    def upload_image(self, path):
        self.uploads.append(path)
        return "remote-" + Path(path).name

    def submit(self, workflow):
        self.workflows.append(workflow)
        return f"prompt-{len(self.workflows)}"

    def wait_for_files(self, prompt_id):
        return [{"filename": "scenelock/start_00001_.png", "subfolder": "", "type": "output"}]

    def download(self, item, dest: Path):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"png")
        return dest


def test_dry_run_prints_workflows_without_a_client(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("COMFY_API_KEY", raising=False)
    monkeypatch.setattr("scenelock.pipeline.ComfyClient", BoomClient)
    code = main(["start", "--scene", EXAMPLE, "--dry-run", "-n", "2", "--output", str(tmp_path)])
    assert code == 0
    output = capsys.readouterr().out
    assert "{{" not in output
    assert "Dry-run start" in output
    assert "Total ~72" in output
    assert "seed 61001" in output
    assert "seed 61011" in output
    assert "No API calls" in output
    saved = list((tmp_path / "dry-run").glob("start_s*.json"))
    assert len(saved) == 2
    workflow = json.loads(saved[0].read_text())
    assert isinstance(workflow["6"]["inputs"]["seed"], int)
    assert not (tmp_path / "ledger.json").exists()


def test_run_dry_run_covers_all_stages(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("COMFY_API_KEY", raising=False)
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network")))
    code = main(["run", "--scene", EXAMPLE, "--dry-run", "-n", "1", "--output", str(tmp_path)])
    assert code == 0
    output = capsys.readouterr().out
    assert "Full-run estimate" in output
    assert "Total ~116" in output  # 36 + 36 + 44
    assert "GeminiImage2Node" in output
    assert "ByteDanceFirstLastFrameNode" in output
    assert "dry-run/chosen-start.png" in output
    assert "QA runs after a video exists" in output
    assert list((tmp_path / "dry-run").glob("*.json"))


def test_yes_is_required_and_makes_no_request(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("COMFY_API_KEY", raising=False)
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network")))
    code = main(["video", "--scene", EXAMPLE, "--start", "a.png", "--end", "b.png", "--output", str(tmp_path)])
    assert code == 2
    output = capsys.readouterr().out
    assert "Total ~44" in output
    assert "--yes" in output
    assert "Nothing was submitted." in output


def test_live_start_uploads_then_submits_remote_names(tmp_path, monkeypatch):
    monkeypatch.delenv("COMFY_API_KEY", raising=False)
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network")))
    refs = tmp_path / "refs"
    refs.mkdir()
    for name in ("location.png", "person_a.png", "person_b.png"):
        Image.new("RGB", (8, 12), "gray").save(refs / name)
    scene_text = Path(EXAMPLE).read_text(encoding="utf-8")
    scene_path = tmp_path / "scene.yaml"
    scene_path.write_text(scene_text, encoding="utf-8")
    fake = FakeClient()
    from scenelock.scene import load_scene

    scene = load_scene(scene_path)
    result = run_start(scene, 1, False, True, tmp_path / "out", client=fake)
    assert result.submitted
    assert len(fake.uploads) == 3
    images = [
        fake.workflows[0]["1"]["inputs"]["image"],
        fake.workflows[0]["2"]["inputs"]["image"],
        fake.workflows[0]["3"]["inputs"]["image"],
    ]
    assert images == ["remote-location.png", "remote-person_a.png", "remote-person_b.png"]
    assert result.files[0].is_file()
    ledger = json.loads((tmp_path / "out" / "ledger.json").read_text())
    assert ledger["total_credits"] == 36
    assert ledger["entries"][0]["prompt_ids"] == ["prompt-1"]


def test_yes_without_key_does_not_call_the_network(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("COMFY_API_KEY", raising=False)
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network")))
    refs = tmp_path / "refs"
    refs.mkdir()
    for name in ("location.png", "person_a.png", "person_b.png"):
        Image.new("RGB", (4, 4), "white").save(refs / name)
    scene_path = tmp_path / "scene.yaml"
    scene_path.write_text(Path(EXAMPLE).read_text(encoding="utf-8"), encoding="utf-8")
    code = main(["start", "--scene", str(scene_path), "--yes", "-n", "1", "--output", str(tmp_path / "out")])
    assert code == 1
    assert "COMFY_API_KEY" in capsys.readouterr().err
