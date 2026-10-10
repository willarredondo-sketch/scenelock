"""Approximate Comfy partner-node credits.

The numbers are the ones we are willing to print before a run. They are not
read from a billing API, and they do not change with resolution. Treat them
as a rough gate, then confirm the balance in the Comfy account.
"""

from __future__ import annotations

from dataclasses import dataclass

# Flat per-image approximation for a Nano Banana Pro / Gemini image node.
IMAGE_CREDITS = 36

# Seedance 1.5 Pro at 720p, no audio. 5s is the 2026-10-10 measured charge.
# 8s is still an approximation. Other durations are interpolated between them.
VIDEO_CREDITS_AT_5S = 27.57
VIDEO_CREDITS_AT_8S = 44

PRICING_NOTE = (
    "Approximate Comfy partner credits. These rates are rough and change. "
    "They are not a quote. Confirm the balance in your Comfy account before you pass --yes."
)


@dataclass(frozen=True)
class CostLine:
    label: str
    count: int
    credits_each: float
    note: str

    @property
    def credits(self) -> float:
        return self.count * self.credits_each


@dataclass(frozen=True)
class CostEstimate:
    lines: tuple[CostLine, ...]

    @property
    def total(self) -> float:
        return sum(line.credits for line in self.lines)

    def format(self) -> str:
        rows = ["Approximate cost (Comfy partner credits):"]
        for line in self.lines:
            rows.append(
                f"  {line.count} x {line.label} ~{format_credits(line.credits_each)} each "
                f"= ~{format_credits(line.credits)} ({line.note})"
            )
        rows.append(f"  Total ~{format_credits(self.total)}")
        rows.append(PRICING_NOTE)
        return "\n".join(rows)


class SpendRequired(RuntimeError):
    """A live submit was requested without --yes."""

    def __init__(self, estimate: CostEstimate):
        super().__init__(estimate.format())
        self.estimate = estimate


def image_line(stage: str, count: int) -> CostLine:
    return CostLine(
        label=f"{stage} frame (Nano Banana Pro image)",
        count=count,
        credits_each=IMAGE_CREDITS,
        note="flat ~36 per image; a 2026-10-10 1K run charged 35.95 and 35.28",
    )


def video_line(duration: int, count: int = 1) -> CostLine:
    credits, note = video_credits(duration)
    return CostLine(
        label=f"video (Seedance 1.5 Pro 720p, {duration}s)",
        count=count,
        credits_each=credits,
        note=note,
    )


def video_credits(duration: int) -> tuple[float, str]:
    if duration == 5:
        return float(VIDEO_CREDITS_AT_5S), "measured 2026-10-10, 720p, no audio"
    if duration == 8:
        return float(VIDEO_CREDITS_AT_8S), "listed approximation for 8s; that run was 5s"
    # Linear between the two listed points. Outside 5-8s this is an extrapolation.
    credits = VIDEO_CREDITS_AT_5S + (duration - 5) * (VIDEO_CREDITS_AT_8S - VIDEO_CREDITS_AT_5S) / 3
    if 5 < duration < 8:
        note = "interpolated between the 5s and 8s approximations"
    else:
        note = "extrapolated from the 5s and 8s approximations"
    return credits, note


def estimate_stage(stage: str, count: int, duration: int) -> CostEstimate:
    if stage == "video":
        return CostEstimate((video_line(duration, count),))
    if stage in {"start", "end"}:
        return CostEstimate((image_line(stage, count),))
    raise ValueError(f"Unknown stage: {stage}")


def estimate_run(start_count: int, end_count: int, duration: int) -> CostEstimate:
    return CostEstimate(
        (
            image_line("start", start_count),
            image_line("end", end_count),
            video_line(duration, 1),
        )
    )


def format_credits(value: float) -> str:
    rounded = round(float(value), 2)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.2f}"
