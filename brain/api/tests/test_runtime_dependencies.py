import re
from pathlib import Path


def test_lancedb_table_exports_have_lance_dependency_declared():
    requirements = Path(__file__).parents[1] / "requirements.txt"

    declared_packages = {
        re.split(r"[@=<>]", line, maxsplit=1)[0].strip().lower()
        for line in requirements.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "pylance" in declared_packages
