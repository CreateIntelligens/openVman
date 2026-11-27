"""CHANGELOG.md stays one section per day with each category listed once."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "check_changelog", ROOT / "scripts" / "check_changelog.py",
)
check_changelog = importlib.util.module_from_spec(SPEC)
# dataclass 需要在 sys.modules 找得到模組。
sys.modules[SPEC.name] = check_changelog
SPEC.loader.exec_module(check_changelog)

GOOD = """# Changelog

## [2026-11-27]

### Added

- **[2026-11-27]** new thing
  - detail

### Fixed

- **[2026-11-27]** fixed thing

## [2026-11-26]

### Changed

- **[2026-11-26]** older change

## [0.1.0] - 2026-03-11

### Added
- legacy entry without a date
### Added
- legacy sections are not checked
"""


def test_repository_changelog_passes():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert check_changelog.check(text) == []


def test_well_formed_changelog_passes():
    assert check_changelog.check(GOOD) == []


@pytest.mark.parametrize("broken, message", [
    (GOOD.replace("### Fixed\n\n- **[2026-11-27]** fixed thing",
                  "### Added\n\n- **[2026-11-27]** fixed thing"),
     "### Added appears 2 times"),
    (GOOD.replace("### Added\n\n- **[2026-11-27]** new thing\n  - detail\n\n"
                  "### Fixed\n\n- **[2026-11-27]** fixed thing",
                  "### Fixed\n\n- **[2026-11-27]** fixed thing\n\n"
                  "### Added\n\n- **[2026-11-27]** new thing"),
     "categories out of order"),
    (GOOD.replace("- **[2026-11-26]** older change", "- **[2026-11-25]** older change"),
     "entry dated 2026-11-25 in [2026-11-26]"),
    (GOOD.replace("## [2026-11-26]", "## [2026-11-28]")
         .replace("**[2026-11-26]**", "**[2026-11-28]**"),
     "must come after"),
    (GOOD.replace("## [2026-11-27]", "## [Unreleased]"), "[Unreleased] section"),
    (GOOD.replace("### Fixed", "### Documentation"), "unknown category"),
    (GOOD.replace("## [2026-11-26]", "## [2026-11-26] - release")
         .replace("- **[2026-11-26]** older change", "- undated entry"),
     "unrecognized heading"),
    (GOOD.replace("## [0.1.0] - 2026-03-11", "## Notes"), "unrecognized heading"),
])
def test_layout_problems_are_reported(broken, message):
    problems = check_changelog.check(broken)
    assert any(message in problem for problem in problems), problems


def test_fix_regroups_by_day_and_keeps_every_entry():
    messy = """# Changelog

## [Unreleased]

### Fixed

- **[2026-11-26]** fix on the 26th

- **[2026-11-27]** fix on the 27th
  - with detail

### Added

<!-- >>> marker -->
- **[2026-11-27]** added on the 27th
<!-- <<< marker -->

### Fixed

- **[2026-11-27]** second fix block

## [2026-10-08]

### Documentation
- **[2026-10-08]** docs entry
### Reliability
- **[2026-10-07]** reliability entry

## [0.1.0] - 2026-03-11

### Added
- legacy
"""
    fixed = check_changelog.fix(messy)
    assert check_changelog.check(fixed) == []
    assert check_changelog.entry_texts(fixed) == check_changelog.entry_texts(messy)
    assert fixed.index("added on the 27th") < fixed.index("fix on the 27th")
    assert fixed.index("fix on the 27th") < fixed.index("second fix block")
    assert "<!-- >>> marker -->\n- **[2026-11-27]** added on the 27th" in fixed
    assert "### Changed\n\n- **[2026-10-08]** docs entry" in fixed
    assert "## [2026-10-07]\n\n### Fixed\n\n- **[2026-10-07]** reliability" in fixed
    assert fixed.endswith("## [0.1.0] - 2026-03-11\n\n### Added\n- legacy\n")
    assert check_changelog.fix(fixed) == fixed


def test_fix_refuses_an_unrecognized_heading():
    with pytest.raises(ValueError, match="unrecognized heading"):
        check_changelog.fix(GOOD.replace("## [2026-11-26]", "## [2026-11-26] - release"))


def test_fix_refuses_an_undated_entry():
    with pytest.raises(ValueError, match="no \\*\\*\\[YYYY-MM-DD\\]\\*\\*"):
        check_changelog.fix(GOOD.replace("- **[2026-11-26]** older", "- older"))
