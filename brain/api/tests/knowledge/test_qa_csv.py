from __future__ import annotations

import importlib
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def _import(module_name: str):
    return importlib.import_module(module_name)


def test_alias_matching_optimization():
    qa_csv = _import("knowledge.qa_csv")
    csv_data = "questionnaire,image_url,圖片 (image),a\nQ1,http://url,pic.png,A1".encode("utf-8")
    parsed = qa_csv._parse_csv_rows(csv_data)
    assert parsed is not None
    fieldnames, rows = parsed
    assert "img" in fieldnames
    assert "a" in fieldnames
    assert "q" not in fieldnames


def test_encoding_compatibility():
    qa_csv = _import("knowledge.qa_csv")
    big5_data = "問題,回答\nQ1,A1\n".encode("big5")
    parsed = qa_csv._parse_csv_rows(big5_data)
    assert parsed is not None
    fieldnames, rows = parsed
    assert "q" in fieldnames
    assert "a" in fieldnames
    assert rows[0]["q"] == "Q1"
    assert rows[0]["a"] == "A1"

    gbk_data = "问题,回答\nQ2,A2\n".encode("gbk")
    parsed = qa_csv._parse_csv_rows(gbk_data)
    assert parsed is not None
    fieldnames_gbk, rows_gbk = parsed
    assert "q" in fieldnames_gbk
    assert "a" in fieldnames_gbk
    assert rows_gbk[0]["q"] == "Q2"
    assert rows_gbk[0]["a"] == "A2"


def test_normalize_qa_csv_rows():
    qa_csv = _import("knowledge.qa_csv")
    normalize_qa_csv_rows = qa_csv.normalize_qa_csv_rows

    csv_data = (
        b"index,q,a"
        b"\n3,Q3,A3"
        b"\n1,Q1,A1"
        b"\n,,"
        b"\n2,Q2,A2"
    )
    res = normalize_qa_csv_rows(csv_data)
    assert res is not None
    lines = res.decode("utf-8").strip().split("\n")
    assert lines[0] == "index,q,a"
    assert lines[1] == "1,Q1,A1"
    assert lines[2] == "2,Q2,A2"
    assert lines[3] == "3,Q3,A3"

    csv_data_renumber = (
        b"index,question,answer"
        b"\n3,Q3,A3"
        b"\n3,Q3-dup,A3-dup"
        b"\n,Q1,A1"
    )
    res_renumber = normalize_qa_csv_rows(csv_data_renumber)
    assert res_renumber is not None
    lines_renumber = res_renumber.decode("utf-8").strip().split("\n")
    assert lines_renumber[0] == "index,q,a"
    assert "1" in lines_renumber[1]
    assert "2" in lines_renumber[2]
    assert "3" in lines_renumber[3]


def test_convert_csv_to_qa_markdown_embeds_hidden_and_normalizes():
    qa_csv = _import("knowledge.qa_csv")
    convert = qa_csv.convert_csv_to_qa_markdown

    csv_data = (
        "index,問題,答案,display,img,url\n"
        "2,Q2,A2,false,,\n"
        "1,Q1,A1,true,pic1.png,https://example.com\n"
        ",,,,,\n"
    ).encode("utf-8")
    markdown = convert(csv_data)

    assert markdown.index("## Q1") < markdown.index("## Q2")
    q1_block, q2_block = markdown.split("## Q2")
    assert '"hidden": true' in q2_block
    assert '"hidden"' not in q1_block
    assert '"img": "pic1.png"' in q1_block
    assert '"url": "https://example.com"' in q1_block


def test_parse_qa_markdown_returns_hidden():
    qa_csv = _import("knowledge.qa_csv")
    markdown = (
        '## Q1\n\nA1\n<!-- qa_metadata: {"img": "", "url": "", "hidden": true} -->\n\n'
        '## Q2\n\nA2\n<!-- qa_metadata: {"img": "p.png", "url": ""} -->'
    )
    entries = qa_csv.parse_qa_markdown(markdown)
    assert entries[0]["q"] == "Q1"
    assert entries[0]["hidden"] is True
    assert entries[1]["hidden"] is False
    assert entries[1]["img"] == "p.png"
