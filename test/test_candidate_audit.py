import json
import tempfile
import unittest
from pathlib import Path

from tools.candidate_audit import build_audit, numeric_eligible, safe_path


class CandidateAuditV2Tests(unittest.TestCase):
    def test_numeric_filter_is_compared_to_returned_count_not_raw_count(self):
        self.assertTrue(numeric_eligible({"wf": 8, "wi": 32}))
        self.assertFalse(numeric_eligible({"wf": 18, "wi": 12}))
        self.assertFalse(numeric_eligible({"wf": True, "wi": 0}))

    def test_same_raw_item_is_unique_but_run_associations_stay_separate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "experiment_artifacts").mkdir()
            (root / "out_a.txt").write_text("[00:00:10] 문서와 일치하는 사건\n", encoding="utf-8")
            (root / "out_b.txt").write_text("[00:00:10] 다른 결과\n", encoding="utf-8")
            raw = root / "experiment_artifacts" / "chunk_0000.json"
            items = [
                {"group_large": "방송", "topic": "주제", "timestamp": "00:00:10", "wf": 10, "wi": 30, "content": "문서와 일치하는 사건"},
                {"group_large": "방송", "topic": "주제", "timestamp": "00:00:11", "wf": 20, "wi": 25, "content": "문서와 일치하는 사건"},
                {"group_large": "방송", "topic": "주제", "timestamp": "00:00:20", "wf": 5, "wi": 5, "content": "낮은 점수"},
            ]
            raw.write_text(json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")
            metadata = []
            for name, vod, out, returned in (("a", "111", "out_a.txt", 2), ("b", "222", "out_b.txt", 4)):
                path = root / f"{name}.metadata.json"
                path.write_text(json.dumps({"experiment": "t1", "vod_id": vod, "title": name,
                    "output_path": str(root / out), "chunks": [{"chunk_index": 0, "start_sec": 0, "end_sec": 60,
                    "raw_output_path": str(raw), "item_count": returned}]}), encoding="utf-8")
                metadata.append(path)
            report = build_audit(root, metadata)
            self.assertEqual(report["candidate_count"], 3)
            self.assertEqual(report["raw_candidate_count"], 3)
            eligible = next(c for c in report["candidates"] if c["raw_score"]["wi"] == 30)
            self.assertEqual({a["compatibility_status"] for a in eligible["associations"]}, {"compatible_unbound", "conflicting"})
            self.assertEqual(eligible["vod_id"], "111")
            overlapping = [c for c in report["candidates"] if c["content"] == "문서와 일치하는 사건"]
            run_a = [a for c in overlapping for a in c["associations"] if a["metadata_path"] == "a.metadata.json"]
            self.assertTrue(all(a["output_match"]["status"] == "ambiguous" for a in run_a))
            self.assertFalse(run_a[0]["output_match"]["event_identity_verified"])

    def test_count_agreement_is_not_provenance_verification_and_missing_count_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / "raw.json"
            raw.write_text(json.dumps({"items": [{"timestamp": "00:00:10", "wf": 50, "wi": 1, "content": "x"}]}), encoding="utf-8")
            meta = root / "m.json"
            meta.write_text(json.dumps({"experiment": "t1", "vod_id": "1", "chunks": [{"chunk_index": 0, "raw_output_path": str(raw)}]}), encoding="utf-8")
            report = build_audit(root, [meta])
            self.assertEqual(report["candidates"][0]["associations"][0]["compatibility_status"], "unknown")
            self.assertIsNone(report["candidates"][0]["vod_id"])

    def test_safe_path_rejects_root_escape(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                safe_path(Path(td), "../outside.json")


if __name__ == "__main__":
    unittest.main()
