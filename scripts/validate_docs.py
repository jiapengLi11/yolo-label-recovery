"""Validate repository-local Markdown links and image references."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
HTML_SRC_RE = re.compile(r"(?:src|href)=[\"']([^\"']+)[\"']")
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "tel:", "data:")


def markdown_files(root: Path) -> list[Path]:
    files = list(root.glob("*.md"))
    files.extend((root / "docs").rglob("*.md"))
    files.extend((root / "platform").rglob("*.md"))
    ignored_parts = {"node_modules", "target", "dist", ".git"}
    return sorted(path for path in files if path.is_file() and not ignored_parts.intersection(path.parts))


def strip_code_fences(text: str) -> str:
    parts = text.split("```")
    return "".join(part for index, part in enumerate(parts) if index % 2 == 0)


def local_targets(path: Path) -> list[str]:
    text = strip_code_fences(path.read_text(encoding="utf-8"))
    return [*LINK_RE.findall(text), *HTML_SRC_RE.findall(text)]


def resolve_target(source: Path, raw: str) -> Path | None:
    target = raw.strip().strip("<>")
    if not target or target.startswith("#") or target.lower().startswith(EXTERNAL_PREFIXES):
        return None
    target = unquote(target.split("#", 1)[0].split("?", 1)[0])
    if not target:
        return None
    return (source.parent / target).resolve()


def validate(root: Path) -> list[str]:
    failures: list[str] = []
    for source in markdown_files(root):
        for raw in local_targets(source):
            target = resolve_target(source, raw)
            if target is not None and not target.exists():
                failures.append(f"{source.relative_to(root)} -> {raw}")
    return failures


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    failures = validate(root)
    if failures:
        print("Broken repository-local documentation links:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"Documentation links OK across {len(markdown_files(root))} Markdown files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
