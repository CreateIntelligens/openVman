"""Check frozen evidence and meaningful filter edge cases without LLM calls."""

import ast
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def read(name):
    return json.loads((ROOT / name).read_text())


def main():
    source = (ROOT / "source_catalog.md").read_text()
    lines = source.splitlines()
    questions = read("questions.json")["questions"]
    assert len(questions) == 10
    assert len({q["id"] for q in questions}) == 10
    citations = 0
    for question in questions:
        assert question["required_points"] and question["sources"]
        for citation in question["sources"]:
            actual = "\n".join(lines[
                citation["line_start"] - 1:citation["line_end"]
            ])
            assert actual == citation["quote"], (question["id"], citation)
            citations += 1
    generation = read("generation.json")
    assert generation["config"]["source_sha256"] == hashlib.sha256(
        source.encode()
    ).hexdigest()
    expected = {}
    for line in lines:
        if line.startswith("| ") and "EUS-" in line:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) == 8:
                expected[cells[0]] = dict(zip(
                    ("height_mm", "cwl_mm", "lwl_mm"),
                    map(float, cells[4:7]),
                ))
    assert len(expected) == 5
    checked = 0
    for note in generation["notes"]:
        assert (ROOT / "notes" / note["filename"]).read_text().strip() == (
            note["markdown"].strip()
        )
        fm = note["frontmatter"]
        for field, value in expected[fm["model"]].items():
            assert fm[field] == value
            checked += 1
        assert fm["max_depth_m"] == 10
        checked += 1
        for field in ("hp", "head_m", "outlet_inches"):
            assert fm[field] is None
    # Exercise the actual filter function independently of the container loop.
    tree = ast.parse((ROOT / "runtime.py").read_text())
    function = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef)
                    and n.name == "apply_filter")
    namespace = {"fields": ["hp", "height_mm"], "notes": [
        {"frontmatter": {"model": "known", "hp": 1, "height_mm": 350}},
        {"frontmatter": {"model": "unknown", "hp": None,
                         "height_mm": 400}},
        {"frontmatter": {"model": "excluded", "hp": 2,
                         "height_mm": 500}},
    ]}
    exec(compile(ast.Module(body=[function], type_ignores=[]),
                 "filter-under-test", "exec"), namespace)
    apply_filter = namespace["apply_filter"]
    result = apply_filter({"conditions": [
        {"field": "hp", "op": "eq", "value": 1},
    ]})
    assert [r["model"] for r in result["matches"]] == ["known"]
    assert [r["model"] for r in result["unknown"]] == ["unknown"]
    assert [r["model"] for r in result["excluded"]] == ["excluded"]
    result = apply_filter({"conditions": [
        {"field": "hp", "op": "eq", "value": 1},
        {"field": "height_mm", "op": "lt", "value": 390},
    ]})
    assert not result["unknown"]
    assert len(result["excluded"]) == 2
    result = apply_filter({"conditions": [],
                           "sort": {"field": "height_mm",
                                    "direction": "desc"}, "limit": 1})
    assert result["matches"][0]["model"] == "excluded"
    result = apply_filter({"conditions": [],
                           "sort": {"field": "hp", "direction": "asc"}})
    assert [r["model"] for r in result["unknown"]] == ["unknown"]
    for invalid in ({"conditions": [], "limit": -1},
                    {"conditions": [], "combine": "or"},
                    {"conditions": [{"field": "hp", "op": "eval",
                                     "value": 1}]}):
        try:
            apply_filter(invalid)
        except AssertionError:
            pass
        else:
            raise AssertionError("不合法篩選條件未拒絕")
    for path in ROOT.glob("*.py"):
        compile(path.read_text(), str(path), "exec")
    if (ROOT / "results.json").exists():
        results = read("results.json")
        assert len(results["questions"]) == 10
        assert len(results["calls"]) == 40
        assert results["usage"]["missing_usage_calls"] == 0
        assert not results["integrity"]["changed"]
        for row in results["questions"]:
            assert set(row["answers"]) == {"A", "B", "C"}
            assert len(row["nearest_notes"]) == 3
            assert row["current_search"]["results"]
            assert row["embedding_version"].split(":")[:5] == (
                row["note_embedding_identity"].split(":")[:5]
            )
            assert row["embedding_version"].split(":")[-1] == (
                row["note_embedding_identity"].split(":")[-1]
            )
        assert all(c["model"] == results["config"]["model"]
                   for c in results["calls"])
        if "summary" in results:
            assert all("grade" in a for row in results["questions"]
                       for a in row["answers"].values())
            for arm in ("A", "B", "C"):
                assert sum(results["summary"]["scores"][arm].values()) == 10
    assert not generation["integrity"]["changed"]
    print(json.dumps({"questions": 10, "exact_citations": citations,
                      "numeric_fields": checked, "filter_cases": 7,
                      "status": "passed"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
