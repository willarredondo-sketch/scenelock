"""A reviewer used only by tests. It flags; it does not decide."""

from pathlib import Path

from qa.reviewer import ReviewFlag, VisionReviewer


class FlaggingReviewer(VisionReviewer):
    def review(self, video_path: Path, frame_paths: list[Path]) -> list[ReviewFlag]:
        frame = str(frame_paths[0]) if frame_paths else ""
        return [ReviewFlag("extra finger", frame=frame, note="check the full-res grab")]
