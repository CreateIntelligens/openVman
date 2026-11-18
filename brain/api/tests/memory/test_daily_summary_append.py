"""Daily memory summaries are appended, and duplicate checks read only what was added since last time."""

from __future__ import annotations

from pathlib import Path

import pytest

from memory import memory_governance as governance


@pytest.fixture(autouse=True)
def fresh_index():
    governance._daily_scans.clear()
    yield
    governance._daily_scans.clear()


def _block(fingerprint: str) -> str:
    return f"## t | session s\n\n- fingerprint: {fingerprint}\n\n### Summary\nUser: q\nAssistant: a\n"


def test_appending_keeps_earlier_bytes_and_adds_the_section_once(tmp_path: Path):
    daily = tmp_path / "2026-11-18.md"
    daily.write_text("# 2026-11-18 對話日誌\n\n## 10:00 | session a\n\n### User\nhi\n\n", encoding="utf-8")
    before = daily.read_bytes()

    governance._append_summary_block(daily, _block("aaaaaaaaaaaa"))
    governance._append_summary_block(daily, _block("bbbbbbbbbbbb"))

    after = daily.read_text(encoding="utf-8")
    assert daily.read_bytes().startswith(before)
    assert after.count(governance._SUMMARY_SECTION_HEADER) == 1
    assert after.index("aaaaaaaaaaaa") < after.index("bbbbbbbbbbbb")


def test_duplicates_written_by_another_process_are_still_found(tmp_path: Path):
    daily = tmp_path / "2026-11-18.md"
    governance._append_summary_block(daily, _block("aaaaaaaaaaaa"))
    assert governance._daily_file_has_fingerprint(daily, "aaaaaaaaaaaa" + "f" * 52)

    # 另一個 worker 直接接在檔尾；這個 process 的索引還沒看過這段。
    with daily.open("a", encoding="utf-8") as handle:
        handle.write("\n" + _block("cccccccccccc"))

    assert governance._daily_file_has_fingerprint(daily, "cccccccccccc" + "0" * 52)
    assert not governance._daily_file_has_fingerprint(daily, "dddddddddddd" + "0" * 52)


def test_a_replaced_file_is_scanned_from_the_start(tmp_path: Path):
    daily = tmp_path / "2026-11-18.md"
    governance._append_summary_block(daily, _block("aaaaaaaaaaaa"))
    assert governance._daily_file_has_fingerprint(daily, "aaaaaaaaaaaa" + "0" * 52)

    # 歸檔後重建：換了一個檔案，舊的指紋不能再算數。
    daily.rename(tmp_path / "archived.md")
    daily.write_text("# 2026-11-18 對話日誌\n\n", encoding="utf-8")

    assert not governance._daily_file_has_fingerprint(daily, "aaaaaaaaaaaa" + "0" * 52)
    governance._append_summary_block(daily, _block("bbbbbbbbbbbb"))
    assert daily.read_text(encoding="utf-8").count(governance._SUMMARY_SECTION_HEADER) == 1


def test_a_file_rewritten_in_place_is_scanned_from_the_start(tmp_path: Path):
    # 刪掉重建時 inode 可能剛好重用；內容對不上就不能從舊位置接著讀。
    daily = tmp_path / "2026-11-18.md"
    governance._append_summary_block(daily, _block("aaaaaaaaaaaa"))
    assert governance._daily_file_has_fingerprint(daily, "aaaaaaaaaaaa" + "0" * 52)

    with daily.open("r+", encoding="utf-8") as handle:
        handle.truncate(0)
        handle.write("# 2026-11-18 對話日誌\n\n" + "## 10:00 | session x\n\n### User\n" + "嗨" * 200 + "\n\n")

    assert not governance._daily_file_has_fingerprint(daily, "aaaaaaaaaaaa" + "0" * 52)
    governance._append_summary_block(daily, _block("bbbbbbbbbbbb"))
    assert daily.read_text(encoding="utf-8").count(governance._SUMMARY_SECTION_HEADER) == 1
