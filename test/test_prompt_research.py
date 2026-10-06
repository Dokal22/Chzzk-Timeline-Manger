import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE = Path(__file__).parents[1] / "src" / "code" / "prompt_research.py"
SPEC = importlib.util.spec_from_file_location("prompt_research_test", MODULE)
RESEARCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RESEARCH)


class ResearchRecorderTest(unittest.TestCase):
    def test_disabled_recorder_writes_nothing(self):
        with tempfile.TemporaryDirectory() as root:
            recorder = RESEARCH.ResearchRecorder(root)
            recorder.start(False)
            recorder.record("timeline", "private stt", "prompt", "raw", "clean")
            self.assertFalse((Path(root) / "prompt_research").exists())

    def test_enabled_record_preserves_provenance_and_outputs(self):
        with tempfile.TemporaryDirectory() as root:
            recorder = RESEARCH.ResearchRecorder(root)
            recorder.start(True, vod_id="42")
            recorder.record("timeline", "same input", "version A", "raw JSON", [{"content": "clean"}],
                            model_requested="", prompt_versions=[{"id": "x", "version": 2}], schema={"type": "object"})
            path = Path(root) / "prompt_research" / f"{recorder.run_id}.json"
            row = json.loads(path.read_text(encoding="utf-8"))[0]
            self.assertEqual("unknown (CLI default)", row["model_actual"])
            self.assertEqual("raw JSON", row["raw_output"])
            self.assertEqual([{"content": "clean"}], row["processed_output"])
            self.assertEqual(RESEARCH.sha256("same input"), row["input_sha256"])


if __name__ == "__main__":
    unittest.main()
