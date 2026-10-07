"""Fill ComfyUI API-format workflow templates."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / "workflows"

PLACEHOLDER = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
INT_FIELDS = {"seed", "duration"}


class TemplateError(ValueError):
    """A workflow template still has an empty placeholder, or a value is missing."""


def load_template(name: str) -> dict:
    path = WORKFLOWS / name
    if not path.is_file():
        raise TemplateError(f"Missing workflow template: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def fill_workflow(template: dict, values: dict) -> dict:
    """Replace {{PLACEHOLDER}} tokens. seed and duration become integers."""
    missing: set[str] = set()

    def convert(key: str | None, text: str):
        if key in INT_FIELDS and re.fullmatch(r"-?\d+", text):
            return int(text)
        return text

    def replace(text: str) -> str:
        def repl(match: re.Match) -> str:
            name = match.group(1)
            if name not in values:
                missing.add(name)
                return match.group(0)
            return str(values[name])

        return PLACEHOLDER.sub(repl, text)

    def walk(node, key: str | None = None):
        if isinstance(node, dict):
            return {child_key: walk(child, child_key) for child_key, child in node.items()}
        if isinstance(node, list):
            return [walk(child, key) for child in node]
        if isinstance(node, str):
            return convert(key, replace(node))
        return node

    filled = walk(template)
    if missing:
        raise TemplateError(f"Missing placeholder values: {', '.join(sorted(missing))}")
    leftover = PLACEHOLDER.findall(json.dumps(filled))
    if leftover:
        raise TemplateError(f"Unfilled placeholders: {', '.join(sorted(set(leftover)))}")
    return filled
