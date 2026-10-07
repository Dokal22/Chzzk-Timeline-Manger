import json
import tempfile
import unittest
from pathlib import Path

from tools import benchmark_manifest


class BenchmarkManifestTest(unittest.TestCase):
    def make_root(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        for vod_id, offset in (("101", 0), ("202", 60)):
            (root / "voicepalette" / f"VOD_{vod_id}").mkdir(parents=True)
            (root / "chat_cache" / vod_id).mkdir(parents=True)
            (root / "voicepalette" / f"VOD_{vod_id}" / "full_raw_script.txt").write_text(
                f"[00:00:01] private stt {vod_id}\n[00:01:01] second\n", encoding="utf-8"
            )
            (root / "chat_cache" / vod_id / f"chat_{vod_id}_full.txt").write_text(
                f"[00:00:02] 🔥 private chat {vod_id}\n[00:01:02] chat\n", encoding="utf-8"
            )
        return temp, root

    def test_deterministic_and_content_free(self):
        temp, root = self.make_root()
        with temp:
            records = benchmark_manifest.build_records(root)
            benchmark_manifest.assign_splits(records)
            first = benchmark_manifest.select_records(records, 4)
            second = benchmark_manifest.select_records(records, 4)
            self.assertEqual(first, second)
            encoded = json.dumps(first, ensure_ascii=False)
            self.assertNotIn("private stt", encoded)
            self.assertNotIn("private chat", encoded)

    def test_split_is_vod_level_and_labels_are_independent(self):
        temp, root = self.make_root()
        with temp:
            records = benchmark_manifest.build_records(root)
            benchmark_manifest.assign_splits(records)
            by_vod = {}
            for record in records:
                by_vod.setdefault(record["vod_id"], set()).add(record["split"])
                self.assertEqual(set(record["labels"]), {
                    "summary_worthiness", "entertainment_value",
                    "acceptable_click_start_seconds", "acceptable_click_end_seconds",
                    "evidence_modality", "confidence", "duplicate_relation",
                    "annotator_id", "notes",
                })
            self.assertTrue(all(len(splits) == 1 for splits in by_vod.values()))
            self.assertEqual({"calibration", "held_out"}, {record["split"] for record in records})


if __name__ == "__main__":
    unittest.main()
