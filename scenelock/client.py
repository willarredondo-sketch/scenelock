"""Comfy Cloud HTTP client.

Talks to https://cloud.comfy.org with X-API-Key. Submit body matches the runs
that worked: {"prompt": workflow, "extra_data": {"api_key_comfy_org": KEY}}.
Polling uses GET /api/history_v2/{prompt_id}. Downloads use GET /api/view.

This module does not call the network unless you invoke a method. Pass
`opener` in tests.
"""

from __future__ import annotations

import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

DEFAULT_BASE_URL = "https://cloud.comfy.org"
TERMINAL_OK = {"success", "completed"}
TERMINAL_BAD = {"error", "failed", "cancelled"}


class ComfyError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class ComfyClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        opener=None,
        poll_interval: float = 5.0,
        poll_timeout: float = 900.0,
    ):
        key = (api_key or "").strip()
        if not key:
            raise ComfyError("Set COMFY_API_KEY to a Comfy Cloud API key.")
        self.api_key = key
        self.base_url = base_url.rstrip("/")
        self.opener = opener
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout

    @classmethod
    def from_env(cls, **kwargs) -> "ComfyClient":
        return cls(os.environ.get("COMFY_API_KEY", ""), **kwargs)

    def upload_image(self, path: str | Path) -> str:
        file_path = Path(path)
        if not file_path.is_file():
            raise ComfyError(f"Reference image not found: {file_path}")
        _boundary, body, content_type = _multipart_image(file_path)
        payload = self._json(
            "POST",
            "/api/upload/image",
            data=body,
            headers={"Content-Type": content_type},
            timeout=120,
        )
        name = payload.get("name") if isinstance(payload, dict) else None
        if not name:
            raise ComfyError(f"Upload response had no name: {self._scrub(json.dumps(payload)[:400])}")
        return str(name)

    def submit(self, workflow: dict) -> str:
        payload = self._json(
            "POST",
            "/api/prompt",
            json_body={
                "prompt": workflow,
                "extra_data": {"api_key_comfy_org": self.api_key},
            },
            timeout=60,
        )
        if not isinstance(payload, dict):
            raise ComfyError("Prompt response was not a JSON object")
        errors = payload.get("node_errors") or {}
        if errors:
            raise ComfyError(f"Prompt rejected: {self._scrub(json.dumps(errors)[:800])}")
        prompt_id = payload.get("prompt_id")
        if not prompt_id:
            raise ComfyError(f"Prompt response had no prompt_id: {self._scrub(json.dumps(payload)[:400])}")
        return str(prompt_id)

    def history(self, prompt_id: str) -> tuple[int, dict]:
        return self._json_status("GET", f"/api/history_v2/{urllib.parse.quote(prompt_id)}", timeout=30)

    def wait_for_files(self, prompt_id: str) -> list[dict]:
        deadline = time.monotonic() + self.poll_timeout
        last_state = "pending"
        while True:
            status, payload = self.history(prompt_id)
            if status == 404 or not payload:
                last_state = "pending"
            else:
                entry = unwrap_history(payload, prompt_id)
                last_state = status_of(entry)
                if last_state in TERMINAL_OK:
                    files = output_files(entry)
                    if not files:
                        raise ComfyError(
                            "Job finished but history listed no output files. "
                            "The outputs object may use a key this client does not read yet."
                        )
                    return files
                if last_state in TERMINAL_BAD:
                    raise ComfyError(f"Job {prompt_id} {last_state}: {self._scrub(json.dumps(entry)[:800])}")
            if time.monotonic() >= deadline:
                raise ComfyError(f"Timed out after {int(self.poll_timeout)}s waiting for {prompt_id} ({last_state})")
            time.sleep(self.poll_interval)

    def download(self, item: dict, dest: Path) -> Path:
        query = urllib.parse.urlencode(
            {
                "filename": item.get("filename", ""),
                "subfolder": item.get("subfolder") or "",
                "type": item.get("type") or "output",
            }
        )
        dest.parent.mkdir(parents=True, exist_ok=True)
        raw = self._bytes("GET", f"/api/view?{query}", timeout=120)
        dest.write_bytes(raw)
        return dest

    def _json(self, method: str, path: str, json_body: dict | None = None, data: bytes | None = None, headers: dict | None = None, timeout: float = 60):
        status, payload = self._json_status(method, path, json_body=json_body, data=data, headers=headers, timeout=timeout, ok=(200,))
        return payload

    def _json_status(
        self,
        method: str,
        path: str,
        json_body: dict | None = None,
        data: bytes | None = None,
        headers: dict | None = None,
        timeout: float = 60,
        ok: tuple[int, ...] = (200,),
    ) -> tuple[int, dict]:
        raw, status = self._read(method, path, json_body=json_body, data=data, headers=headers, timeout=timeout)
        if status not in ok:
            raise ComfyError(f"{method} {path} failed ({status}): {self._scrub(raw[:800].decode(errors='replace'))}", status)
        if not raw:
            return status, {}
        try:
            parsed = json.loads(raw.decode())
        except json.JSONDecodeError as exc:
            raise ComfyError(f"{method} {path} returned non-JSON ({status})") from exc
        if not isinstance(parsed, dict):
            raise ComfyError(f"{method} {path} returned JSON that was not an object")
        return status, parsed

    def _bytes(self, method: str, path: str, timeout: float) -> bytes:
        raw, status = self._read(method, path, timeout=timeout)
        if status != 200:
            raise ComfyError(f"{method} {path} failed ({status}): {self._scrub(raw[:400].decode(errors='replace'))}", status)
        return raw

    def _read(
        self,
        method: str,
        path: str,
        json_body: dict | None = None,
        data: bytes | None = None,
        headers: dict | None = None,
        timeout: float = 60,
    ) -> tuple[bytes, int]:
        body = data
        header_map = {"X-API-Key": self.api_key}
        if json_body is not None:
            body = json.dumps(json_body).encode()
            header_map["Content-Type"] = "application/json"
        if headers:
            header_map.update(headers)
        request = urllib.request.Request(self.base_url + path, data=body, headers=header_map, method=method)
        opener = self.opener or urllib.request.urlopen
        try:
            response = opener(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            return raw, exc.code
        try:
            raw = response.read()
            status = getattr(response, "status", None) or getattr(response, "code", 200)
        finally:
            close = getattr(response, "close", None)
            if close:
                close()
        return raw, int(status)

    def _scrub(self, text: str) -> str:
        if self.api_key:
            return text.replace(self.api_key, "[redacted]")
        return text


def unwrap_history(payload: dict, prompt_id: str) -> dict:
    """Accept the prompt-id map, a bare entry, or a history list."""
    if not isinstance(payload, dict) or not payload:
        return {}
    wrapped = payload.get(prompt_id)
    if isinstance(wrapped, dict):
        return wrapped
    if "outputs" in payload or "status" in payload:
        return payload
    history = payload.get("history")
    if isinstance(history, list):
        for item in history:
            if isinstance(item, dict) and str(item.get("prompt_id")) == str(prompt_id):
                return item
        return {}
    if len(payload) == 1:
        only = next(iter(payload.values()))
        if isinstance(only, dict) and ("outputs" in only or "status" in only):
            return only
    return {}


def status_of(entry: dict) -> str:
    if not entry:
        return "pending"
    status = entry.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip().lower()
    if isinstance(status, dict):
        label = status.get("status_str") or status.get("status")
        if isinstance(label, str) and label.strip():
            return label.strip().lower()
        if status.get("completed") is True:
            return "success"
    if entry.get("outputs"):
        return "success"
    return "pending"


def output_files(entry: dict) -> list[dict]:
    files: list[dict] = []
    outputs = entry.get("outputs") or {}
    if not isinstance(outputs, dict):
        return files
    for node in outputs.values():
        if not isinstance(node, dict):
            continue
        for key in ("images", "videos", "gifs"):
            items = node.get(key) or []
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict) and item.get("filename"):
                    files.append(item)
    return files


def _multipart_image(path: Path) -> tuple[str, bytes, str]:
    filename = path.name.replace('"', "").replace("\r", "").replace("\n", "")
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    boundary = "----SceneLock" + uuid.uuid4().hex
    chunk = bytearray()
    chunk.extend(f"--{boundary}\r\n".encode())
    chunk.extend(
        f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'.encode()
    )
    chunk.extend(f"Content-Type: {mime}\r\n\r\n".encode())
    chunk.extend(path.read_bytes())
    chunk.extend(b"\r\n")
    chunk.extend(f"--{boundary}--\r\n".encode())
    return boundary, bytes(chunk), f"multipart/form-data; boundary={boundary}"
