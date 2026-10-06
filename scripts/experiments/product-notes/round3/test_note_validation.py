"""Regression cases for independently checked note values and provenance."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from note_validation import parse_source_specs, validate_note


ROOT = Path(__file__).resolve().parent
FROZEN = ROOT.parent / "round2"
ROWS = json.loads((FROZEN / "table_rows.json").read_text())
SOURCE = (FROZEN / "source_catalog.md").read_text()


def note_fixture(index=0, footnotes=None):
    row = deepcopy(ROWS[index])
    fm = parse_source_specs([row])[0]["frontmatter"]
    if footnotes is None:
        footnotes = ([{"page": 9, "line": 208}]
                     if fm["phase"] == [1, 3] else [])
    fm["source"] = {
        "path": "knowledge/EVAK_CATALOG.md", "page": row["page"],
        "row_line": row["line"], "footnotes": footnotes,
    }
    body = (
        f"# {fm['model']}\n\n"
        f"額定點：揚程 {fm['rated_head_m']:g} m，"
        f"流量 {fm['rated_flow_lpm']:g} LPM（同一工作點）。\n"
        f"最大揚程：{fm['max_head_m']:g} m。\n"
        f"最大流量：{fm['max_flow_lpm']:g} LPM。\n"
        "兩者是各自的極限值，不是同一個工作點。\n\n"
        f"出處：第 {row['page']} 頁，L{row['line']}"
    )
    if footnotes:
        body += (f"；註腳：第 {footnotes[0]['page']} 頁，"
                 f"L{footnotes[0]['line']}")
    body += "。\n\n相關連結：[[80EDW-5.20S-T|80EDW-5.20S/T]]\n"
    yaml = "\n".join(f"{key}: {json.dumps(value, ensure_ascii=False)}"
                     for key, value in fm.items())
    return "---\n" + yaml + "\n---\n\n" + body, fm, row


class SourceParsingTests(unittest.TestCase):
    def test_raw_cells_are_independent_from_cached_cells(self):
        row = deepcopy(ROWS[0])
        row["cells"][3] = "999 m @ 999 LPM"
        parsed = parse_source_specs([row])[0]
        self.assertEqual(parsed["frontmatter"]["rated_head_m"], 9.5)
        self.assertEqual(parsed["frontmatter"]["rated_flow_lpm"], 500)

    def test_all_fifteen_rows_and_absent_phase_values(self):
        records = parse_source_specs(ROWS)
        self.assertEqual(len(records), 15)
        self.assertEqual(records[0]["frontmatter"], {
            "model": "80EDW-5.20S/T", "series": "EDW", "hp": 2,
            "kw": 1.5, "outlet_inch": 3, "rated_head_m": 9.5,
            "rated_flow_lpm": 500, "max_head_m": 16.4,
            "max_flow_lpm": 820, "solids_mm": 10, "phase": [1, 3],
            "current_1ph_a": 11, "current_3ph_a": 3.8,
            "weight_1ph_kg": 47, "weight_3ph_kg": 46,
        })
        self.assertEqual(records[3]["frontmatter"]["phase"], 3)
        self.assertIsNone(records[3]["frontmatter"]["current_1ph_a"])
        self.assertIsNone(records[3]["frontmatter"]["weight_1ph_kg"])
        self.assertEqual(records[5]["frontmatter"]["weight_1ph_kg"], 27.5)
        self.assertIsNone(records[5]["frontmatter"]["weight_3ph_kg"])
        self.assertEqual(records[-1]["frontmatter"]["max_flow_lpm"], 1900)

    def test_rejects_corrupt_units_instead_of_extracting_any_number(self):
        row = deepcopy(ROWS[0])
        row["row"] = row["row"].replace("9.5 m @", "9.5 kg @")
        with self.assertRaises(ValueError):
            parse_source_specs([row])


class NoteValidationTests(unittest.TestCase):
    def validate(self, markdown, fm, row, source=SOURCE):
        result = validate_note(markdown, fm, row, source)
        json.dumps(result, ensure_ascii=False, allow_nan=False)
        return result

    def failed(self, markdown, fm, row, code, source=SOURCE):
        result = self.validate(markdown, fm, row, source)
        self.assertEqual(result["status"], "failed", result)
        codes = [error["code"] for error in result["errors"]]
        self.assertIn(code, codes, result)
        return result

    def test_all_fifteen_correct_notes_pass(self):
        for index in range(15):
            with self.subTest(model=ROWS[index]["model"]):
                result = self.validate(*note_fixture(index))
                self.assertEqual(result["status"], "passed", result)
                self.assertEqual(len(result["checked"]["fields"]), 15)

    def test_integer_float_zero_tails_colons_and_unicode_whitespace(self):
        md, fm, row = note_fixture()
        md = md.replace("9.5 m，流量 500 LPM", "9.500\u3000m，流量\u3000500.00 LPM")
        md = md.replace("最大揚程：16.4 m。", "最大揚程: 16.4000 m。")
        fm["hp"] = 2.0
        self.assertEqual(self.validate(md, fm, row)["status"], "passed")

    def test_actual_generated_related_links_list_is_accepted(self):
        # First three captured attempts had this exact valid body; aliases
        # varied between the model spelling and its mapped filename stem.
        body = """# 80EDW-5.20S/T

