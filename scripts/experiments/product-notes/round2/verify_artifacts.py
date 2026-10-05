"""Independently parse frozen source rows and verify experiment artifacts."""

import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent


def read(name):
    return json.loads((ROOT / name).read_text())


def number(cell):
    return float(re.search(r"\d+(?:\.\d+)?", cell)[0])


def optional_number(cell):
    return None if cell.strip() == "-" else number(cell)


def source_specs():
    records = []
    for row in read("table_rows.json"):
        c = row["cells"]
        hp, kw = map(number, c[1].split("/"))
        rh, rf = map(number, c[3].split("@"))
        mh, mf = map(number, c[4].split("@"))
        if row["series"] == "EDW":
            currents = [optional_number(v) for v in c[6].split("/")]
            weights = [optional_number(v) for v in c[7].split("/")]
        else:
            currents = [optional_number(c[6]), optional_number(c[7])]
            weights = [optional_number(v) for v in c[8].split("/")]
        phases = [phase for phase, val in zip((1, 3), currents)
                  if val is not None]
        fm = {
            "model": row["model"], "series": row["series"],
            "hp": hp, "kw": kw, "outlet_inch": number(c[2]),
            "rated_head_m": rh, "rated_flow_lpm": rf,
            "max_head_m": mh, "max_flow_lpm": mf,
            "solids_mm": number(c[5]),
            "phase": phases if len(phases) > 1 else phases[0],
            "current_1ph_a": currents[0], "current_3ph_a": currents[1],
            "weight_1ph_kg": weights[0], "weight_3ph_kg": weights[1],
        }
        records.append({"frontmatter": fm, "line": row["line"],
                        "page": row["page"]})
    return records


def main():
    source = (ROOT / "source_catalog.md").read_text()
    lines = source.splitlines()
    qs = read("questions.json")["questions"]
    frozen = read("question_validation.json")
    for filename, key in (("questions.json", "questions_sha256"),
                          ("table_rows.json", "table_rows_sha256")):
        assert hashlib.sha256((ROOT / filename).read_bytes()).hexdigest() == (
            frozen[key])
    assert len(qs) == 12 and len({q["id"] for q in qs}) == 12
    citations = 0
    for question in qs:
        for citation in question["sources"]:
            actual = "\n".join(lines[
                citation["line_start"] - 1:citation["line_end"]
            ])
            assert actual == citation["quote"], (question["id"], citation)
            citations += 1
    for row in read("table_rows.json"):
        assert lines[row["line"] - 1] == row["row"]
    references = source_specs()
    assert len(references) == 15
    known_numeric = sum(isinstance(v, (int, float)) and not isinstance(v, bool)
                        for r in references for v in r["frontmatter"].values())
    null_count = sum(v is None for r in references
                     for v in r["frontmatter"].values())
    audit = {"method": "独立解析凍結規格表，核對所有frontmatter欄位；不修改原生成筆記。".replace("独", "獨"),
             "note_count": 15, "known_numeric_count": known_numeric,
             "null_count": null_count, "spec_errors": [],
             "provenance_issues": [], "details": []}
    if (ROOT / "generation.json").exists():
        generation = read("generation.json")
        assert generation["config"]["source_sha256"] == hashlib.sha256(
            source.encode()).hexdigest()
        assert len(generation["notes"]) == 15
        by_model = {n["frontmatter"]["model"]: n
                    for n in generation["notes"]}
        assert len(by_model) == 15
        for reference in references:
            expected = reference["frontmatter"]
            note = by_model[expected["model"]]
            assert (ROOT / "notes" / note["filename"]).read_text().strip() == (
                note["markdown"].strip())
            fm = note["frontmatter"]
            checks = []
            for key, value in expected.items():
                actual = fm.get(key)
                match = actual == value
                if isinstance(actual, bool):
                    match = False
                checks.append({"field": key, "expected": value,
                               "actual": actual, "match": match,
                               "source_line": reference["line"]})
                if not match:
                    audit["spec_errors"].append({"model": expected["model"],
                                                 **checks[-1]})
            src = fm.get("source", {})
            if (src.get("path") != "knowledge/EVAK_CATALOG.md"
                    or src.get("page") != reference["page"]
                    or src.get("row_line") != reference["line"]):
                audit["provenance_issues"].append({
                    "model": expected["model"], "source": src,
                    "expected_row": reference["line"],
                    "expected_page": reference["page"],
                })
            footnotes = src.get("footnotes", [])
            allowed = [{"page": 9, "line": 208}] if (
                expected["series"] == "EDW") else []
            if any(f not in allowed for f in footnotes):
                audit["provenance_issues"].append({
                    "model": expected["model"], "footnotes": footnotes,
                    "reason": "出處包含未提供或無關的註腳",
                })
            if (expected["series"] == "EDW" and isinstance(expected["phase"], list)
                    and allowed[0] not in footnotes):
                audit["provenance_issues"].append({
                    "model": expected["model"],
                    "reason": "S/T相數缺少第9頁208行註腳出處",
                })
            audit["details"].append({"model": expected["model"],
                                     "checks": checks})
        audit["spec_error_count"] = len(audit["spec_errors"])
        audit["provenance_issue_count"] = len(audit["provenance_issues"])
        (ROOT / "numeric_audit.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
        assert not generation["integrity"]["changed"]
        assert generation["integrity"]["digest_before"] == (
            generation["integrity"]["digest_after"])
    if (ROOT / "results.json").exists():
        results = read("results.json")
        assert len(results["questions"]) == 12
        assert len(results["calls"]) == 48
        assert results["usage"]["missing_usage_calls"] == 0
        assert not results["integrity"]["changed"]
        from filter_engine import evaluate_filters
        mismatches = []
        for row in results["questions"]:
            assert set(row["answers"]) == {"A", "B", "C"}
            assert len(row["nearest_notes"]) == 3
            if row["filter_spec"] is not None:
                recomputed = evaluate_filters(row["filter_spec"], references)
                if recomputed != row["frontmatter_filter"]:
                    # Source provenance fields exist only in the LLM notes.
                    def canonical(obj):
                        if isinstance(obj, list):
                            return [canonical(v) for v in obj]
                        if isinstance(obj, dict):
                            return {k: canonical(v) for k, v in obj.items()
                                    if k != "source"}
                        return obj
                    if canonical(recomputed) != canonical(row["frontmatter_filter"]):
                        mismatches.append(row["id"])
            assert row["embedding_version"].split(":")[:5] == (
                row["note_embedding_identity"].split(":")[:5])
            assert row["embedding_version"].split(":")[-1] == (
                row["note_embedding_identity"].split(":")[-1])
        assert not mismatches, mismatches
        answer_calls = [c for c in results["calls"]
                        if not c["label"].startswith("filter-")]
        assert len({c["system_sha256"] for c in answer_calls}) == 1
        assert all(c["model"] == results["config"]["model"]
                   for c in results["calls"])
        if "summary" in results:
            for arm in ("A", "B", "C"):
                assert sum(results["summary"]["scores"][arm].values()) == 12
    for path in ROOT.glob("*.py"):
        compile(path.read_text(), str(path), "exec")
    report = {"status": "passed", "questions": 12,
              "exact_citations": citations, "source_rows": 15,
              "known_numeric_fields": known_numeric,
              "null_fields": null_count,
              "spec_errors": len(audit["spec_errors"])}
    (ROOT / "verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
