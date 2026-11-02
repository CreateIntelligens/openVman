"""Check that a main comparison cannot silently accept an incomplete batch."""

import ast
from dataclasses import dataclass, replace
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

import ablation_matrix as matrix
import main_wiki_benchmark as benchmark
import pipeline_matrix
import stage_profiler


class MainWikiBenchmarkTests(unittest.TestCase):
    def test_noise_control_uses_production_handler_and_identical_product_tools(self):
        from unittest.mock import Mock

        tree = ast.parse(benchmark.SCRIPT)
        handler = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                       and n.name == "knowledge")
        production = Mock(return_value="production result")
        raw = Mock(return_value="raw result")
        scope = {"p": {"pipelines": True}, "pipeline_arms": pipeline_matrix.CLEAN_INDEX_ARMS,
                 "production_tool": types.SimpleNamespace(handler=production),
                 "pipeline": types.SimpleNamespace(search=raw),
                 "timed_tool": lambda label, fn, args: fn(args)}
        exec(compile(ast.Module(body=[handler], type_ignores=[]), "clean routing", "exec"), scope)
        arguments = {"queries": ["synthetic"]}
        for arm in ("main", "main_noise"):
            scope["current_arm"] = arm
            self.assertEqual(scope["knowledge"](arguments), "production result")
        self.assertEqual(production.call_count, 2)
        self.assertEqual(production.call_args.args[0], arguments)
        raw.assert_not_called()
        for arm, options in pipeline_matrix.CLEAN_INDEX_ARMS.items():
            self.assertTrue(arm == "main" or options.get("products"))
        self.assertEqual(pipeline_matrix.CLEAN_INDEX_ARMS['raw_multi']['banks'], ['raw'])

    def test_catalog_cache_never_changes_the_main_control_or_hides_invalidations(self):
        from unittest.mock import Mock

        node = next(n for n in ast.walk(ast.parse(benchmark.SCRIPT))
                    if isinstance(n, ast.FunctionDef) and n.name == "catalog_for_request")
        original = Mock(return_value="formal catalog")
        cached = Mock(return_value="verified copy")
        scope = {
            "p":{"pipelines":True}, "current_arm":"main",
            "pipeline_arms":{"main":{}, "guarded":{}, "cached":{"catalog_cache":True}},
            "load_product_catalog":original,
            "verified_catalog":types.SimpleNamespace(load=cached),
            "timed_tool":lambda name, function, value:function(value),
        }
        exec(compile(ast.Module(body=[node], type_ignores=[]), "catalog scope", "exec"), scope)
        for arm in ("main", "guarded"):
            scope["current_arm"] = arm
            self.assertEqual(scope["catalog_for_request"]("fixture"), "formal catalog")
        cached.assert_not_called()
        scope["current_arm"] = "cached"
        self.assertEqual(scope["catalog_for_request"]("fixture"), "verified copy")
        cached.side_effect = RuntimeError("catalog changed")
        with self.assertRaisesRegex(RuntimeError, "catalog changed"):
            scope["catalog_for_request"]("fixture")
        self.assertEqual(original.call_count, 2)

    def test_container_exit_before_input_keeps_failure_and_empty_checkpoint(self):
        class ClosedInput:
            def write(self, value):
                raise BrokenPipeError("synthetic stopped container")

            def close(self):
                pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = root / "cases.json"
            cases.write_text(json.dumps([{"id":"fixture", "q":"question"}]))
            generation = root / "generation"
            generation.mkdir()
            target = root / "result.json"
            process = types.SimpleNamespace(
                stdin=ClosedInput(), stdout=[],
                stderr=io.StringIO("container is not running"), wait=lambda:1,
            )
            argv = [benchmark.__file__, "--project", "fixture", "--cases", str(cases),
                    "--snapshot", str(generation), "--output", str(target)]
            with (
                patch("sys.argv", argv),
                patch.object(benchmark, "main_sources", return_value=("fixture-commit", {})),
                patch.object(benchmark, "dynamic_payload", return_value={"snapshot":str(generation)}),
                patch.object(benchmark, "output_path", return_value=target),
                patch.object(benchmark.subprocess, "Popen", return_value=process),
            ):
                with self.assertRaises(SystemExit):
                    benchmark.main()
            self.assertFalse(target.exists())
            self.assertEqual(target.with_suffix(".checkpoint.jsonl").read_text(), "")
            failure = json.loads(target.with_suffix(".failure.json").read_text())
            self.assertFalse(failure["accepted"])
            self.assertEqual(failure["input_error_type"], "BrokenPipeError")
            self.assertEqual(failure["checkpoint_records"], 0)

    def test_legacy_ablation_records_the_policy_that_was_actually_applied(self):
        from unittest.mock import Mock

        tree = ast.parse(benchmark.SCRIPT)
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.If)
                    and isinstance(n.test, ast.BoolOp)
                    and any(isinstance(call, ast.Call) and call.args
                            and isinstance(call.args[0], ast.Constant)
                            and call.args[0].value == "policy"
                            for call in ast.walk(n.test)))
        apply = Mock(return_value=[{"role":"system", "content":"policy applied"}])
        scope = {
            "p":{"ablation":True},
            "matrix":types.SimpleNamespace(ARMS={"fixture":{"policy":True}}),
            "current_arm":"fixture", "messages":[],
            "answer_policy":types.SimpleNamespace(apply_policy=apply),
            "get_settings":lambda:types.SimpleNamespace(prompt_total_char_budget=10000),
            "row":{"answer_policy":"production"},
        }
        exec(compile(ast.Module(body=[node], type_ignores=[]), "policy metadata", "exec"), scope)
        self.assertEqual(scope["row"]["answer_policy"], "evidence_v1")
        self.assertEqual(apply.call_args.args[1], "evidence_v1")

    def test_followup_rotates_repeats_and_requires_unchanged_main_control(self):
        arms = pipeline_matrix.selected_arms(True)
        self.assertIn("raw_multi", arms)
        self.assertEqual(arms["raw_multi"], {"banks":["raw"], "multi":True})
        self.assertTrue(arms["raw_guarded"]["force_products"])
        for rep in range(3):
            orders = [pipeline_matrix.ordered_arms(i, rep, arms) for i in range(len(arms))]
            self.assertEqual({order[0] for order in orders}, set(arms))
            self.assertTrue(all(set(order) == set(arms) for order in orders))
        for names in ([], ["raw_multi"], ["main", "main"], ["main", "unknown"]):
            with self.subTest(names=names), self.assertRaises(ValueError):
                pipeline_matrix.selected_arms(True, names)

    def test_forced_product_prefetch_preserves_knowledge_and_passes_exact_route_arguments(self):
        tree = ast.parse(benchmark.SCRIPT)
        node = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "prefetched_turn")
        arguments = {"scenarios":[{"name":"synthetic", "conditions":[]}]}
        calls = []
        scope = {
            "original_prefetched_turn":lambda args:{"knowledge":args},
            "p":{"pipelines":True}, "pipeline_arms":{"candidate":{"force_products":True}},
            "current_arm":"candidate", "row":{"product_route":{"required":True,"arguments":arguments}},
            "agent_loop":types.SimpleNamespace(_append_synthetic_call=lambda *args:calls.append(args) or args),
        }
        exec(compile(ast.Module(body=[node], type_ignores=[]), "prefetch", "exec"), scope)
        knowledge_args = {"queries":["synthetic question"]}
        scope["prefetched_turn"](knowledge_args)
        self.assertIs(calls[0][0]["knowledge"], knowledge_args)
        self.assertEqual(calls[0][1:3], ("prefetch-spec-products", "filter_products"))
        self.assertIs(calls[0][3], arguments)
        scope["row"]["product_route"]["required"] = False
        self.assertEqual(scope["prefetched_turn"](knowledge_args), {"knowledge":knowledge_args})
        self.assertEqual(len(calls), 1)

    def test_input_byte_changes_and_deleted_snapshot_are_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/"sources.json"
            source.write_bytes(b"old")
            hashes = {str(source):hashlib.sha256(source.read_bytes()).hexdigest()}
            self.assertTrue(benchmark.inputs_unchanged(hashes))
            source.write_bytes(b"new")
            self.assertFalse(benchmark.inputs_unchanged(hashes))
            source.unlink()
            self.assertFalse(benchmark.inputs_unchanged(hashes))

    def test_worker_tool_stages_are_not_dropped_or_nested_into_the_main_thread(self):
        tree = ast.parse(benchmark.SCRIPT)
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and n.name in {"measure", "profile_report"}]
        import time
        start = time.perf_counter()
        scope = {"profiler":stage_profiler.Profiler(request_started_at=start),
                 "profile_thread":threading.get_ident(), "threading":threading,
                 "worker_profiles":{}, "profile_lock":threading.Lock(),
                 "stages":stage_profiler, "request_started":start}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "stages", "exec"), scope)
        def worker():
            with scope["measure"]("knowledge"):
                with scope["measure"]("embedding"):
                    pass
        with scope["measure"]("caller"):
            thread = threading.Thread(target=worker)
            thread.start()
            thread.join()
        report = scope["profile_report"]()
        self.assertEqual(set(report["summary"]), {"caller", "knowledge", "embedding"})
        spans = {s["name"]:s for s in report["spans"]}
        self.assertIsNone(spans["knowledge"]["parent"])
        self.assertNotEqual(spans["knowledge"]["lane"], spans["caller"]["lane"])
        self.assertEqual(report["spans"][spans["embedding"]["parent"]]["name"], "knowledge")

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
                 "time":types.SimpleNamespace(perf_counter=lambda:1),
                 "p":{"ablation":False}, "measure":lambda _:__import__('contextlib').nullcontext()}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "handlers", "exec"), scope)
        arguments = {"queries":["fixture"], "top_k":7, "future_field":"keep"}
        self.assertEqual(scope["knowledge"](arguments), {"original":True})
        self.assertIs(calls[0], arguments)
        self.assertEqual(scope["row_metrics"]["knowledge_calls"], 1)

    def test_ablation_rotates_each_arm_without_giving_one_all_the_warm_positions(self):
        orders = [matrix.ordered_arms(i) for i in range(len(matrix.ARMS))]
        self.assertEqual({order[0] for order in orders}, set(matrix.ARMS))
        for order in orders:
            self.assertEqual(set(order), set(matrix.ARMS))
        self.assertFalse(matrix.recall_controls("main_fixes")["include_wiki"])
        self.assertFalse(matrix.recall_controls("main_fixes")["rewrite"])
        base = dict(matrix.ARMS["main_fixes_rewrite"])
        self.assertEqual(matrix.ARMS["wiki"], {**base, "wiki":True})

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
