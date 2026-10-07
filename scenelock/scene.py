"""Load a SceneLock scene YAML file."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_IMAGE_MODEL = "gemini-3-pro-image-preview"
DEFAULT_VIDEO_MODEL = "seedance-1-5-pro-251215"


class SceneError(ValueError):
    """The scene file is missing a field or breaks a v0.1 rule."""


@dataclass
class Character:
    name: str
    image: Path
    slot: str
    held_object: str
    held_hand: str


@dataclass
class Scene:
    title: str
    setting: str
    location_image: Path
    characters: list[Character]
    table_lock: list[str]
    start_pose: str
    end_pose: str
    motion_beat: str
    duration: int
    aspect_ratio: str
    image_resolution: str
    video_resolution: str
    image_model: str
    video_model: str
    table_bbox: tuple[int, int, int, int] | None
    seeds: dict[str, list[int]]
    source: Path | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def slug(self) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", self.title.lower()).strip("-")
        return slug or "scene"


def load_scene(source: str | Path | dict, base_dir: Path | None = None) -> Scene:
    """Parse a scene from a YAML path or an already-loaded mapping."""
    origin: Path | None = None
    if isinstance(source, dict):
        data = source
        base = Path(base_dir) if base_dir else Path.cwd()
    else:
        origin = Path(source)
        base = origin.parent if base_dir is None else Path(base_dir)
        loaded = yaml.safe_load(origin.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise SceneError("Scene file must be a YAML mapping")
        data = loaded
    scene = scene_from_mapping(data, base)
    scene.source = origin
    return scene


def scene_from_mapping(data: dict, base_dir: Path) -> Scene:
    if not isinstance(data, dict):
        raise SceneError("Scene must be a mapping")

    title = _text(data, "title")
    setting = _text(data, "setting")
    start_pose = _text(data, "start_pose")
    end_pose = _text(data, "end_pose")
    motion_beat = _text(data, "motion_beat")
    raw_aspect = data.get("aspect_ratio", "9:16")
    if not isinstance(raw_aspect, str) or not raw_aspect.strip():
        raise SceneError('aspect_ratio must be a quoted string such as "9:16"')
    aspect_ratio = raw_aspect.strip()
    image_resolution = str(data.get("image_resolution") or "1K").strip()
    video_resolution = str(data.get("video_resolution") or "720p").strip()
    image_model = str(data.get("image_model") or DEFAULT_IMAGE_MODEL).strip()
    video_model = str(data.get("video_model") or DEFAULT_VIDEO_MODEL).strip()

    try:
        duration = int(data.get("duration"))
    except (TypeError, ValueError) as exc:
        raise SceneError("duration must be an integer number of seconds") from exc
    if duration < 4 or duration > 12:
        raise SceneError("duration must be between 4 and 12 seconds for this video node")

    refs = data.get("refs") or {}
    if not isinstance(refs, dict) or not refs.get("location"):
        raise SceneError("refs.location is required (path to the location photo)")
    location_image = _resolve(base_dir, refs["location"])

    raw_characters = data.get("characters")
    if not isinstance(raw_characters, list):
        raise SceneError("characters must be a list")
    if len(raw_characters) != 2:
        raise SceneError(
            "v0.1 expects exactly two characters. The start-frame graph loads "
            "a location photo plus two people."
        )
    characters = [_character(item, base_dir, index) for index, item in enumerate(raw_characters, start=1)]
    slots = [character.slot for character in characters]
    if sorted(slots) != ["left", "right"]:
        raise SceneError("One character must sit on the left and the other on the right")

    table_lock = _table_lock(data.get("table_lock"))
    table_bbox = _bbox(data.get("table_bbox"))
    seeds = _seeds(data.get("seeds") or {})

    warnings: list[str] = []
    if duration < 6 or duration > 8:
        warnings.append(
            f"Duration is {duration}s. The pipeline is aimed at 6-8 second clips."
        )

    return Scene(
        title=title,
        setting=setting,
        location_image=location_image,
        characters=characters,
        table_lock=table_lock,
        start_pose=start_pose,
        end_pose=end_pose,
        motion_beat=motion_beat,
        duration=duration,
        aspect_ratio=aspect_ratio,
        image_resolution=image_resolution,
        video_resolution=video_resolution,
        image_model=image_model,
        video_model=video_model,
        table_bbox=table_bbox,
        seeds=seeds,
        warnings=warnings,
    )


def output_dir_for(scene: Scene, override: str | Path | None) -> Path:
    if override:
        return Path(override)
    return Path("outputs") / scene.slug


def _character(item: dict, base_dir: Path, index: int) -> Character:
    if not isinstance(item, dict):
        raise SceneError(f"Character {index} must be a mapping")
    name = str(item.get("name") or "").strip()
    if not name:
        raise SceneError(f"Character {index} needs a name")
    if not item.get("image"):
        raise SceneError(f"{name} needs an image path")
    slot = str(item.get("slot") or "").strip().lower()
    if slot not in {"left", "right"}:
        raise SceneError(f"{name} slot must be left or right")
    held_hand = str(item.get("held_hand") or "").strip().lower()
    if held_hand not in {"left", "right"}:
        raise SceneError(f"{name} held_hand must be left or right")
    held_object = str(item.get("held_object") or "").strip()
    if not held_object:
        raise SceneError(
            f"{name} needs held_object. The clip keeps that object in one hand "
            "and gestures with the free hand."
        )
    return Character(
        name=name,
        image=_resolve(base_dir, item["image"]),
        slot=slot,
        held_object=held_object,
        held_hand=held_hand,
    )


def _table_lock(value) -> list[str]:
    if isinstance(value, str):
        items = [line.strip(" -*\t") for line in value.splitlines()]
    elif isinstance(value, list):
        items = [str(item).strip() for item in value]
    else:
        raise SceneError("table_lock must be a list of props to keep fixed")
    items = [item for item in items if item]
    if not items:
        raise SceneError("table_lock needs at least one prop")
    return items


def _bbox(value) -> tuple[int, int, int, int] | None:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise SceneError("table_bbox must be [x, y, width, height] in start-frame pixels, or null")
    try:
        box = tuple(int(part) for part in value)
    except (TypeError, ValueError) as exc:
        raise SceneError("table_bbox values must be integers") from exc
    if box[2] <= 0 or box[3] <= 0:
        raise SceneError("table_bbox width and height must be positive")
    return box  # type: ignore[return-value]


def _seeds(value: dict) -> dict[str, list[int]]:
    if not isinstance(value, dict):
        raise SceneError("seeds must be a mapping of start, end, and video lists")
    parsed: dict[str, list[int]] = {}
    for stage in ("start", "end", "video"):
        raw = value.get(stage) or []
        if not isinstance(raw, list):
            raise SceneError(f"seeds.{stage} must be a list of integers")
        try:
            parsed[stage] = [int(seed) for seed in raw]
        except (TypeError, ValueError) as exc:
            raise SceneError(f"seeds.{stage} must be integers") from exc
    return parsed


def _text(data: dict, key: str) -> str:
    value = data.get(key)
    if value is None or not str(value).strip():
        raise SceneError(f"{key} is required")
    return str(value).strip()


def _resolve(base_dir: Path, value) -> Path:
    path = Path(str(value))
    if not path.is_absolute():
        path = base_dir / path
    return path


def seeds_for(scene: Scene, stage: str, count: int) -> list[int]:
    """Take the scene's seeds, then keep counting by 10 until `count` is filled."""
    if count < 1:
        raise SceneError("count must be at least 1")
    chosen = list(scene.seeds.get(stage) or [])
    defaults = {"start": 61001, "end": 62001, "video": 64001}
    cursor = chosen[-1] if chosen else defaults[stage] - 10
    while len(chosen) < count:
        cursor += 10
        chosen.append(cursor)
    return chosen[:count]
