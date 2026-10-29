"""Check that a main comparison cannot silently accept an incomplete batch."""

import ast
from dataclasses import dataclass, replace
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import main_wiki_benchmark as benchmark


class MainWikiBenchmarkTests(unittest.TestCase):
    def test_pairs_balance_both_orders_and_reverse_on_repeat(self):
        for index in range(8):
            self.assertEqual(
                benchmark.arm_order(0, index),
                list(reversed(benchmark.arm_order(1, index))),
            )
        self.assertEqual(
            sum(benchmark.arm_order(0, index)[0] == "main" for index in range(8)),
            4,
        )

    def test_missing_duplicates_and_extra_records_never_form_an_accepted_batch(self):
        cases = [{"id":"fixture"}]
        records = [{"id":"fixture", "rep":rep, "variant":arm}
                   for rep in range(2) for arm in ("main", "wiki")]
        data = {"records":records, "config_unchanged":True,
                "readonly_check":{"changed_paths":[]}}
        benchmark.validate_records(data, cases, 2)
        for invalid in (records[:-1], records + records[:1], records[:3] + records[:1]):
            with self.subTest(records=invalid), self.assertRaises(ValueError):
                benchmark.validate_records({**data, "records":invalid}, cases, 2)
        for metadata in ({"config_unchanged":False},
                         {"readonly_check":{"changed_paths":["mutated"]}},
                         {"readonly_check":{}}):
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                benchmark.validate_records({**data, **metadata}, cases, 2)

    def test_module_loader_has_file_metadata_before_executing_source(self):
        tree = ast.parse(benchmark.SCRIPT)
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "module")
        scope = {"types":types, "sys":types.SimpleNamespace(modules={})}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "loader", "exec"), scope)
        loaded = scope["module"]("fixture", "SOURCE_FILE = __file__")
        self.assertEqual(loaded.SOURCE_FILE, loaded.__file__)

    def test_main_knowledge_handler_forwards_original_arguments_without_overrides(self):
        tree = ast.parse(benchmark.SCRIPT)
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and n.name in {"knowledge", "timed_tool"}]
        calls = []
        original = types.SimpleNamespace(handler=lambda args:calls.append(args) or {"original":True})
        scope = {"production_tool":original, "current_arm":"main",
                 "row_metrics":{"knowledge_ms":0, "knowledge_calls":0},
                 "time":types.SimpleNamespace(perf_counter=lambda:1)}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "handlers", "exec"), scope)
        arguments = {"queries":["fixture"], "top_k":7, "future_field":"keep"}
        self.assertEqual(scope["knowledge"](arguments), {"original":True})
        self.assertIs(calls[0], arguments)
        self.assertEqual(scope["row_metrics"]["knowledge_calls"], 1)

    def test_slotted_production_tools_keep_their_original_schema(self):
        @dataclass(frozen=True, slots=True)
        class Tool:
            name: str
            parameters: dict
            handler: object
        original = Tool("fixture", {"required":["queries"]}, lambda args:args)
        product = Tool("products", {"required":["scenarios"]}, lambda args:args)
        tree = ast.parse(benchmark.SCRIPT)
        nodes = [n for n in ast.walk(tree) if isinstance(n, ast.Expr)
                 and isinstance(n.value, ast.Call)
                 and isinstance(n.value.func, ast.Attribute)
                 and isinstance(n.value.func.value, ast.Name)
                 and n.value.func.value.id == "registry"
                 and n.value.func.attr == "register"]
        wrapped = []
        scope = {"production_tool":original, "product":product,
                 "registry":types.SimpleNamespace(register=wrapped.append),
                 "replace":replace, "knowledge":lambda args:args,
                 "timed_tool":lambda name, handler, args:handler(args)}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "registration", "exec"), scope)
        self.assertEqual(len(wrapped), 2)
        for tool, source in zip(wrapped, (original, product)):
            self.assertIs(tool.parameters, source.parameters)
            self.assertEqual(tool.name, source.name)
            self.assertEqual(tool.handler({"unchanged":True}), {"unchanged":True})

    def test_existing_output_rejected_before_main_lookup_or_container(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = root / "cases.json"
            cases.write_text(json.dumps([{"id":"fixture", "q":"question"}]))
            target = root / "result.json"
            target.write_text("preserve")
            argv = [benchmark.__file__, "--project", "fixture", "--cases", str(cases),
                    "--snapshot", str(root / "snapshot"), "--output", str(target)]
            with patch("sys.argv", argv), patch.object(benchmark, "main_sources") as sources, patch.object(benchmark, "output_path", return_value=target):
                with patch.object(benchmark.subprocess, "Popen") as process:
                    with self.assertRaises(SystemExit):
                        benchmark.main()
                    sources.assert_not_called()
                    process.assert_not_called()
            self.assertEqual(target.read_text(), "preserve")


if __name__ == "__main__":
    unittest.main()
