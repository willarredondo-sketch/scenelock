"""Command line for SceneLock."""

from __future__ import annotations

import argparse
import sys

from scenelock import __version__
from scenelock.client import ComfyError
from scenelock.cost import SpendRequired
from scenelock.pipeline import ledger_text, run_end, run_pipeline, run_start, run_video
from scenelock.scene import SceneError, load_scene, output_dir_for
from scenelock.templates import TemplateError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scenelock",
        description="Build locked start and end frames, then a short clip between them.",
    )
    parser.add_argument("--version", action="version", version=f"scenelock {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="Generate N start-frame variations")
    _add_common(start)
    start.add_argument("-n", "--count", type=int, default=4, help="How many seeds to run")

    end = sub.add_parser("end", help="Edit the chosen start frame into N end frames")
    _add_common(end)
    end.add_argument("--start", required=True, help="Chosen start frame (local file)")
    end.add_argument("-n", "--count", type=int, default=2)

    video = sub.add_parser("video", help="Animate between a start frame and an end frame")
    _add_common(video)
    video.add_argument("--start", required=True, help="Start frame (local file)")
    video.add_argument("--end", required=True, help="End frame (local file)")

    qa_cmd = sub.add_parser("qa", help="Grab frames, build a contact sheet, and write QA_NOTES.md")
    qa_cmd.add_argument("--scene", required=True)
    qa_cmd.add_argument("--video", required=True)
    qa_cmd.add_argument("--start", required=True)
    qa_cmd.add_argument("--end", required=True)
    qa_cmd.add_argument("--interval", type=float, default=1.0, help="Seconds between frame grabs")
    qa_cmd.add_argument("--output", default=None)
    qa_cmd.add_argument(
        "--reviewer",
        default=None,
        help="Optional dotted path module:Class. Off when omitted. The reviewer only flags.",
    )

    run = sub.add_parser("run", help="Run every stage. Pauses to pick a start and an end.")
    _add_common(run)
    run.add_argument("-n", "--count", type=int, default=4)
    run.add_argument("--auto-pick", action="store_true", help="Use the first variation of each stage")
    run.add_argument("--reviewer", default=None)

    dashboard = sub.add_parser("dashboard", help="Open the local dashboard")
    dashboard.add_argument("--port", type=int, default=7860)
    dashboard.add_argument("--host", default="127.0.0.1")

    args = parser.parse_args(argv)
    try:
        return _dispatch(args)
    except SpendRequired as exc:
        print(exc.estimate.format())
        print("Re-run with --yes to spend. Nothing was submitted.")
        return 2
    except (SceneError, ComfyError, TemplateError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "dashboard":
        from app.dashboard import main as dashboard_main

        dashboard_main(host=args.host, port=args.port)
        return 0

    scene = load_scene(args.scene)
    output = args.output
    if args.command == "qa":
        from qa.check import run_qa

        destination = output_dir_for(scene, output) / "qa" if output is None else output
        report = run_qa(
            scene,
            args.video,
            args.start,
            args.end,
            destination,
            interval=args.interval,
            reviewer_path=args.reviewer,
        )
        print(f"Wrote {report.notes_path}")
        return 0
    if args.command == "start":
        result = run_start(scene, args.count, args.dry_run, args.yes, output)
    elif args.command == "end":
        result = run_end(scene, args.start, args.count, args.dry_run, args.yes, output)
    elif args.command == "video":
        result = run_video(scene, args.start, args.end, args.dry_run, args.yes, output)
    elif args.command == "run":
        result = run_pipeline(
            scene,
            args.count,
            args.dry_run,
            args.yes,
            args.auto_pick,
            output,
            reviewer=args.reviewer,
        )
    else:
        raise SceneError(f"Unknown command {args.command}")
    print(result.render())
    if args.command != "run" or not args.dry_run:
        print(ledger_text(output_dir_for(scene, output)))
    return 0


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--scene", required=True, help="Path to a scene YAML file")
    parser.add_argument("--output", default=None, help="Output directory (default outputs/<scene-slug>)")
    parser.add_argument("--dry-run", action="store_true", help="Print the filled workflows and do not call the API")
    parser.add_argument("--yes", action="store_true", help="Submit the job and spend Comfy credits")