額定點：揚程 9.5 m，流量 500 LPM（同一工作點）。
最大揚程：16.4 m。
最大流量：820 LPM。
兩者是各自的極限值，不是同一個工作點。

出處：第 9 頁，L201；註腳：第 9 頁，L208。

相關連結：
- [[80EDW-5.20S-T|80EDW-5.20S/T]]
- [[80EDW-5.30S-T|80EDW-5.30S-T]]"""
        md, fm, row = note_fixture()
        prefix = md[:md.index("\n---\n", 4) + len("\n---\n")]
        for alias in ("80EDW-5.30S-T", "80EDW-5.30S/T"):
            actual_body = body.replace(
                "|80EDW-5.30S-T]]", f"|{alias}]]",
            )
            result = self.validate(prefix + actual_body, fm, row)
            self.assertEqual(result["status"], "passed", result)
            self.assertEqual(len(result["checked"]["wikilinks"]), 2)

    def test_related_links_titles_and_standard_bullets_are_accepted(self):
        md, fm, row = note_fixture()
        original = "相關連結：[[80EDW-5.20S-T|80EDW-5.20S/T]]"
        for heading in ("相關連結：", "## 相關連結", "### 相關連結："):
            for marker in ("-", "*", "+"):
                with self.subTest(heading=heading, marker=marker):
                    links = (f"{heading}\n  {marker} "
                             "[[80EDW-5.20S-T|80EDW-5.20S/T]]")
                    result = self.validate(md.replace(original, links), fm, row)
                    self.assertEqual(result["status"], "passed", result)

    def test_fourth_actual_attempt_missing_same_point_still_fails(self):
        md, fm, row = note_fixture()
        md = md.replace("LPM（同一工作點）。", "LPM。")
        md = md.replace("相關連結：[[", "相關連結：\n- [[")
        result = self.failed(md, fm, row, "body_required")
        rated_errors = [error for error in result["errors"]
                        if error["field"] == "rated"]
        self.assertEqual(len(rated_errors), 1)
        self.assertFalse(any(error["field"] == "related_links"
                             for error in result["errors"]))

    def test_link_bullets_cannot_hide_inference_or_unknown_targets(self):
        md, fm, row = note_fixture()
        original = "相關連結：[[80EDW-5.20S-T|80EDW-5.20S/T]]"
        extra = "相關連結：\n- [[80EDW-5.20S-T]] 適合農田灌溉。"
        self.failed(md.replace(original, extra), fm, row, "body_extra")
        unknown = "相關連結：\n- [[UnknownPump]]"
        self.failed(md.replace(original, unknown), fm, row, "wikilink_target")

    def test_swapped_pages_fail_for_both_series(self):
        for index, wrong_page in ((0, 11), (5, 9)):
            with self.subTest(index=index):
                md, fm, row = note_fixture(index)
                fm["source"]["page"] = wrong_page
                self.failed(md, fm, row, "citation_page")

    def test_swapped_body_pages_fail(self):
        md, fm, row = note_fixture(5)
        md = md.replace("出處：第 11 頁", "出處：第 9 頁")
        self.failed(md, fm, row, "body_citation")

    def test_page_is_checked_against_actual_source_heading(self):
        md, fm, row = note_fixture()
        source = SOURCE.replace("## 第 9 頁：EDW", "## 第 11 頁：EDW")
        self.failed(md, fm, row, "citation_page", source)

    def test_wrong_model_row_and_nonmodel_quote_are_rejected(self):
        for wrong_line in (202, 199, 196):
            with self.subTest(line=wrong_line):
                md, fm, row = note_fixture()
                fm["source"]["row_line"] = wrong_line
                self.failed(md, fm, row, "citation_model")

    def test_model_substring_in_a_different_row_cannot_pass(self):
        md, fm, row = note_fixture()
        source = SOURCE.replace("| 80EDW-5.20S/T |", "| 80EDW-5.20S/T-X |")
        self.failed(md, fm, row, "citation_model", source)

    def test_changed_raw_row_is_detected(self):
        md, fm, row = note_fixture()
        source = SOURCE.replace("9.5 m @ 500 LPM", "8.5 m @ 500 LPM", 1)
        self.failed(md, fm, row, "source_row", source)

    def test_missing_required_st_footnote(self):
        md, fm, row = note_fixture(0, footnotes=[])
        self.failed(md, fm, row, "footnote_required")

    def test_three_phase_edw_optional_footnote_both_choices_pass(self):
        for footnotes in ([], [{"page": 9, "line": 208}]):
            result = self.validate(*note_fixture(3, footnotes))
            self.assertEqual(result["status"], "passed", result)

    def test_wrong_footnote_page_line_or_content_fails(self):
        for footnote in ({"page": 11, "line": 208},
                         {"page": 9, "line": 209},
                         {"page": True, "line": 208}):
            md, fm, row = note_fixture(0, [footnote])
            self.failed(md, fm, row, "footnote_reference")
        md, fm, row = note_fixture()
        source = SOURCE.replace("S 代表單相", "S 代表三相", 1)
        self.failed(md, fm, row, "footnote_content", source)

    def test_eub_m_cannot_cite_an_unprovided_or_empty_footnote(self):
        md, fm, row = note_fixture(5, [{"page": 9, "line": 208}])
        self.failed(md, fm, row, "footnote_reference")
        md, fm, row = note_fixture(5)
        fm["source"]["footnotes"] = [{}]
        self.failed(md, fm, row, "footnote_reference")

    def test_footnote_must_also_appear_in_body(self):
        md, fm, row = note_fixture()
        md = md.replace("；註腳：第 9 頁，L208", "")
        self.failed(md, fm, row, "body_footnotes")

    def test_boolean_numbers_phase_and_source_positions_fail(self):
        for field in ("hp", "phase", "rated_head_m", "current_1ph_a"):
            with self.subTest(field=field):
                md, fm, row = note_fixture(5)
                fm[field] = True
                self.failed(md, fm, row, "spec_value")
        md, fm, row = note_fixture()
        fm["phase"] = [True, 3]
        self.failed(md, fm, row, "spec_value")
        md, fm, row = note_fixture()
        fm["source"]["row_line"] = 201.0
        self.failed(md, fm, row, "source_metadata")

    def test_unknown_numeric_missing_null_and_unknown_field_fail(self):
        md, fm, row = note_fixture(3)
        fm["current_1ph_a"] = 0
        self.failed(md, fm, row, "spec_value")
        md, fm, row = note_fixture(3)
        del fm["current_1ph_a"]
        self.failed(md, fm, row, "spec_value")
        md, fm, row = note_fixture()
        fm["invented_head_m"] = 999
        self.failed(md, fm, row, "unknown_field")

    def test_nonfinite_and_nonnumeric_values_produce_json_safe_errors(self):
        for value in (float("nan"), float("inf"), "2 HP", {"value": 2}):
            md, fm, row = note_fixture()
            fm["hp"] = value
            self.failed(md, fm, row, "spec_value")

    def test_independent_body_numeric_audit(self):
        for old, new in (("揚程 9.5 m", "揚程 9.6 m"),
                         ("流量 500 LPM", "流量 501 LPM"),
                         ("最大揚程：16.4 m", "最大揚程：16.5 m"),
                         ("最大流量：820 LPM", "最大流量：821 LPM")):
            md, fm, row = note_fixture()
            self.failed(md.replace(old, new), fm, row, "body_number")

    def test_simultaneous_maxima_fail_even_with_correct_disclaimer(self):
        md, fm, row = note_fixture()
        md += "\n極限點：揚程 16.4 m，流量 820 LPM（同一工作點）。\n"
        self.failed(md, fm, row, "body_extra")

    def test_raw_max_at_notation_is_not_an_allowed_body_sentence(self):
        md, fm, row = note_fixture()
        md = md.replace("最大揚程：16.4 m。\n最大流量：820 LPM。",
                        "極限點：16.4 m @ 820 LPM。")
        self.failed(md, fm, row, "body_required")

    def test_inferences_fail_in_body_or_heading(self):
        for extra in ("適合農田灌溉。", "採用高鉻鋼葉輪。", "適用地下水抽送。"):
            md, fm, row = note_fixture()
            self.failed(md + extra, fm, row, "body_extra")
            self.failed(md + "\n## " + extra, fm, row, "body_heading")

    def test_duplicate_or_missing_sentences_fail(self):
        md, fm, row = note_fixture()
        sentence = "最大流量：820 LPM。"
        self.failed(md + sentence, fm, row, "body_required")
        self.failed(md.replace(sentence, ""), fm, row, "body_required")

    def test_eub_m_requires_row_citation_without_footnotes(self):
        md, fm, row = note_fixture(5)
        md = md.replace("出處：第 11 頁，L233。", "")
        self.failed(md, fm, row, "body_citation_required")

    def test_filename_mapping_and_alias_are_audited(self):
        md, fm, row = note_fixture()
        original = "[[80EDW-5.20S-T|80EDW-5.20S/T]]"
        for bad in ("[[80EDW-5.20S/T]]", "[[UnknownPump]]",
                    "[[../80EDW-5.20S-T]]", "[[80EDW-5.20S-T|適合農田]]"):
            self.failed(md.replace(original, bad), fm, row, "wikilink_target")
        valid = md.replace(original, "[[50EUB-M-5.20S.md]]")
        self.assertEqual(self.validate(valid, fm, row)["status"], "passed")

    def test_errors_keep_multiple_details_instead_of_stopping_at_first(self):
        md, fm, row = note_fixture()
        fm["hp"] = 99
        fm["kw"] = 88
        fm["source"]["page"] = 11
        md += "採用高鉻鋼葉輪。"
        result = self.failed(md, fm, row, "body_extra")
        self.assertGreaterEqual(len(result["errors"]), 5)
        self.assertTrue(all("expected" in item and "actual" in item
                            for item in result["errors"]))

    def test_malformed_input_reports_errors(self):
        md, fm, row = note_fixture()
        row["row"] = "不是規格列"
        self.failed(md, fm, row, "source_parse")
        md, fm, row = note_fixture()
        self.failed(md, None, row, "frontmatter_type")
        self.failed(md.removeprefix("---\n"), fm, row,
                    "frontmatter_delimiters")


if __name__ == "__main__":
    unittest.main()
