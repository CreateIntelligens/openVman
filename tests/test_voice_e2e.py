"""Scoring and case-file checks for the simulated voice-turn harness."""

from __future__ import annotations

import io
import unittest
import wave
from pathlib import Path

from scripts.voice_e2e.run import cer, load_cases, summarize, terms_heard, wav_bytes

CASES_DIR = Path(__file__).resolve().parents[1] / "scripts" / "voice_e2e" / "cases"


class ScoringTest(unittest.TestCase):
    def test_punctuation_width_and_case_do_not_count_as_errors(self):
        self.assertEqual(cer("請問 DIVA 有攪拌器嗎？", "請問diva有攪拌器嗎?"), 0.0)

    def test_variant_characters_are_not_mishearings(self):
        self.assertEqual(cer("HIPPO 污水泵", "HIPPO汙水泵"), 0.0)
        self.assertEqual(terms_heard(["污水泵"], "HIPPO汙水泵"), ["污水泵"])

    def test_one_wrong_character_in_ten(self):
        self.assertAlmostEqual(cer("沉水泵最深可以放多深", "沉睡泵最深可以放多深"), 0.1)

    def test_empty_transcript_is_all_wrong(self):
        self.assertEqual(cer("沉水泵", ""), 1.0)

    def test_terms_accept_any_listed_spelling(self):
        self.assertEqual(terms_heard(["自動著脫裝置|自動脫著裝置", "EUBL"], "自動脫著裝置 UBL"),
                         ["自動著脫裝置|自動脫著裝置"])

    def test_wav_wraps_pcm_at_16k_mono(self):
        with wave.open(io.BytesIO(wav_bytes(b"\0\0" * 160))) as handle:
            self.assertEqual((handle.getframerate(), handle.getnchannels(), handle.getnframes()),
                             (16000, 1, 160))

    def test_summary_groups_by_voice_and_path_and_skips_failures(self):
        ok = {"text": "x", "cer": 0.2, "terms_ok": True, "asr_ms": 900, "chat_ms": 5000, "reply_ok": True}
        rows = [
            {"voice": "v", "terms": ["DIVA"], "stream": ok, "batch": {"error": "HTTP 500"}},
            {"voice": "v", "terms": [], "stream": {**ok, "cer": 0.4, "asr_ms": None}},
            {"voice": "v", "terms": [], "error": "speech failed"},
        ]
        by_path = {s["path"]: s for s in summarize(rows)}
        self.assertEqual(by_path["stream"]["cases"], 2)
        self.assertAlmostEqual(by_path["stream"]["mean_cer"], 0.3)
        self.assertEqual(by_path["stream"]["terms_ok"], "1/1")
        self.assertEqual(by_path["stream"]["asr_ms"], 900)
        self.assertEqual(by_path["batch"]["failed"], 1)


class CaseFilesTest(unittest.TestCase):
    def test_every_case_file_loads_with_unique_ids(self):
        files = sorted(CASES_DIR.glob("*.json"))
        self.assertTrue(files)
        for path in files:
            with self.subTest(path.name):
                cases, data = load_cases(path, [])
                self.assertTrue(data.get("project_id"))
                self.assertEqual(len({c.id for c in cases}), len(cases))
                for voice in data.get("voices", []):
                    self.assertIn(":", voice)

    def test_only_filters_by_id_pattern(self):
        cases, _ = load_cases(CASES_DIR / "heji.json", ["^diva", "eubl"])
        self.assertEqual([c.id for c in cases], ["diva-agitator", "eubl-hp"])


if __name__ == "__main__":
    unittest.main()
