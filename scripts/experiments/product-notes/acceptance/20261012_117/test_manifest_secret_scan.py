"""Ensure manifest hash exceptions do not suppress credential detection."""

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[4]
PREFIX = "scripts/experiments/product-notes/acceptance/20261012_117/"


def main():
    # Generated test strings avoid embedding credential-shaped literals in Git.
    sample = hashlib.sha256(b"manifest secret scan fixture").hexdigest()
    manifest = f'  "brain/api/core/key_pool.py": "{sample}",\n'
    credential = f'  "api_key": "{sample}",\n'
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        cases = {
            PREFIX + "results.json": manifest + credential,
            PREFIX + "probe2_results.json": manifest + credential,
            PREFIX + "other.json": manifest,
        }
        for relative, content in cases.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        report = root / "findings.json"
        result = subprocess.run(
            ["gitleaks", "dir", ".", "--config", str(REPO / ".gitleaks.toml"),
             "--redact", "--no-banner", "--report-format", "json",
             "--report-path", str(report)],
            cwd=root, capture_output=True, text=True,
        )
        if result.returncode != 1 or not report.exists():
            raise RuntimeError("Expected fixture detection; check Gitleaks setup")
        findings = json.loads(report.read_text())
        actual = {
            (row["File"].removeprefix("./"), row["StartLine"], row["RuleID"])
            for row in findings
        }
        expected = {
            (PREFIX + "results.json", 2, "generic-api-key"),
            (PREFIX + "probe2_results.json", 2, "generic-api-key"),
            (PREFIX + "other.json", 1, "generic-api-key"),
        }
        assert len(findings) == 3 and actual == expected, (
            "Manifest exception must require both exact file and hash line"
        )
    print("Secret scan fixtures passed: hash exceptions scoped; keys detected")


if __name__ == "__main__":
    main()
