"""驗證未知規格、候選完整性及共同額定點的篩選邊界。"""

from copy import deepcopy
from math import isclose
import unittest

from filter_engine import evaluate_filters, normalize_quantity, validate_spec


def condition(field, op, value):
    return {"field": field, "op": op, "value": value}


def notes(*rows):
    return [{"frontmatter": row} for row in rows]


def run(where, products, **kwargs):
    spec = {"scenarios": [{"name": "需求", "where": where, **kwargs}]}
    return evaluate_filters(spec, products)["scenarios"][0]


def models(rows):
    return [row["model"] for row in rows]


class FilterEngineTests(unittest.TestCase):
    def test_null_and_false_takes_priority(self):
        result = run({"all": [condition("hp", "gte", 3),
                               condition("series", "eq", "EDW")]},
                     notes({"model": "a", "hp": None, "series": "EUB-M"}))
        self.assertEqual(models(result["excluded"]), ["a"])
        self.assertEqual(result["unknown"], [])

    def test_null_and_true_is_unknown(self):
        result = run({"all": [condition("hp", "gte", 3),
                               condition("series", "eq", "EDW")]},
                     notes({"model": "a", "hp": None, "series": "EDW"}))
        self.assertEqual(models(result["unknown"]), ["a"])
        self.assertEqual(result["excluded"], [])

    def test_null_or_true_takes_priority(self):
        result = run({"any": [condition("hp", "gte", 3),
                               condition("series", "eq", "EDW")]},
                     notes({"model": "a", "hp": None, "series": "EDW"}))
        self.assertEqual(models(result["matches_all"]), ["a"])

    def test_null_or_false_is_unknown(self):
        result = run({"any": [condition("hp", "gte", 3),
                               condition("series", "eq", "EDW")]},
                     notes({"model": "a", "hp": None, "series": "EUB-M"}))
        self.assertEqual(models(result["unknown"]), ["a"])

    def test_nested_expressions(self):
        where = {"all": [condition("hp", "lte", 3), {"any": [
            condition("series", "eq", "EDW"),
            condition("rated_flow_lpm", "gte", 500),
        ]}]}
        result = run(where, notes(
            {"model": "a", "hp": 3, "series": "EDW"},
            {"model": "b", "hp": 2, "series": "EUB-M", "rated_flow_lpm": 500},
            {"model": "c", "hp": 4, "series": "EDW"},
        ))
        self.assertEqual(models(result["matches_all"]), ["a", "b"])
        self.assertEqual(models(result["excluded"]), ["c"])

    def test_phase_eq_matches_scalar_and_combined_row(self):
        result = run(condition("phase", "eq", 3), notes(
            {"model": "a", "phase": 3}, {"model": "b", "phase": [1, 3]},
            {"model": "c", "phase": 1}, {"model": "d", "phase": None},
        ))
        self.assertEqual(models(result["matches_all"]), ["a", "b"])
        self.assertEqual(models(result["excluded"]), ["c"])
        self.assertEqual(models(result["unknown"]), ["d"])

    def test_phase_in_intersection_and_ne(self):
        products = notes({"model": "a", "phase": [1, 3]},
                         {"model": "b", "phase": 1})
        result = run(condition("phase", "in", [3]), products)
        self.assertEqual(models(result["matches_all"]), ["a"])
        result = run(condition("phase", "ne", 3), products)
        self.assertEqual(models(result["matches_all"]), ["b"])
        result = run(condition("phase", "contains", 3), products)
        self.assertEqual(models(result["matches_all"]), ["a"])

    def test_multiple_sort_fields_and_stable_tie(self):
        products = notes(
            {"model": "a", "hp": 3, "max_head_m": 20},
            {"model": "b", "hp": 2, "max_head_m": 20},
            {"model": "c", "hp": 2, "max_head_m": 25},
            {"model": "d", "hp": 2, "max_head_m": 25},
        )
        result = run({"all": []}, products, sort=[
            {"field": "hp", "direction": "asc"},
            {"field": "max_head_m", "direction": "desc"},
        ])
        self.assertEqual(models(result["selected"]), ["c", "d", "b", "a"])

    def test_missing_sort_field_stays_in_matches_at_tail(self):
        result = run({"all": []}, notes(
            {"model": "a", "hp": 1, "max_head_m": None},
            {"model": "b", "hp": 3, "max_head_m": 20},
        ), sort=[{"field": "hp", "direction": "asc"},
                 {"field": "max_head_m", "direction": "desc"}])
        self.assertEqual(models(result["matches_all"]), ["b", "a"])
        self.assertEqual(result["sort_unknown"],
                         [{"model": "a", "fields": ["max_head_m"]}])
        self.assertEqual(result["matches_all"][1]["missing_sort_fields"],
                         ["max_head_m"])
        self.assertEqual(result["excluded"], [])

    def test_limit_preserves_all_candidates(self):
        result = run({"all": []}, notes({"model": "a"}, {"model": "b"}), limit=1)
        self.assertEqual(models(result["matches_all"]), ["a", "b"])
        self.assertEqual(models(result["selected"]), ["a"])

    def test_scenarios_are_independent(self):
        spec = {"scenarios": [
            {"name": "小馬力", "where": condition("hp", "lte", 2)},
            {"name": "高揚程", "where": condition("max_head_m", "gte", 25)},
        ]}
        result = evaluate_filters(spec, notes(
            {"model": "a", "hp": 2, "max_head_m": 20},
            {"model": "b", "hp": 3, "max_head_m": 25},
        ))["scenarios"]
        self.assertEqual(models(result[0]["selected"]), ["a"])
        self.assertEqual(models(result[1]["selected"]), ["b"])

    def test_operating_point_never_combines_maxima(self):
        result = run({"all": []}, notes(
            {"model": "max-only", "max_head_m": 25, "max_flow_lpm": 900},
            {"model": "exact", "rated_head_m": 15, "rated_flow_lpm": 400},
            {"model": "capacity", "rated_head_m": 20, "rated_flow_lpm": 500},
            {"model": "lower", "rated_head_m": 10, "rated_flow_lpm": 900},
        ), operating_point={"head_m": 15, "flow_lpm": 400})
        check = result["operating_point_check"]
        self.assertEqual(models(check["exact_rated_matches"]), ["exact"])
        self.assertEqual(models(check["rated_capacity_candidates"]),
                         ["exact", "capacity"])
        self.assertEqual(check["unknown_curve_models"],
                         ["max-only", "capacity", "lower"])
        self.assertIn("尚未證實需求點", check["warning"])
        self.assertIn("max_head_m", check["warning"])

    def test_operating_point_keeps_filter_unknown_separate(self):
        result = run(condition("hp", "lte", 3), notes(
            {"model": "a", "hp": None, "rated_head_m": 20,
             "rated_flow_lpm": 500},
        ), operating_point={"head_m": 15, "flow_lpm": 400})
        self.assertEqual(models(result["unknown"]), ["a"])
        self.assertEqual(result["operating_point_check"]["rated_capacity_candidates"], [])
        self.assertEqual(result["operating_point_check"]["unknown_curve_models"], ["a"])

    def test_invalid_field_operator_and_unknown_schema_key(self):
        bad = [condition("price", "eq", 100), condition("hp", "sql", 3),
               {"field": "hp", "op": "gte", "value": 3, "extra": True},
               {"all": [], "any": []}]
        for expr in bad:
            with self.subTest(expr=expr), self.assertRaises(ValueError):
                run(expr, [])
        with self.assertRaises(ValueError):
            validate_spec({"scenarios": [], "extra": True})

    def test_invalid_limits_and_duplicate_names(self):
        for limit in (True, False, 0, -1, 1.5, "1"):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                run({"all": []}, [], limit=limit)
        with self.assertRaises(ValueError):
            validate_spec({"scenarios": [
                {"name": "重複", "where": {"all": []}},
                {"name": "重複", "where": {"all": []}},
            ]})

    def test_nan_infinity_bool_and_null_query_rejected(self):
        for value in (float("nan"), float("inf"), float("-inf"), True, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                run(condition("hp", "gte", value), [])
        with self.assertRaises(ValueError):
            run({"all": []}, notes({"model": "a", "hp": float("nan")}))

    def test_empty_all_any_and_input_not_mutated(self):
        products = notes({"model": "a", "hp": None})
        before = deepcopy(products)
        self.assertEqual(models(run({"all": []}, products)["selected"]), ["a"])
        self.assertEqual(models(run({"any": []}, products)["excluded"]), ["a"])
        run({"all": []}, products, sort=[{"field": "hp", "direction": "asc"}])
        self.assertEqual(products, before)

    def test_flow_quantity_normalization(self):
        self.assertEqual(normalize_quantity(30, "m3/h", "rated_flow_lpm"), 500)
        self.assertEqual(normalize_quantity(30, "m³/h", "max_flow_lpm"), 500)
        self.assertTrue(isclose(normalize_quantity(40, "m3/h", "max_flow_lpm"),
                                2000 / 3))
        converted = normalize_quantity(30, "m3/h", "rated_flow_lpm")
        result = run(condition("rated_flow_lpm", "gte", converted),
                     notes({"model": "a", "rated_flow_lpm": 500}))
        self.assertEqual(models(result["selected"]), ["a"])
        with self.assertRaises(ValueError):
            normalize_quantity(30, "m3/h", "hp")


if __name__ == "__main__":
    unittest.main()
