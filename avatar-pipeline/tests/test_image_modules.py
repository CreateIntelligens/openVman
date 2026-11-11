"""The image copies an allow-list of modules; every documented entry point must be on it."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_documented_modules_are_copied_into_the_image():
    documented = set(re.findall(r"python -m pipeline\.(\w+)", (ROOT / "README.md").read_text(encoding="utf-8")))
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    copied = set(re.findall(r"pipeline/(\w+)\.py", dockerfile))
    assert documented, "README should document at least one entry point"
    assert documented <= copied, f"missing from the image: {sorted(documented - copied)}"
