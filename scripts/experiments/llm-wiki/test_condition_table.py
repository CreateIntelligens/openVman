"""Synthetic facts test exact variant lookup and conservative answer gates."""

import copy
import json
import unittest

from condition_table import Table


def record(row_id="a", *, entity="model-a", attribute="current", conditions=None,
           value="12.5", unit="A", approved=True):
    return {
        "id": row_id, "entity": entity, "attribute": attribute,
        "conditions": ({"freq": "50Hz", "phase": "3", "voltage": "400V"}
                       if conditions is None else conditions),
        "value": value, "unit": unit,
        "source": {"ref": "synthetic-ref:" + row_id,
                   "quote": "Synthetic literal value: " + value + " " + unit,
                   "sha256": "a" * 64},
        "approved": approved,
    }


class LookupTests(unittest.TestCase):
    def test_frequency_variants_are_separate_and_sources_are_preserved(self):
        first = record()
        second = record("b", conditions={"freq": "60Hz", "phase": "3", "voltage": "400V"},
                        value="14.0")
        table = Table([first, second])
        for row in (first, second):
            with self.subTest(freq=row["conditions"]["freq"]):
                result = table.lookup("model-a", "current", row["conditions"])
                self.assertEqual(result["status"], "answer")
                self.assertEqual(result["value"], row["value"])
                self.assertEqual(result["matches"], [row])
                self.assertEqual(result["conditions"], row["conditions"])
                self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)

    def test_missing_or_unknown_source_frequency_never_supports_50_or_60(self):
        for source_conditions in (
            {"phase": "3", "voltage": "400V"},
            {"freq": "unknown", "phase": "3", "voltage": "400V"},
        ):
            table = Table([record(conditions=source_conditions)])
            for freq in ("50Hz", "60Hz"):
                with self.subTest(source=source_conditions, freq=freq):
                    result = table.lookup("model-a", "current", {
                        "freq": freq, "phase": "3", "voltage": "400V",
                    })
                    self.assertEqual(result["status"], "unknown")

    def test_same_hp_does_not_identify_a_model(self):
        table = Table([
            record(conditions={"hp": "3", "phase": "3"}),
            record("b", entity="model-b", conditions={"hp": "3", "phase": "3"}, value="16"),
        ])
        self.assertEqual(table.lookup("3HP", "current", {"hp": "3", "phase": "3"})["status"],
                         "unknown")
        self.assertEqual(table.lookup("model-b", "current", {"hp": "3", "phase": "3"})["value"],
                         "16")

    def test_phase_and_voltage_from_different_rows_cannot_be_combined(self):
        table = Table([
            record(conditions={"freq": "60Hz", "phase": "1", "voltage": "220V"}),
            record("b", conditions={"freq": "60Hz", "phase": "3", "voltage": "400V"}),
        ])
        result = table.lookup("model-a", "current", {
            "freq": "60Hz", "phase": "1", "voltage": "400V",
        })
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["matches"], [])

    def test_clinic_close_cannot_substitute_for_checkin_deadline(self):
        base = {"service": "synthetic-service", "weekday": "Monday"}
        closing = record(entity="synthetic-desk", attribute="time",
                         conditions={**base, "time_kind": "clinic_close"}, value="17:00", unit="")
        deadline = record("b", entity="synthetic-desk", attribute="time",
                          conditions={**base, "time_kind": "checkin_deadline"}, value="16:30", unit="")
        query = {**base, "time_kind": "checkin_deadline"}
        self.assertEqual(Table([closing]).lookup("synthetic-desk", "time", query)["status"],
                         "unknown")
        self.assertEqual(Table([closing, deadline]).lookup("synthetic-desk", "time", query)["value"],
                         "16:30")

    def test_missing_any_candidate_dimension_requires_clarification(self):
        first = record()
        second = record("b", conditions={**first["conditions"], "mode": "continuous"})
        table = Table([first, second])
        result = table.lookup("model-a", "current", {"freq": "50Hz"})
        self.assertEqual(result["status"], "clarify")
        self.assertEqual(result["missing"], ["mode", "phase", "voltage"])
        self.assertEqual(result["matches"], [first, second])
        self.assertNotIn("value", result)

    def test_approval_defaults_false_and_any_unapproved_match_blocks_answer(self):
        first = record()
        pending = record("b")
        pending.pop("approved")
        result = Table([first, pending]).lookup("model-a", "current", first["conditions"])
        self.assertEqual(result["status"], "review_required")
        self.assertFalse(result["matches"][1]["approved"])
        self.assertNotIn("value", result)
        self.assertIn("not automatically verified", result["support"])

    def test_conflicting_value_or_unit_is_reported_before_approval(self):
        first = record()
        for value, unit in (("13.5", "A"), ("12.5", "mA")):
            with self.subTest(value=value, unit=unit):
                other = record("b", value=value, unit=unit, approved=False)
                result = Table([first, other]).lookup("model-a", "current", first["conditions"])
                self.assertEqual(result["status"], "conflict")
                self.assertEqual(result["matches"], [first, other])
                self.assertNotIn("value", result)

    def test_independent_maxima_do_not_prove_an_operating_point(self):
        table = Table([
            record(attribute="max_head", value="20", unit="m"),
            record("b", attribute="max_flow", value="500", unit="LPM"),
        ])
        conditions = {"freq": "50Hz", "phase": "3", "voltage": "400V"}
        result = table.lookup("model-a", "operating_point", {
            **conditions, "head_m": "20", "flow_lpm": "500",
        })
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(table.lookup("model-a", "max_head", conditions)["value"], "20")

    def test_unknown_and_exact_matching_do_not_normalize_or_interpolate(self):
        table = Table([record()])
        for entity, attribute, conditions in (
            ("MODEL-A", "current", record()["conditions"]),
            ("model-a", "Current", record()["conditions"]),
            ("model-a", "current", {"freq": "55Hz", "phase": "3", "voltage": "400V"}),
            ("model-a", "current", {"freq": "50Hz ", "phase": "3", "voltage": "400V"}),
        ):
            with self.subTest(entity=entity, attribute=attribute, conditions=conditions):
                self.assertEqual(table.lookup(entity, attribute, conditions)["status"], "unknown")

    def test_inputs_and_results_cannot_mutate_table_or_each_other(self):
        original = record()
        before = copy.deepcopy(original)
        table = Table([original])
        original["value"] = "changed"
        query = copy.deepcopy(before["conditions"])
        result = table.lookup("model-a", "current", query)
        result["matches"][0]["source"]["quote"] = "changed"
        result["conditions"]["freq"] = "changed"
        self.assertEqual(query, before["conditions"])
        self.assertEqual(table.lookup("model-a", "current", query)["matches"], [before])


