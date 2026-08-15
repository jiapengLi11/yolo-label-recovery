import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "autolabel_with_single_class_models.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("autolabel_config", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_model_spec_accepts_relative_path():
    specs = MODULE.parse_model_specs({"person": {"path": "weights/person.pt"}})
    assert specs["person"].path == "weights/person.pt"
    assert specs["person"].pred_class == 0


def test_model_spec_rejects_missing_path():
    try:
        MODULE.parse_model_specs({"person": {"pred_class": 0}})
    except ValueError as error:
        assert "path" in str(error)
    else:
        raise AssertionError("missing model path should fail")
