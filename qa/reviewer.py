"""Optional vision-model reviewer.

The default reviewer does nothing. A replacement may flag defects. It must not
decide whether a flag is real: QA_NOTES.md leaves that to a human, because
video-review models invent extra limbs from motion blur.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ReviewFlag:
    claim: str
    frame: str | None = None
    note: str = ""


class VisionReviewer:
    """Interface for a reviewer that only flags."""

    def review(self, video_path: Path, frame_paths: list[Path]) -> list[ReviewFlag]:
        raise NotImplementedError


class DisabledReviewer(VisionReviewer):
    def review(self, video_path: Path, frame_paths: list[Path]) -> list[ReviewFlag]:
        return []


def load_reviewer(dotted: str | None) -> VisionReviewer:
    if not dotted:
        return DisabledReviewer()
    if ":" not in dotted:
        raise ValueError("Reviewer must look like package.module:ClassName")
    module_name, class_name = dotted.split(":", 1)
    module = importlib.import_module(module_name)
    reviewer_cls = getattr(module, class_name)
    reviewer = reviewer_cls()
    if not isinstance(reviewer, VisionReviewer):
        raise TypeError(f"{dotted} must subclass qa.reviewer.VisionReviewer")
    return reviewer
