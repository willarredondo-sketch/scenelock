"""Prompt text for the three stages.

The guardrail sentences are always added. They record lessons from real runs:
keep a held object in one hand, edit the end frame instead of regenerating it,
lock the camera, land the gesture before the last frame, and keep hands off
faces and necks.
"""

from __future__ import annotations

from scenelock.scene import Scene

TABLE_RULE = "Do not add, remove, move, resize or relabel any object."


def build_start_prompt(scene: Scene) -> tuple[str, list[str]]:
    warnings = pose_warnings(scene.start_pose, "start")
    people = " ".join(_person_clause(scene, index, character) for index, character in enumerate(scene.characters, start=2))
    prompt = _normalize(
        f"Photorealistic cinematic still, vertical {scene.aspect_ratio}. "
        f"Two people at {scene.setting}. The location matches reference image 1. "
        f"{people} "
        f"{scene.start_pose} "
        "Nobody is mid-bite, and nobody has both hands on the held object. "
        "Keep the held object in one hand for the whole still and gesture with the free hand. "
        f"Locked table layout: {_lock_list(scene)}. Nothing else on the table. "
        f"{TABLE_RULE} "
        "No alcohol. Faces match the references. Natural anatomy, five separate fingers, "
        "no extra or fused fingers, no duplicate objects. "
        "Static camera, eye-level, medium-wide, from the waist up, full tabletop visible, "
        "room above the heads. Hands stay away from faces and necks. Closed-mouth smiles only."
    )
    return prompt, warnings


def build_end_prompt(scene: Scene) -> tuple[str, list[str]]:
    warnings = pose_warnings(scene.end_pose, "end")
    prompt = _normalize(
        "Edit this photo. Keep the camera, framing, background, lighting, wardrobe, "
        "seating, faces, and identities identical. "
        f"{_seat_line(scene)} Do not swap their seats. "
        "Table must stay identical. "
        f"Locked table layout: {_lock_list(scene)}. {TABLE_RULE} "
        f"Change only poses and expressions: {scene.end_pose} "
        "Each person still holds the same object in the same one hand, low and away from the mouth, "
        "and gestures with the free hand. "
        "A free hand may rest on the other person's upper arm or shoulder, never the neck. "
        "The pose has to be physically reachable in one small motion. "
        "Closed-mouth smiles only; open laughing mouths fuse teeth. "
        "Natural anatomy, five fingers, no extra hands, no alcohol, no new objects."
    )
    return prompt, warnings


def build_video_prompt(scene: Scene) -> tuple[str, list[str]]:
    warnings = pose_warnings(scene.motion_beat, "video")
    prompt = _normalize(
        "Static locked-off camera, no camera movement, no zoom. "
        f"{_seat_line(scene)} They stay in those seats. "
        f"Setting: {scene.setting}. "
        f"Motion: {scene.motion_beat} "
        "The key gesture arrives at about 70% of the clip, then holds still so the end frame matches. "
        "Movements are slow and small. "
        "Each person keeps the held object in the same one hand for the whole clip and gestures with the free hand. "
        "Hands stay away from faces and necks. Closed-mouth smiles only. "
        f"The table stays completely unchanged: {_lock_list(scene)}. "
        "Natural hands with five fingers, no morphing, no extra hands. Faces stay consistent."
    )
    return prompt, warnings


def pose_warnings(text: str, stage: str) -> list[str]:
    """Flag user pose text that fights the guardrails. The prompt still includes both."""
    warnings: list[str] = []
    lowered = text.lower()
    if "mid-bite" in lowered or "mid bite" in lowered or "both hands" in lowered:
        warnings.append(
            f"{stage} pose looks mid-action or uses both hands. Hands melt when the model "
            "has to let go of an object. Keep the object in one hand and gesture with the free hand."
        )
    if "neck" in lowered:
        warnings.append(
            f"{stage} pose mentions the neck. Put the free hand on the upper arm or shoulder."
        )
    if "laugh" in lowered or "open mouth" in lowered or "open-mouth" in lowered:
        warnings.append(
            f"{stage} pose asks for an open mouth. Open laughter fuses teeth. Prefer a closed-mouth smile."
        )
    return warnings


def _person_clause(scene: Scene, reference_index: int, character) -> str:
    free = "right" if character.held_hand == "left" else "left"
    return (
        f"{character.name} (reference image {reference_index}) is on the {character.slot} and holds "
        f"{character.held_object} in the {character.held_hand} hand only, low near the plate, not at the mouth. "
        f"The {free} hand is empty and free to gesture."
    )


def _seat_line(scene: Scene) -> str:
    return " ".join(f"{character.name} stays on the {character.slot}." for character in scene.characters)


def _lock_list(scene: Scene) -> str:
    return "; ".join(scene.table_lock)


def _normalize(text: str) -> str:
    return " ".join(text.split())
