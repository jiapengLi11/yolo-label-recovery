"""Run dependency-light checks without requiring pytest."""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
from yolo_label_recovery.state import build_run_signature, load_state, new_state, save_state

SCRIPT = ROOT / "autolabel_with_single_class_models.py"
SPEC = importlib.util.spec_from_file_location("autolabel_smoke", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class CoreChecks(unittest.TestCase):
    def test_iou(self):
        box = MODULE.Box(0, 0.5, 0.5, 0.2, 0.2)
        self.assertEqual(MODULE.iou(box, box), 1.0)
        left = MODULE.Box(0, 0.2, 0.5, 0.1, 0.1)
        right = MODULE.Box(0, 0.8, 0.5, 0.1, 0.1)
        self.assertEqual(MODULE.iou(left, right), 0.0)

    def test_threshold_override(self):
        thresholds = MODULE.parse_thresholds(["smoking:0.70:0.45"])
        self.assertEqual(thresholds["smoking"], (0.70, 0.45))
        self.assertEqual(thresholds["person"], MODULE.DEFAULT_THRESHOLDS["person"])

    def test_model_spec(self):
        specs = MODULE.parse_model_specs({"person": {"path": "weights/person.pt"}})
        self.assertEqual(specs["person"].pred_class, 0)
        with self.assertRaises(ValueError):
            MODULE.parse_model_specs({"person": {"pred_class": 0}})

    def test_atomic_state_round_trip(self):
        signature = build_run_signature({"dataset": "demo", "batch": 32})
        state = new_state(signature, {"person": {"auto_added": 0}})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            save_state(path, state)
            self.assertEqual(load_state(path, signature), state)

    def test_resume_writes_are_idempotent(self):
        candidate = MODULE.Candidate(
            split="train",
            image=Path("demo.jpg"),
            label=Path("demo.txt"),
            class_name="person",
            class_id=0,
            conf=0.9,
            box=MODULE.Box(0, 0.5, 0.5, 0.2, 0.4, 0.9),
            mode="auto",
            max_iou_same_class=0.1,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            writer = MODULE.CandidateWriter(root, ["person"], 0, 0)
            self.assertTrue(writer.write(candidate))
            writer.close()
            writer = MODULE.CandidateWriter(root, ["person"], 0, 0, resume=True)
            self.assertFalse(writer.write(candidate))
            writer.close()
            rows = (root / "candidates_all.csv").read_text(encoding="utf-8-sig").splitlines()
            self.assertEqual(len(rows), 2)

            labels = root / "labels"
            MODULE.append_batch_labels(labels, [candidate])
            MODULE.append_batch_labels(labels, [candidate])
            label_rows = (labels / "train" / "demo.txt").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(label_rows), 1)


if __name__ == "__main__":
    unittest.main()
