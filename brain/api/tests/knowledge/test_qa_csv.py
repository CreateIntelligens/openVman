from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def _import(module_name: str):
    return importlib.import_module(module_name)


def test_validate_supported_qa_csv():
    qa_csv = _import("knowledge.qa_csv")
    validate_supported_qa_csv = qa_csv.validate_supported_qa_csv
    UnsupportedQaCsvError = qa_csv.UnsupportedQaCsvError

    # 1. 普通非 QA CSV 應通過
    plain_csv = b"name,age\nAlice,20\nBob,30"
    validate_supported_qa_csv(plain_csv)

    # 2. 完整且包含別名的 QA CSV 應通過
    valid_csv = "問題,解答\nQ1,A1".encode("utf-8")
    validate_supported_qa_csv(valid_csv)

    # 3. 缺 a 欄位但有 q 欄位，應拋出 UnsupportedQaCsvError
    invalid_csv = b"question,other\nQ1,other_value"
    with pytest.raises(UnsupportedQaCsvError) as exc_info:
        validate_supported_qa_csv(invalid_csv)
    assert "q and a columns" in str(exc_info.value)

    # 4. 解析結果為 None、空 CSV、無任何欄位，應拋出 UnsupportedQaCsvError
    empty_csv = b""
    with pytest.raises(UnsupportedQaCsvError) as exc_info:
        validate_supported_qa_csv(empty_csv)
    assert "CSV is empty, invalid, or could not be parsed." in str(exc_info.value)


def test_alias_matching_optimization():
    qa_csv = _import("knowledge.qa_csv")
    # 測試 image_url 不會被誤匹配為 img，questionnaire 不會被誤匹配為 q
    # 測試 圖片 (image) 會被匹配為 img
    csv_data = "questionnaire,image_url,圖片 (image),a\nQ1,http://url,pic.png,A1".encode("utf-8")
    parsed = qa_csv._parse_csv_rows(csv_data)
    assert parsed is not None
    fieldnames, rows = parsed
    assert "img" in fieldnames
    assert "a" in fieldnames
    assert "q" not in fieldnames  # questionnaire 不應變成 q


def test_encoding_compatibility():
    qa_csv = _import("knowledge.qa_csv")
    # Big5 編碼測試
    big5_data = "問題,回答\nQ1,A1\n".encode("big5")
    parsed = qa_csv._parse_csv_rows(big5_data)
    assert parsed is not None
    fieldnames, rows = parsed
    assert "q" in fieldnames
    assert "a" in fieldnames
    assert rows[0]["q"] == "Q1"
    assert rows[0]["a"] == "A1"

    # GBK 編碼測試
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

    # 1. 測試保留可保留的 index 並排序，且排除空 QA 列
    csv_data = (
        b"index,q,a"
        b"\n3,Q3,A3"
        b"\n1,Q1,A1"
        b"\n,,"  # 空列，應被排除
        b"\n2,Q2,A2"
    )
    res = normalize_qa_csv_rows(csv_data)
    assert res is not None
    lines = res.decode("utf-8").strip().split("\n")
    assert lines[0] == "index,q,a"
    assert lines[1] == "1,Q1,A1"
    assert lines[2] == "2,Q2,A2"
    assert lines[3] == "3,Q3,A3"

    # 2. 測試不可保留 index 的重新編號 (有重複或缺失)
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


def test_split_qa_csv_by_image():
    qa_csv = _import("knowledge.qa_csv")
    split_qa_csv_by_image = qa_csv.split_qa_csv_by_image

    csv_data = (
        b"q,a,img"
        b"\nQ1,A1,images/pic.png"
        b"\nQ2,A2,"
    )
    splits = split_qa_csv_by_image(csv_data, "test.csv")
    assert splits is not None
    assert len(splits) == 2
    
    main_name, main_bytes = splits[0]
    assert main_name == "test.csv"
    assert b"Q2,A2" in main_bytes
    assert b"Q1,A1" not in main_bytes
    
    img_name, img_bytes = splits[1]
    assert img_name == "test_IMG_pic.png.csv"
    assert b"Q1,A1" in img_bytes
    assert b"Q2,A2" not in img_bytes

    csv_no_img_val = b"q,a,img\nQ1,A1,\n"
    assert split_qa_csv_by_image(csv_no_img_val, "test.csv") is None


def test_merge_csv_files():
    qa_csv = _import("knowledge.qa_csv")
    merge_csv_files = qa_csv.merge_csv_files

    # 包含重複 QA 項目的去重驗證測試，題目忽略大小寫與前後空白去重，保留首次出現的項目
    file1 = b"index,q,a,img,url\n2,Q2,A2,IMG=images/photo2.png,http://url2\n1,Q_dup ,first_instance,\n"
    file2 = b"index,q,a,img,url\n1,Q1,A1,images/photo1.png,\n3, q_dup,second_instance,\n"
    
    merged = merge_csv_files([file1, file2], ["file1.csv", "file2.csv"])
    
    assert len(merged) == 3
    
    q1_row = next(r for r in merged if r["q"] == "Q1")
    assert q1_row["source_file"] == "file2.csv"
    
    q_dup_row = next(r for r in merged if r["q"].strip().lower() == "q_dup")
    assert q_dup_row["q"] == "Q_dup"  # 經由 .strip() 後變為 Q_dup
    assert q_dup_row["a"] == "first_instance"
    assert q_dup_row["source_file"] == "file1.csv"
    
    assert not any(r["a"] == "second_instance" for r in merged)


def test_extract_hidden_from_csv():
    qa_csv = _import("knowledge.qa_csv")
    extract_hidden_from_csv = qa_csv.extract_hidden_from_csv

    csv_data = (
        b"q,a,display"
        b"\nQ1,A1,true"
        b"\nQ2,A2,false"
        b"\nQ3,A3,0"
        b"\nQ4,A4"
        b"\nQ5,A5,\xe5\x90\xa6"  # 否 (UTF-8)
    )
    hidden = extract_hidden_from_csv(csv_data)
    assert set(hidden) == {"Q2", "Q3", "Q5"}
