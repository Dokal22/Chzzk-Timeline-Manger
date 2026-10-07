import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import annotate_benchmark


class BenchmarkAnnotationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "voicepalette" / "VOD_1").mkdir(parents=True)
        (self.root / "chat_cache" / "1").mkdir(parents=True)
        (self.root / "voicepalette" / "VOD_1" / "full_raw_script.txt").write_text(
            "[00:00:05] setup\n[00:00:35] payoff\n[00:01:05] outside\n", encoding="utf-8"
        )
        (self.root / "chat_cache" / "1" / "chat_1_full.txt").write_text(
            "[00:00:10] chat one\n[00:00:59] chat two\n[00:01:00] outside\n", encoding="utf-8"
        )
        self.record = {
            "window_id": "1:00000000-00000060", "vod_id": "1", "split": "calibration",
            "source": {"stt_path": "voicepalette/VOD_1/full_raw_script.txt", "chat_path": "chat_cache/1/chat_1_full.txt", "start_seconds": 0, "end_seconds": 60},
            "strata": {}, "evidence": {},
        }
        self.manifest = self.root / "manifest.jsonl"
        self.manifest.write_text(json.dumps(self.record) + "\n", encoding="utf-8")
        self.annotations = self.root / "annotations.jsonl"

    def tearDown(self):
        self.temp.cleanup()

    def labels(self, **changes):
        value = {"summary_worthiness": 1, "entertainment_value": 2,
                 "acceptable_click_start_seconds": 5, "acceptable_click_end_seconds": 35,
                 "evidence_modality": "stt+chat", "confidence": "high",
                 "duplicate_relation": "none", "annotator_id": "tester", "notes": "setup-before-apex"}
        value.update(changes)
        return value

    def test_bounded_evidence_does_not_include_outside_window(self):
        evidence = annotate_benchmark.bounded_evidence(self.root, self.record)
        self.assertEqual(evidence["stt"], ["[00:00:05] setup", "[00:00:35] payoff"])
        self.assertEqual(evidence["chat"], ["[00:00:10] chat one", "[00:00:59] chat two"])
        self.assertNotIn("outside", " ".join(evidence["stt"] + evidence["chat"]))

    def test_validation_rejects_bad_enum_interval_duplicate_and_held_out(self):
        by_id = {self.record["window_id"]: self.record}
        for changes in ({"summary_worthiness": 4}, {"acceptable_click_end_seconds": 61}, {"acceptable_click_start_seconds": 40}, {"duplicate_relation": "same_event:missing"}):
            with self.assertRaises(ValueError):
                annotate_benchmark.validate_labels(self.labels(**changes), self.record, by_id)
        held = dict(self.record, split="held_out")
        with self.assertRaises(ValueError):
            annotate_benchmark.validate_labels(self.labels(), held, {held["window_id"]: held})

    def test_save_resume_and_validator(self):
        labels = self.labels()
        annotate_benchmark.validate_labels(labels, self.record, {self.record["window_id"]: self.record})
        row = {"window_id": self.record["window_id"], "record_digest": annotate_benchmark.record_digest(self.record), "labels": labels}
        annotate_benchmark.atomic_write_annotations(self.annotations, {row["window_id"]: row})
        loaded = annotate_benchmark.load_annotations(self.annotations)
        self.assertEqual(loaded[row["window_id"]]["labels"], labels)
        self.assertEqual(annotate_benchmark.validate_annotations(self.manifest, self.annotations, self.root), [])

    def test_held_out_annotation_is_rejected_by_validator(self):
        held = dict(self.record, split="held_out")
        self.manifest.write_text(json.dumps(held) + "\n", encoding="utf-8")
        row = {"window_id": held["window_id"], "record_digest": annotate_benchmark.record_digest(held), "labels": self.labels()}
        annotate_benchmark.atomic_write_annotations(self.annotations, {row["window_id"]: row})
        errors = annotate_benchmark.validate_annotations(self.manifest, self.annotations, self.root)
        self.assertTrue(any("held-out" in error for error in errors))

    def test_vod_url_uses_window_start(self):
        self.assertEqual(
            annotate_benchmark.vod_url(self.record),
            "https://chzzk.naver.com/video/1?currentTime=0",
        )

    @patch("tools.annotate_benchmark.webbrowser.open_new_tab", return_value=True)
    def test_open_vod_is_mockable(self, opener):
        url, opened = annotate_benchmark.open_vod(self.record)
        self.assertTrue(opened)
        self.assertEqual(url, "https://chzzk.naver.com/video/1?currentTime=0")
        opener.assert_called_once_with(url)

    @patch("tools.annotate_benchmark.webbrowser.open_new_tab", side_effect=RuntimeError("no browser"))
    def test_open_vod_failure_is_non_destructive(self, opener):
        url, opened = annotate_benchmark.open_vod(self.record)
        self.assertFalse(opened)
        self.assertIn("currentTime=0", url)


if __name__ == "__main__":
    unittest.main()
