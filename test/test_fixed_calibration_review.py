import unittest
import hashlib
import json
import tempfile
from pathlib import Path

from tools.benchmark_manifest import build_records, paired_artifacts
from tools.fixed_calibration_manifest import ROLES, select_fixed
from tools.review_calibration import build_review, evidence_for, html_page
from tools.annotate_benchmark import record_digest


class FixedCalibrationReviewTests(unittest.TestCase):
    def test_local_fixed_frame_has_twelve_deterministic_role_windows_and_hashes(self):
        root = Path.cwd().resolve()
        paired = {vod for vod, _, _ in paired_artifacts(root)}
        records = [r for r in build_records(root) if r["vod_id"] in paired]
        first = select_fixed(records, root)
        second = select_fixed(records, root)
        self.assertEqual([r["window_id"] for r in first], [r["window_id"] for r in second])
        self.assertEqual(len(first), 12)
        self.assertEqual(len({r["vod_id"] for r in first}), 2)
        self.assertTrue(all(r["split"] == "calibration" for r in first))
        for vod in {r["vod_id"] for r in first}:
            self.assertEqual({role for r in first if r["vod_id"] == vod for role in r["selection_roles"]}, set(ROLES))
            self.assertTrue(all(set(r["source_hashes"]) == {"stt_sha256", "chat_sha256"} for r in first if r["vod_id"] == vod))
            self.assertTrue(all(r["labels"]["summary_worthiness"] is None for r in first if r["vod_id"] == vod))

    def test_review_page_distinguishes_absent_labels_and_uses_exact_row_seconds(self):
        root = Path.cwd().resolve()
        manifest = root / "experiment_artifacts/ca002_review/manifest.jsonl"
        audit = root / "experiment_artifacts/ca003_audit_v2/candidate_audit.json"
        annotations = root / "experiment_artifacts/ca002_review/annotations.jsonl"
        if not manifest.is_file() or not audit.is_file():
            self.skipTest("local manifests/audit have not been generated")
        data = build_review(root, manifest, annotations, audit)
        self.assertFalse(data["annotation_file_exists"])
        self.assertTrue(all(row["label_status"] == "annotation_file_absent" for row in data["windows"]))
        page = html_page(data)
        self.assertIn("currentTime=${x.seconds}", page)
        self.assertIn("자동 라벨은 없습니다", page)
        data["windows"][0]["stt"]["lines"][0]["text"] = "</script><img src=x>"
        page = html_page(data)
        self.assertNotIn("</script><img", page)
        self.assertIn("\\u003c/script\\u003e", page)

    def test_evidence_display_reports_line_truncation(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "stt.txt"
            source.write_text("[00:00:01] first\n[00:00:02] second\n", encoding="utf-8")
            record = {"source": {"stt_path": "stt.txt", "start_seconds": 0, "end_seconds": 60}}
            bounded = evidence_for(root, record, "stt", line_cap=1)
            self.assertEqual(len(bounded["lines"]), 1)
            self.assertTrue(bounded["truncated"])

    def test_review_displays_only_digest_valid_existing_label(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "voicepalette/VOD_111").mkdir(parents=True)
            (root / "chat_cache/111").mkdir(parents=True)
            stt = root / "voicepalette/VOD_111/full_raw_script.txt"
            chat = root / "chat_cache/111/chat_111_full.txt"
            stt.write_text("[01:23:32] 합법적 근거\n", encoding="utf-8")
            chat.write_text("[01:23:32] 🔥 반응\n", encoding="utf-8")
            source = {"stt_path": "voicepalette/VOD_111/full_raw_script.txt", "chat_path": "chat_cache/111/chat_111_full.txt", "start_seconds": 4980, "end_seconds": 5040}
            hashes = {"stt_sha256": hashlib.sha256(stt.read_bytes()).hexdigest(), "chat_sha256": hashlib.sha256(chat.read_bytes()).hexdigest()}
            record = {"window_id": "111:00004980-00005040", "vod_id": "111", "split": "calibration", "source": source, "source_hashes": hashes, "strata": {}, "selection_roles": ["middle"]}
            records = [record]
            for i in range(1, 6):
                start = 5040 + i * 60
                records.append({**record, "window_id": f"111:{start:08d}-{start+60:08d}",
                                "source": {**source, "start_seconds": start, "end_seconds": start + 60},
                                "selection_roles": ["fixed_test"]})
            manifest = root / "manifest.jsonl"
            manifest.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
            labels = {"summary_worthiness": 1, "entertainment_value": 2, "acceptable_click_start_seconds": 5012,
                      "acceptable_click_end_seconds": 5012, "evidence_modality": "stt+chat", "confidence": "high",
                      "duplicate_relation": "none", "annotator_id": "reviewer", "notes": "supported"}
            annotation_path = root / "annotations.jsonl"
            annotation_path.write_text(json.dumps({"window_id": record["window_id"], "record_digest": record_digest(record), "labels": labels}) + "\n", encoding="utf-8")
            audit = root / "audit.json"
            audit.write_text(json.dumps({"schema_version": 2, "candidates": [], "matching_policy": "text/time only"}), encoding="utf-8")
            data = build_review(root, manifest, annotation_path, audit)
            self.assertEqual(data["windows"][0]["source_status"], "verified")
            self.assertEqual(data["windows"][0]["label_status"], "labeled")
            self.assertEqual(data["windows"][0]["labels"], labels)
            self.assertTrue(any(line["seconds"] == 5012 for line in data["windows"][0]["stt"]["lines"]))


if __name__ == "__main__":
    unittest.main()
