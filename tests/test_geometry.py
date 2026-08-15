import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "autolabel_with_single_class_models.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("autolabel", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_iou_for_identical_boxes_is_one():
    box = MODULE.Box(0, 0.5, 0.5, 0.2, 0.2)
    assert MODULE.iou(box, box) == 1.0


def test_iou_for_non_overlapping_boxes_is_zero():
    left = MODULE.Box(0, 0.2, 0.5, 0.1, 0.1)
    right = MODULE.Box(0, 0.8, 0.5, 0.1, 0.1)
    assert MODULE.iou(left, right) == 0.0


def test_threshold_override_is_class_specific():
    thresholds = MODULE.parse_thresholds(["smoking:0.70:0.45"])
    assert thresholds["smoking"] == (0.70, 0.45)
    assert thresholds["person"] == MODULE.DEFAULT_THRESHOLDS["person"]