class ContractTests(unittest.TestCase):
    def test_value_without_verbatim_quote_support_is_rejected(self):
        for value in ("12.50", "１２.５", "", " "):
            row = record()
            row["value"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                Table([row])

    def test_invalid_record_and_source_types_are_rejected(self):
        bad_rows = []
        for field, bad in (
            ("id", 1), ("entity", " "), ("attribute", None), ("value", 12.5),
            ("unit", None), ("approved", "true"), ("conditions", []),
            ("conditions", {"phase": 3}), ("conditions", {1: "3"}),
            ("conditions", {"freq": ""}), ("source", "source"),
        ):
            bad_rows.append({**record(), field: bad})
        for field, bad in (("ref", ""), ("ref", 1), ("quote", None),
                           ("sha256", "g" * 64), ("sha256", "a" * 63)):
            row = record()
            row["source"][field] = bad
            bad_rows.append(row)
        for row in bad_rows:
            with self.subTest(row=row), self.assertRaises(ValueError):
                Table([row])

    def test_duplicate_ids_missing_fields_and_extra_fields_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            Table([record(), record()])
        for field in ("id", "source", "conditions"):
            row = record()
            row.pop(field)
            with self.subTest(field=field), self.assertRaises(ValueError):
                Table([row])
        with self.assertRaises(ValueError):
            Table([{**record(), "guessed": True}])
        with self.assertRaises(ValueError):
            Table([{"source": {}}])
        with self.assertRaises(ValueError):
            Table(None)

    def test_invalid_query_types_are_rejected(self):
        table = Table([])
        for args in ((None, "current", {}), ("model-a", [], {}),
                     ("model-a", "current", []),
                     ("model-a", "current", {"phase": 3})):
            with self.subTest(args=args), self.assertRaises(ValueError):
                table.lookup(*args)


if __name__ == "__main__":
    unittest.main()
