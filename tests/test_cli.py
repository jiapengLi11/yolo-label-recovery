from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from yolo_label_recovery import cli


def test_load_pipeline_explains_optional_inference_dependencies(monkeypatch):
    def missing_pipeline(_name):
        raise ModuleNotFoundError("No module named 'ultralytics'", name="ultralytics")

    monkeypatch.setattr(cli.importlib, "import_module", missing_pipeline)

    with pytest.raises(SystemExit, match=r"\[inference\]"):
        cli._load_pipeline()


def test_load_pipeline_returns_imported_module(monkeypatch):
    pipeline = SimpleNamespace(main=lambda: None)
    monkeypatch.setattr(cli.importlib, "import_module", lambda _name: pipeline)

    assert cli._load_pipeline() is pipeline


def test_top_level_help_lists_model_free_analysis_commands(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["yolo-label-recovery", "--help"])

    cli.main()

    output = capsys.readouterr().out
    assert "consensus PRIMARY_CSV VERIFIER_CSV" in output
    assert "cluster DATASET_ROOT" in output
