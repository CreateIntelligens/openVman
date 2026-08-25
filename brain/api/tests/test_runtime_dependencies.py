import re
from pathlib import Path


def _declared_packages() -> set[str]:
    requirements = Path(__file__).parents[1] / "requirements.txt"
    return {
        re.split(r"[@=<>]", line, maxsplit=1)[0].strip().lower()
        for line in requirements.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def test_lancedb_table_exports_have_lance_dependency_declared():
    assert "pylance" in _declared_packages()


def test_brain_does_not_install_in_process_embedding_providers():
    forbidden = {"flagembedding", "sentence-transformers", "transformers"}

    assert _declared_packages().isdisjoint(forbidden)
