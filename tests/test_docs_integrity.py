from pathlib import Path

from scripts.validate_docs import markdown_files, validate


def test_repository_markdown_links_resolve() -> None:
    root = Path(__file__).resolve().parents[1]
    assert markdown_files(root)
    assert validate(root) == []
