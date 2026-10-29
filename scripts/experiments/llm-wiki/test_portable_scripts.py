"""Check explicit project selection and portable output isolation offline."""

import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import tempfile
import types
import unittest
from unittest.mock import patch

import compile_docs
import compile_stress
import live_agent_stress
import regression
import repair_regression


class PortableScriptTests(unittest.TestCase):
    def test_real_project_scripts_require_explicit_project(self):
        for module in (regression, repair_regression):
            with self.subTest(module=module.__name__):
                argv = [module.__file__, "--output", "/unused"]
                if module is repair_regression:
                    argv.extend(["--stress-root", "/unused-input"])
                with patch("sys.argv", argv), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as caught:
                        module.main()
                self.assertEqual(caught.exception.code, 2)

    def test_catalog_source_required_and_rejects_path_escape_before_docker(self):
        for source in (None, "relative.md", "/data/projects/fixture/../private.md"):
            argv = [compile_docs.__file__]
            if source:
                argv.extend(["--source", source])
            with self.subTest(source=source), patch.dict(os.environ, {}, clear=True):
                with patch("sys.argv", argv), patch.object(compile_docs, "read_source") as read:
                    with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                        compile_docs.main()
                    read.assert_not_called()

    def test_catalog_source_is_forwarded_without_shell_interpolation(self):
        source = "/data/projects/fixture/workspace/knowledge/catalog.md"
        with patch.object(compile_docs.subprocess, "run") as run:
            run.return_value = types.SimpleNamespace(stdout=b"# Synthetic")
            self.assertEqual(compile_docs.read_source("fixture-api", source), "# Synthetic")
        self.assertEqual(run.call_args.args[0], ["docker", "exec", "fixture-api", "cat", source])
        blocks = compile_docs.source_blocks("# Synthetic", source=source)
        self.assertEqual(blocks[0]["source"], source)

    def test_output_root_environment_applies_without_private_project_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = {"compile_docs": ("DEFAULT_OUTPUT", root / "heji"),
                     "compile_stress": ("OUTPUT", root / "stress/compile"),
                     "live_agent_stress": ("OUTPUT_ROOT", root),
                     "regression": ("DEFAULT_OUTPUT", root / "heji/embedding_regression")}
            with patch.dict(os.environ, {"LLM_WIKI_OUTPUT_ROOT": directory}):
                for name, (key, expected) in names.items():
                    values = runpy.run_path(str(Path(__file__).parent / f"{name}.py"))
                    self.assertEqual(values[key], expected)

    def test_configured_root_inside_repository_still_rejected(self):
        repo = Path(__file__).resolve().parents[3]
        target = repo / "forbidden-private-output"
        with patch.object(compile_docs, "DEFAULT_OUTPUT", repo):
            with self.assertRaises(ValueError):
                compile_docs.output_directory(target)
        with patch.object(live_agent_stress, "OUTPUT_ROOT", repo):
            with self.assertRaises(ValueError):
                live_agent_stress.output_path(target, [])
        argv = [compile_stress.__file__, "--output", str(target)]
        with patch.object(compile_stress, "OUTPUT", repo), patch("sys.argv", argv):
            with self.assertRaises(ValueError):
                compile_stress.main()
        self.assertFalse(target.exists())

    def test_synthetic_regression_rejects_wrong_project_before_publishing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "compile").mkdir()
            (root / "chain_cases.json").write_text("[]")
            (root / "compile/cases.json").write_text("[]")
            (root / "chain_retrieval.json").write_text(json.dumps({"project_id": "fixture-a"}))
            output = root / "output"
            argv = [repair_regression.__file__, "--project", "fixture-b",
                    "--stress-root", str(root), "--output", str(output)]
            with patch("sys.argv", argv), patch.object(repair_regression, "publish_snapshot") as publish:
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    repair_regression.main()
                publish.assert_not_called()
            self.assertFalse(output.exists())

    def test_catalog_lifecycle_fixture_still_runs_with_explicit_source(self):
        previous = Path.cwd()
        try:
            with tempfile.TemporaryDirectory() as directory:
                with contextlib.redirect_stdout(io.StringIO()):
                    result = compile_stress.lifecycle_worker("L02", Path(directory))
                checks = {check["name"]: check for check in result["checks"]}
                self.assertIn("Expected 20 catalog pages; found 19", checks["rerun_accepts_changed_page_count"]["error"])
        finally:
            os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
