import json
import tempfile
import unittest
from pathlib import Path

from tools.feedback_log import add_feedback, load_rows, sha256
from tools.selection_trial import load_production_merge, run_trial


ROOT = Path(__file__).resolve().parents[1]


class FeedbackLogTests(unittest.TestCase):
    def test_append_links_hash_and_preserves_original_record(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            artifact, log = root / "result.txt", root / "feedback.jsonl"
            artifact.write_text("draft", encoding="utf-8")
            first = add_feedback(log, artifact, "중복 항목을 줄여주세요", vod_id="123", timestamp="00:01:02")
            artifact.write_text("changed", encoding="utf-8")
            second = add_feedback(log, artifact, "시점을 조금 앞당겨주세요", candidate_id="cand-2")
            rows = load_rows(log)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["artifact_sha256"], first["artifact_sha256"])
            self.assertEqual(rows[1]["artifact_sha256"], sha256(artifact))
            self.assertIsNone(rows[0]["quality_label"])
            self.assertNotEqual(first["feedback_id"], second["feedback_id"])

    def test_empty_feedback_rejected_without_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            artifact = Path(temp) / "result.txt"
            artifact.write_text("draft", encoding="utf-8")
            with self.assertRaises(ValueError):
                add_feedback(Path(temp) / "f.jsonl", artifact, "  ")


class SelectionTrialTests(unittest.TestCase):
    def test_deterministic_and_rendered_budget_is_inclusive(self):
        audit = {"matching_policy": "compatible_unbound is not provenance",
                 "candidates": [
                     {"candidate_id": "low", "vod_id": "123", "seconds": 20, "timestamp": "00:00:20",
                      "group_large": "게임", "topic": "보스", "content": "짧은 사건", "raw_score": {"wf": 10, "wi": 30},
                      "raw": {"sha256": "a", "path": "raw.json", "item_index": 0},
                      "associations": [{"claimed_vod_id": "123", "compatibility_status": "compatible_unbound"}]},
                     {"candidate_id": "high", "vod_id": "123", "seconds": 40, "timestamp": "00:00:40",
                      "group_large": "게임", "topic": "보스", "content": "반응이 큰 사건", "raw_score": {"wf": 45, "wi": 30},
                      "raw": {"sha256": "b", "path": "raw2.json", "item_index": 0},
                      "associations": [{"claimed_vod_id": "123", "compatibility_status": "compatible_unbound"}]},
                     {"candidate_id": "unbound", "vod_id": "123", "seconds": 50, "timestamp": "00:00:50",
                      "content": "exclude", "raw_score": {"wf": 50, "wi": 50}, "raw": {},
                      "associations": [{"claimed_vod_id": "123", "compatibility_status": "conflicting"}]}]}
        merge = load_production_merge(ROOT / "src/code/Timeline.py")
        wide = run_trial(audit, "123", "테스트 방송", merge, 5000)
        repeat = run_trial(audit, "123", "테스트 방송", merge, 5000)
        self.assertEqual(wide["alternative"]["text"], repeat["alternative"]["text"])
        self.assertEqual(wide["pool_sha256"], repeat["pool_sha256"])
        self.assertEqual(wide["renderer"]["mode"], "exact_merge_function_plus_Main.py_notice_and_title")
        narrow = run_trial(audit, "123", "테스트 방송", merge, len(wide["alternative"]["text"]) - 1)
        self.assertLessEqual(narrow["alternative"]["rendered_characters"], narrow["budget"]["limit"])
        self.assertIn("unbound", narrow["excluded_unbound_candidate_ids"])
        self.assertIsNone(narrow["quality_claim"])


if __name__ == "__main__":
    unittest.main()
