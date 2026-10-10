"""Letterbox character photos onto the location canvas.

ComfyUI's ImageBatch centre-crops every later image to the first image's size.
A tall portrait batched after a wider location photo loses the top and bottom,
which is where a face often sits. Fitting keeps the whole portrait, including
the face, and pads the leftover canvas instead of cropping.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PIL import Image

from scenelock.scene import Scene


def fit_character_refs(scene: Scene, directory: Path) -> Scene:
    """Return a scene whose character images match the location size.

    If any reference file is missing, the scene is unchanged so a dry-run of
    the photo-less example still works.
    """
    paths = [scene.location_image, *[character.image for character in scene.characters]]
    if not all(path.is_file() for path in paths):
        return scene
    with Image.open(scene.location_image) as location:
        canvas_size = location.convert("RGB").size
    directory.mkdir(parents=True, exist_ok=True)
    fitted = []
    for character in scene.characters:
        dest = directory / character.image.name
        _fit_onto(character.image, canvas_size, dest)
        fitted.append(replace(character, image=dest))
    return replace(scene, characters=fitted)


def _fit_onto(source_path: Path, canvas_size: tuple[int, int], dest: Path) -> None:
    with Image.open(source_path) as source:
        image = source.convert("RGB")
    canvas_w, canvas_h = canvas_size
    scale = min(canvas_w / image.width, canvas_h / image.height)
    fitted_w = max(1, int(round(image.width * scale)))
    fitted_h = max(1, int(round(image.height * scale)))
    resized = image.resize((fitted_w, fitted_h), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", canvas_size, (0, 0, 0))
    left = (canvas_w - fitted_w) // 2
    top = (canvas_h - fitted_h) // 2
    canvas.paste(resized, (left, top))
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest)
