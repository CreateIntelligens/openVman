#!/usr/bin/env python3
"""Keep CHANGELOG.md in one section per day, newest first.

Each `## [YYYY-MM-DD]` section lists its categories once, in the order
Added, Changed, Security, Fixed, Removed, and every entry in it starts with
`**[YYYY-MM-DD]**` of that day. Version sections (`## [0.10.0] - ...`) are
older history and stay as written.

    python3 scripts/check_changelog.py          # check, exit 1 on problems
    python3 scripts/check_changelog.py --fix    # regroup entries in place
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
CATEGORIES = ("Added", "Changed", "Security", "Fixed", "Removed")
# 舊段落用過的分類，--fix 時併進五個標準分類。
LEGACY_CATEGORIES = {
    "Documentation": "Changed",
    "Changed / Fixed": "Changed",
    "Breaking Changes": "Changed",
    "Reliability": "Fixed",
    "Experiments": "Added",
}
DATE_HEADING = re.compile(r"^## \[(\d{4}-\d{2}-\d{2})\]\s*$")
# 舊的版本段落（`## [0.10.0] - 2026-05-25`）照原樣保留；其他寫法都算錯，
# 免得寫錯的日期標題（例如 `## [2026-11-27] - release`）被當成舊段落而略過檢查。
VERSION_HEADING = re.compile(r"^## \[\d+\.\d+\.\d+\](?: - \d{4}-\d{2}-\d{2})?\s*$")
# --fix 會把這種段落的條目分到各自的日期段。
UNDATED_HEADING = re.compile(r"^## \[Unreleased\]\s*$")
ENTRY_DATE = re.compile(r"^- \*\*\[(\d{4}-\d{2}-\d{2})\]\*\*")
# 成對的區塊標記（例如 `<!-- >>> 名稱 -->`）屬於後面那一條。
OPENING_MARKER = re.compile(r"^<!-- >>>")


@dataclass
class Entry:
    lines: list[str]
    category: str
    line_no: int

    @property
    def date(self) -> str | None:
        for line in self.lines:
            if line.startswith("- "):
                match = ENTRY_DATE.match(line)
                return match.group(1) if match else None
        return None

    def text(self) -> str:
        return "\n".join(self.lines).rstrip()


@dataclass
class Section:
    heading: str
    line_no: int
    body: list[str] = field(default_factory=list)

    @property
    def date(self) -> str | None:
        match = DATE_HEADING.match(self.heading)
        return match.group(1) if match else None

    @property
    def regroupable(self) -> bool:
        return self.date is not None or bool(UNDATED_HEADING.match(self.heading))


def split_sections(text: str) -> tuple[list[str], list[Section]]:
    preamble: list[str] = []
    sections: list[Section] = []
    for no, line in enumerate(text.split("\n"), start=1):
        if line.startswith("## "):
            sections.append(Section(line, no))
        elif sections:
            sections[-1].body.append(line)
        else:
            preamble.append(line)
    return preamble, sections


def parse_entries(section: Section) -> tuple[list[str], list[Entry]]:
    """Return (problems, entries) for one dated or undated section."""
    problems: list[str] = []
    entries: list[Entry] = []
    category: str | None = None
    current: Entry | None = None
    pending: list[str] = []
    for offset, line in enumerate(section.body, start=1):
        no = section.line_no + offset
        if line.startswith("### "):
            category = line[4:].strip()
            current = None
            continue
        if line.startswith("- "):
            if category is None:
                problems.append(f"line {no}: entry before any ### category")
                category = "?"
            current = Entry([*pending, line], category, no)
            pending = []
            entries.append(current)
        elif OPENING_MARKER.match(line):
            pending.append(line)
        elif not line.strip():
            if current is not None:
                current.lines.append(line)
        elif current is not None and (line.startswith(" ") or line.startswith("<!--")):
            current.lines.append(line)
        else:
            problems.append(f"line {no}: text outside an entry: {line[:60]!r}")
    if pending:
        problems.append(f"section {section.heading!r}: marker without an entry")
    return problems, entries


def check(text: str) -> list[str]:
    problems: list[str] = []
    _, sections = split_sections(text)
    seen_version = False
    previous_date: str | None = None
    for section in sections:
        if UNDATED_HEADING.match(section.heading):
            problems.append(
                f"line {section.line_no}: [Unreleased] section; put entries under "
                "today's ## [YYYY-MM-DD] (run with --fix)",
            )
            continue
        date = section.date
        if date is None:
            if not VERSION_HEADING.match(section.heading):
                problems.append(
                    f"line {section.line_no}: unrecognized heading {section.heading!r}; "
                    "use ## [YYYY-MM-DD]",
                )
                continue
            seen_version = True
            continue
        if seen_version:
            problems.append(f"line {section.line_no}: date section after version sections")
        if previous_date is not None and date >= previous_date:
            problems.append(
                f"line {section.line_no}: [{date}] must come after (be older than) "
                f"[{previous_date}], one section per day",
            )
        previous_date = date
        parse_problems, entries = parse_entries(section)
        problems.extend(parse_problems)
        headings = [
            line[4:].strip() for line in section.body if line.startswith("### ")
        ]
        for name, count in Counter(headings).items():
            if count > 1:
                problems.append(f"[{date}]: ### {name} appears {count} times")
        unknown = [name for name in headings if name not in CATEGORIES]
        for name in unknown:
            problems.append(f"[{date}]: unknown category ### {name}")
        known = [name for name in headings if name in CATEGORIES]
        if known != sorted(known, key=CATEGORIES.index):
            problems.append(f"[{date}]: categories out of order {known}")
        for entry in entries:
            if entry.date != date:
                problems.append(
                    f"line {entry.line_no}: entry dated {entry.date} in [{date}]",
                )
    return problems


def fix(text: str) -> str:
    preamble, sections = split_sections(text)
    grouped: dict[str, dict[str, list[Entry]]] = {}
    rest: list[Section] = []
    for section in sections:
        if not section.regroupable:
            if not VERSION_HEADING.match(section.heading):
                raise ValueError(
                    f"line {section.line_no}: unrecognized heading {section.heading!r}",
                )
            rest.append(section)
            continue
        problems, entries = parse_entries(section)
        if problems:
            raise ValueError("; ".join(problems))
        for entry in entries:
            if entry.date is None:
                raise ValueError(f"line {entry.line_no}: entry has no **[YYYY-MM-DD]**")
            category = LEGACY_CATEGORIES.get(entry.category, entry.category)
            if category not in CATEGORIES:
                raise ValueError(f"line {entry.line_no}: unknown category {entry.category!r}")
            grouped.setdefault(entry.date, {}).setdefault(category, []).append(entry)
    out = [*preamble]
    while out and not out[-1].strip():
        out.pop()
    out.append("")
    for date in sorted(grouped, reverse=True):
        out += [f"## [{date}]", ""]
        for category in CATEGORIES:
            for i, entry in enumerate(grouped[date].get(category, [])):
                if i == 0:
                    out += [f"### {category}", ""]
                out += [entry.text(), ""]
    for section in rest:
        out += [section.heading, *section.body]
    result = "\n".join(out)
    return result.rstrip("\n") + "\n"


def entry_texts(text: str) -> Counter[str]:
    """All entries of the regroupable sections, for checking --fix keeps them."""
    counter: Counter[str] = Counter()
    for section in split_sections(text)[1]:
        if section.regroupable:
            counter.update(entry.text() for entry in parse_entries(section)[1])
    return counter


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--fix", action="store_true", help="regroup entries in place")
    parser.add_argument("path", nargs="?", type=Path, default=CHANGELOG)
    args = parser.parse_args()
    text = args.path.read_text(encoding="utf-8")
    if args.fix:
        try:
            fixed = fix(text)
        except ValueError as exc:
            print(f"{args.path}: cannot regroup: {exc}", file=sys.stderr)
            return 1
        if entry_texts(fixed) != entry_texts(text):
            print(f"{args.path}: regrouping would change entries; aborted", file=sys.stderr)
            return 1
        args.path.write_text(fixed, encoding="utf-8")
        text = fixed
    problems = check(text)
    for problem in problems:
        print(f"{args.path.name}: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
