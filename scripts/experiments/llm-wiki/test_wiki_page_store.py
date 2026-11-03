"""Synthetic whole-page reads with the real source-admission contract."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from repaired_retrieval import validate_sections
from wiki_page_store import TOOL_NAME, TOOL_SCHEMA, WikiPageError, WikiPageStore


class WikiPageStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.corpus = self.root / "corpus"
        (self.corpus / "wiki").mkdir(parents=True)
        (self.root / "knowledge").mkdir()
        self.project = "synthetic-project"
        self.persona = "synthetic-persona"
        self.sections = []
        self.manifest = {"project_id": self.project, "sources": {}}
        self.disabled = []
        self.personas = {}
        self.calls = []
        for index in range(1, 5):
            self.add_section(index, index)
        self.write_metadata()

    def add_section(self, section_number, page_number):
        source_path = f"knowledge/source-{section_number}.md"
        source = self.root / source_path
        source.write_text(f"Original synthetic unit {section_number}.")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        ref = f"u{section_number:05d}"
        self.manifest["sources"][source_path] = {
            "persona_id": self.persona, "sha256": digest, "refs": [ref],
        }
        self.personas[source_path] = [self.persona]
        section = {
            "id": f"section-{section_number:04d}",
            "compile_page": f"page-{page_number:05d}",
            "title": f"Synthetic title {page_number}",
            "project_id": self.project, "persona_id": self.persona,
            "text": f"Complete fact {section_number} [{ref}].",
            "markdown": f"Complete fact {section_number} [{ref}].",
            "source_paths": [source_path], "source_refs": [ref],
            "source_hashes": {source_path: digest},
            "payload_sha256": hashlib.sha256(str(section_number).encode()).hexdigest(),
        }
        self.sections.append(section)
        path = self.corpus / "wiki" / (section["compile_page"] + ".md")
        if path.exists():
            with path.open("a") as stream:
                stream.write("\n## Another section\n\n" + section["text"] + "\n")
        else:
            path.write_text(
                "<!-- Candidate warning -->\n\n# " + section["title"]
                + "\n\n" + section["text"] + "\n"
            )

    def write_metadata(self):
        (self.corpus / "compiled_sections.json").write_text(json.dumps(self.sections))

    def validate(self, sections):
        self.calls.append(copy.deepcopy(sections))
        return validate_sections(
            sections, self.manifest, project_id=self.project,
            persona_id=self.persona, workspace_root=self.root,
            disabled_paths=self.disabled, current_source_personas=self.personas,
        )

    def store(self, **overrides):
        arguments = {
            "project_id": self.project, "persona_id": self.persona,
            "validator": self.validate,
        }
        arguments.update(overrides)
        return WikiPageStore.from_directory(self.corpus, **arguments)

    def test_entire_page_including_warning_unicode_and_tail_is_never_cut(self):
        path = self.corpus / "wiki/page-00001.md"
        path.write_text(path.read_text() + "\n" + "完整內容\n" * 9000 + "END\r\n")
        expected = path.read_bytes().decode()
        row = self.store().new_question().read_wiki_page("page-00001")["results"][0]
        self.assertEqual(row["text"], expected)
        self.assertGreater(len(row["text"]), 8000)
        self.assertTrue(row["text"].endswith("END\r\n"))
        self.assertEqual(row["page_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(row["payload_sha256"], {
            self.sections[0]["id"]: self.sections[0]["payload_sha256"],
        })
        self.assertEqual(row["project_id"], self.project)
        self.assertEqual(row["persona_id"], self.persona)

    def test_directory_contains_only_fixed_ids_and_existing_titles(self):
        store = self.store()
        catalog = store.catalog()
        self.assertEqual(len(catalog), 4)
        self.assertTrue(all(set(page) == {"page_id", "title"} for page in catalog))
        serialized = json.dumps(catalog)
        for forbidden in ("Complete fact", "Original synthetic", "source_refs", "knowledge/"):
            self.assertNotIn(forbidden, serialized)
        catalog[0]["title"] = "changed by caller"
        self.assertEqual(store.catalog()[0]["title"], "Synthetic title 1")
        self.assertEqual(self.calls, [])

    def test_unknown_ids_and_paths_never_reach_validator(self):
        session = self.store().new_question()
        for page_id in ("unknown", "../page-00001", "/etc/passwd", "wiki/page-00001.md",
                        "page-00001.md", "page-00001\\suffix", [], None):
            with self.subTest(page_id=page_id), self.assertRaises(WikiPageError):
                session.read_wiki_page(page_id)
        self.assertEqual(self.calls, [])
        self.assertEqual(session.read_page_ids, ())

    def test_cross_project_or_persona_store_is_rejected(self):
        for field in ("project_id", "persona_id"):
            with self.subTest(field=field), self.assertRaises(WikiPageError):
                self.store(**{field: "foreign-synthetic-scope"})
        self.sections[-1]["project_id"] = "foreign-synthetic-scope"
        self.write_metadata()
        with self.assertRaisesRegex(WikiPageError, "cross_project"):
            self.store()

    def test_disabled_source_blocks_first_read_and_reread(self):
        session = self.store().new_question()
        session.read_wiki_page("page-00001")
        self.disabled.append(self.sections[0]["source_paths"][0])
        with self.assertRaisesRegex(WikiPageError, "wiki_source_denied"):
            session.read_wiki_page("page-00001")
        fresh = self.store().new_question()
        with self.assertRaises(WikiPageError):
            fresh.read_wiki_page("page-00001")
        self.assertEqual(fresh.read_page_ids, ())

    def test_changed_source_fails_live_hash_validation(self):
        session = self.store().new_question()
        path = self.root / self.sections[0]["source_paths"][0]
        path.write_text("Source changed after store construction")
        with self.assertRaisesRegex(WikiPageError, "wiki_source_denied"):
            session.read_wiki_page("page-00001")

    def test_changed_source_persona_and_removed_ref_are_denied(self):
        path = self.sections[0]["source_paths"][0]
        session = self.store().new_question()
        self.personas[path] = ["foreign-synthetic-persona"]
        with self.assertRaises(WikiPageError):
            session.read_wiki_page("page-00001")
        self.personas[path] = [self.persona]
        self.manifest["sources"][path]["refs"] = []
        with self.assertRaises(WikiPageError):
            session.read_wiki_page("page-00001")

    def test_three_different_pages_per_question_with_unlimited_consistent_rereads(self):
        store = self.store()
        session = store.new_question()
        first = session.read_wiki_page("page-00001")
        first["results"][0]["text"] = "caller mutation"
        for page_id in ("page-00002", "page-00003"):
            session.read_wiki_page(page_id)
        reread = session.read_wiki_page("page-00001")
        self.assertNotEqual(reread["results"][0]["text"], "caller mutation")
        self.assertEqual(reread, session.read_wiki_page("page-00001"))
        self.assertEqual(len(self.calls), 5)
        with self.assertRaisesRegex(WikiPageError, "wiki_page_budget_exceeded"):
            session.read_wiki_page("page-00004")
        self.assertEqual(len(self.calls), 5)
        self.assertEqual(len(session.read_page_ids), 3)
        store.new_question().read_wiki_page("page-00004")

    def test_many_sections_on_one_page_are_all_validated_and_returned_once(self):
        self.add_section(5, 1)
        self.write_metadata()
        session = self.store().new_question()
        row = session.read_wiki_page("page-00001")["results"][0]
        self.assertEqual(row["section_ids"], ["section-0001", "section-0005"])
        self.assertEqual(row["source_refs"], ["u00001", "u00005"])
        self.assertEqual(len(row["source_paths"]), 2)
        self.assertEqual(len(row["payload_sha256"]), 2)
        self.assertEqual(len(self.calls[0]), 2)
        self.assertIn("Complete fact 1", row["text"])
        self.assertIn("Complete fact 5", row["text"])
        self.disabled.append(self.sections[-1]["source_paths"][0])
        with self.assertRaises(WikiPageError):
            session.read_wiki_page("page-00001")

    def test_page_change_and_symlink_are_rejected(self):
        session = self.store().new_question()
        path = self.corpus / "wiki/page-00001.md"
        path.write_text(path.read_text() + "new content")
        with self.assertRaisesRegex(WikiPageError, "wiki_page_changed"):
            session.read_wiki_page("page-00001")
        path.unlink()
        path.symlink_to(self.corpus / "wiki/page-00002.md")
        with self.assertRaisesRegex(WikiPageError, "wiki_path_denied"):
            session.read_wiki_page("page-00001")

    def test_arbitrary_path_in_metadata_is_rejected(self):
        self.sections[0]["compile_page"] = "../outside"
        self.write_metadata()
        with self.assertRaises(WikiPageError):
            self.store()

    def test_partial_validation_and_exceptions_fail_closed_without_details(self):
        partial = self.store(validator=lambda rows: (rows[:-1], []))
        with self.assertRaisesRegex(WikiPageError, "wiki_source_denied"):
            partial.new_question().read_wiki_page("page-00001")

        def broken(rows):
            raise RuntimeError("synthetic private source detail")

        with self.assertRaises(WikiPageError) as failure:
            self.store(validator=broken).new_question().read_wiki_page("page-00001")
        self.assertNotIn("private", str(failure.exception))

    def test_tool_schema_and_handler_disallow_question_and_scope_overrides(self):
        self.assertEqual(TOOL_NAME, "read_wiki_page")
        parameters = TOOL_SCHEMA["function"]["parameters"]
        self.assertEqual(parameters["required"], ["page_id"])
        self.assertFalse(parameters["additionalProperties"])
        session = self.store().new_question()
        for extra in ("query", "project_id", "persona_id", "path", "max_chars"):
            with self.subTest(extra=extra), self.assertRaises(WikiPageError):
                session.handle({"page_id": "page-00001", extra: "forbidden"})
        self.assertEqual(len(session.handle({"page_id": "page-00001"})["results"]), 1)


if __name__ == "__main__":
    unittest.main()
