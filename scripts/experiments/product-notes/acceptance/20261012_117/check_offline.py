"""Recheck this frozen batch without providers, Docker or live databases."""

import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update-report", action="store_true",
        help="Also regenerate the existing REPORT.md from verified grades",
    )
    args = parser.parse_args()
    steps = [
        ("materialize_snapshot.py", "--self-test"),
        ("freeze_questions.py",),
        ("run_acceptance.py", "--self-test"),
        ("audit_tools.py", "--self-test"),
        ("prepare_grading.py",),
        ("audit_tools.py",),
        ("verify_artifacts.py",),
    ]
    if args.update_report:
        steps.append(("finalize_report.py",))
    for name, *arguments in steps:
        print(f"Checking {name} {' '.join(arguments)}", flush=True)
        subprocess.run(
            [sys.executable, "-B", str(ROOT / name), *arguments],
            cwd=ROOT, check=True,
        )
    print(
        "Offline evidence checks passed (60 answers); "
        "this does not assert answer correctness or live deployment health."
    )


if __name__ == "__main__":
    main()
