import json
from pathlib import Path

from PIL import Image
import pytest

from scenelock.client import ComfyClient, ComfyError, output_files, status_of, unwrap_history


class Response:
    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status

    def read(self):
        return self._body

    def close(self):
        return None


def test_submit_sends_partner_key_and_workflow():
    captured = {}

    def opener(request, timeout=None):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode())
        captured["key"] = request.get_header("X-api-key")
        return Response(json.dumps({"prompt_id": "pid-1", "node_errors": {}}).encode())

    client = ComfyClient("secret-key", opener=opener)
    assert client.submit({"1": {"class_type": "SaveImage", "inputs": {}}}) == "pid-1"
    assert captured["url"] == "https://cloud.comfy.org/api/prompt"
    assert captured["key"] == "secret-key"
    assert captured["body"]["extra_data"]["api_key_comfy_org"] == "secret-key"
    assert captured["body"]["prompt"]["1"]["class_type"] == "SaveImage"


def test_upload_is_multipart_and_returns_name(tmp_path):
    image = tmp_path / "person.png"
    Image.new("RGB", (8, 8), "red").save(image)
    captured = {}

    def opener(request, timeout=None):
        captured["url"] = request.full_url
        captured["data"] = request.data
        return Response(json.dumps({"name": "abc.png", "subfolder": "", "type": "input"}).encode())

    client = ComfyClient("secret-key", opener=opener)
    assert client.upload_image(image) == "abc.png"
    assert captured["url"].endswith("/api/upload/image")
    assert b'name="image"' in captured["data"]
    assert b'filename="person.png"' in captured["data"]
    assert b"secret-key" not in captured["data"]


def test_history_parser_and_wait():
    payload = {
        "pid": {
            "status": {"status_str": "success", "completed": True},
            "outputs": {
                "4": {"videos": [{"filename": "clip.mp4", "subfolder": "", "type": "output"}]},
                "7": {"images": [{"filename": "still.png", "subfolder": "", "type": "output"}]},
            },
        }
    }
    entry = unwrap_history(payload, "pid")
    assert status_of(entry) == "success"
    names = [item["filename"] for item in output_files(entry)]
    assert names == ["clip.mp4", "still.png"]
    assert status_of({}) == "pending"
    assert unwrap_history({"history": [{"prompt_id": "pid", "status": "completed"}]}, "pid")["status"] == "completed"

    def opener(request, timeout=None):
        assert "/api/history_v2/pid" in request.full_url
        return Response(json.dumps(payload).encode())

    client = ComfyClient("secret-key", opener=opener, poll_interval=0, poll_timeout=5)
    files = client.wait_for_files("pid")
    assert files[0]["filename"] == "clip.mp4"


def test_failed_job_raises():
    def opener(request, timeout=None):
        body = {"pid": {"status": {"status_str": "error", "completed": False}, "outputs": {}}}
        return Response(json.dumps(body).encode())

    client = ComfyClient("secret-key", opener=opener, poll_interval=0, poll_timeout=1)
    with pytest.raises(ComfyError, match="error"):
        client.wait_for_files("pid")


def test_error_text_redacts_the_key():
    def opener(request, timeout=None):
        return Response(b"secret-key leaked", 500)

    client = ComfyClient("secret-key", opener=opener)
    with pytest.raises(ComfyError, match="redacted") as raised:
        client.submit({})
    assert "secret-key" not in str(raised.value)
