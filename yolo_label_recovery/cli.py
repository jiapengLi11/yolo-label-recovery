"""Command-line entry point for the recovery pipeline and report generator."""

from __future__ import annotations

import sys

from . import __version__

USAGE = """YOLO Label Recovery

Commands:
  yolo-label-recovery run [pipeline arguments]
  yolo-label-recovery report OUTPUT_ROOT [--output report.html]
  yolo-label-recovery audit DATASET_ROOT [audit options]
  yolo-label-recovery doctor [--output environment.json]

Examples:
  yolo-label-recovery run --help
  yolo-label-recovery report outputs/run-001
  yolo-label-recovery audit datasets/example --hash-images --check-images
  yolo-label-recovery doctor
"""


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help"}:
        print(USAGE)
        return
    if sys.argv[1] in {"-V", "--version"}:
        print(__version__)
        return

    command = sys.argv[1]
    if command == "run":
        import autolabel_with_single_class_models as pipeline

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

    if command == "doctor":
        from .runtime import main as doctor_main

        doctor_main(sys.argv[2:])
        return

    raise SystemExit(f"Unknown command: {command}\n\n{USAGE}")


if __name__ == "__main__":
    main()
