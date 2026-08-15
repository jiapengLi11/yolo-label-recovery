"""Command-line entry point for the recovery pipeline and report generator."""

from __future__ import annotations

import importlib
import sys

from . import __version__

USAGE = """YOLO Label Recovery

Commands:
  yolo-label-recovery run [pipeline arguments]
  yolo-label-recovery report OUTPUT_ROOT [--output report.html]
  yolo-label-recovery audit DATASET_ROOT [audit options]
  yolo-label-recovery calibrate REVIEWED_CSV --output-dir OUTPUT_DIR
  yolo-label-recovery consensus PRIMARY_CSV VERIFIER_CSV --output-dir OUTPUT_DIR
  yolo-label-recovery cluster DATASET_ROOT --output-dir OUTPUT_DIR
  yolo-label-recovery doctor [--output environment.json]

Examples:
  yolo-label-recovery run --help
  yolo-label-recovery report outputs/run-001
  yolo-label-recovery audit datasets/example --hash-images --check-images
  yolo-label-recovery calibrate reviewed.csv --output-dir calibration
  yolo-label-recovery consensus primary.csv verifier.csv --output-dir consensus
  yolo-label-recovery cluster datasets/example --output-dir near-duplicates
  yolo-label-recovery doctor
"""


def _load_pipeline():
    try:
        return importlib.import_module("autolabel_with_single_class_models")
    except ModuleNotFoundError as error:
        if error.name in {"cv2", "torch", "ultralytics"}:
            raise SystemExit(
                "The 'run' command requires the optional inference dependencies.\n"
                "Install a CUDA-compatible PyTorch build, then run:\n"
                "  python -m pip install -e \".[inference]\""
            ) from error
        raise


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help"}:
        print(USAGE)
        return
    if sys.argv[1] in {"-V", "--version"}:
        print(__version__)
        return

    command = sys.argv[1]
    if command == "run":
        pipeline = _load_pipeline()

        sys.argv = [sys.argv[0], *sys.argv[2:]]
        pipeline.main()
        return

    if command == "report":
        from .report import main as report_main

        report_main(sys.argv[2:])
        return

    if command == "audit":
        from .audit import main as audit_main

        audit_main(sys.argv[2:])
        return

    if command == "calibrate":
        from .calibration import main as calibration_main

        calibration_main(sys.argv[2:])
        return

    if command == "consensus":
        from .consensus import main as consensus_main

        consensus_main(sys.argv[2:])
        return

    if command == "cluster":
        from .near_duplicates import main as cluster_main

        cluster_main(sys.argv[2:])
        return

    if command == "doctor":
        from .runtime import main as doctor_main

        doctor_main(sys.argv[2:])
        return

    raise SystemExit(f"Unknown command: {command}\n\n{USAGE}")


if __name__ == "__main__":
    main()
