import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest import mock


CODE = Path(__file__).parents[1] / "src" / "code"
sys.path.insert(0, str(CODE))


def load_timeline():
    requests = types.ModuleType("requests"); requests.RequestException = Exception
    yt_dlp = types.ModuleType("yt_dlp"); yt_dlp.YoutubeDL = object
    pydantic = types.ModuleType("pydantic"); pydantic.BaseModel = object; pydantic.ConfigDict = dict; pydantic.Field = lambda *a, **k: None
    sys.modules.setdefault("requests", requests); sys.modules.setdefault("yt_dlp", yt_dlp); sys.modules.setdefault("pydantic", pydantic)
    path = CODE / "Timeline.py"
    spec = importlib.util.spec_from_file_location("timeline_nickname_correction_validation", path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


class NicknameCorrectionValidationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.timeline = load_timeline()

    def correct(self, response, db_text="small db", timeline_text=None):
        timeline = self.timeline
        recorder = mock.Mock()
        with mock.patch.object(timeline, "load_chzzk_streamers_raw_db", return_value=db_text), \
             mock.patch.object(timeline.PromptRegistry, "compose", return_value="review instructions"), \
             mock.patch.object(timeline, "debug_prompt_before_call"), \
             mock.patch.object(timeline, "run_codex", return_value=response) as run_codex, \
            mock.patch.object(timeline, "ACTIVE_RECORDER", recorder):
            result = timeline.correct_streamer_nicknames_with_codex(
                self.ORIGINAL if timeline_text is None else timeline_text,
                prompt_snapshot={"nickname_review": []})
        return result, run_codex, recorder

    ORIGINAL = "[저스트 채팅; 인사]\n[00:00:10] 오타 닉네임 등장\n\n[게임; 플레이]\n[00:01:20] 게임 시작"

    def test_nickname_and_content_correction_is_accepted(self):
        corrected = self.ORIGINAL.replace("오타 닉네임", "정식 닉네임")
        result, _, _ = self.correct(corrected)
        self.assertEqual(corrected, result)

    def test_removed_or_added_line_returns_original(self):
        lines = self.ORIGINAL.splitlines()
        cases = {
            "removed": "\n".join(lines[:-1]),
            "added": self.ORIGINAL + "\n추가된 줄",
        }
        for name, response in cases.items():
            with self.subTest(name=name):
                result, _, _ = self.correct(response)
                self.assertEqual(self.ORIGINAL, result)

    def test_changed_removed_or_new_timestamp_returns_original(self):
        cases = {
            "changed": self.ORIGINAL.replace("00:00:10", "00:00:11"),
            "removed": self.ORIGINAL.replace("[00:00:10] ", ""),
            "new on header": self.ORIGINAL.replace("[저스트 채팅; 인사]", "[00:00:00] [저스트 채팅; 인사]"),
        }
        for name, response in cases.items():
            with self.subTest(name=name):
                result, _, _ = self.correct(response)
                self.assertEqual(self.ORIGINAL, result)

    def test_different_timestamp_lines_reordered_returns_original(self):
        lines = self.ORIGINAL.split("\n")
        first = lines.index("[00:00:10] 오타 닉네임 등장")
        second = lines.index("[00:01:20] 게임 시작")
        lines[first], lines[second] = lines[second], lines[first]
        result, _, _ = self.correct("\n".join(lines))
        self.assertEqual(self.ORIGINAL, result)

    def test_rejected_correction_returns_preprocessed_intermediate_text(self):
        timeline_text = "[01:00:10] 방송 시작 인사"
        result, _, _ = self.correct("[01:00:11] 방송 시작 인사", timeline_text=timeline_text)
        self.assertEqual("[01:00:10] 방송 잡담 및 소통", result)

    def test_line_endings_and_terminal_newline_difference_are_accepted(self):
        corrected = self.ORIGINAL.replace("\n", "\r\n") + "\r\n"
        result, _, _ = self.correct(corrected)
        self.assertEqual(self.ORIGINAL.splitlines(), result.splitlines())

    def test_small_database_is_included_unchanged(self):
        db_text = "닉네임:정식명\n다른 닉네임"
        _, run_codex, _ = self.correct(self.ORIGINAL, db_text)
        prompt = run_codex.call_args.kwargs["prompt"]
        self.assertIn(f"[치지직 스트리머 마스터 DB (참고 사전)]===\n{db_text}\n\n", prompt)

    def test_oversized_database_keeps_only_complete_line_prefix_within_char_cap(self):
        timeline = self.timeline
        db_text = "one\ntwo\nthree\n"
        with mock.patch.object(timeline, "NICKNAME_DB_MAX_CHARS", 8), \
             mock.patch.object(timeline, "NICKNAME_DB_MAX_BYTES", 100):
            _, run_codex, _ = self.correct(self.ORIGINAL, db_text)
        prompt = run_codex.call_args.kwargs["prompt"]
        self.assertIn("[치지직 스트리머 마스터 DB (참고 사전)]===\none\ntwo\n\n", prompt)
        self.assertNotIn("three", prompt)
        self.assertLessEqual(len("one\ntwo\n"), 8)

    def test_oversized_database_respects_utf8_byte_cap_and_drops_partial_line(self):
        timeline = self.timeline
        db_text = "가\n나나나\n다\n"
        with mock.patch.object(timeline, "NICKNAME_DB_MAX_CHARS", 100), \
             mock.patch.object(timeline, "NICKNAME_DB_MAX_BYTES", 5):
            _, run_codex, _ = self.correct(self.ORIGINAL, db_text)
        prompt = run_codex.call_args.kwargs["prompt"]
        self.assertIn("[치지직 스트리머 마스터 DB (참고 사전)]===\n가\n\n", prompt)
        self.assertNotIn("나나나", prompt)
        self.assertLessEqual(len("가\n".encode("utf-8")), 5)

    def test_oversized_database_does_not_include_partial_last_line(self):
        timeline = self.timeline
        db_text = "one\nlongline\nthree"
        with mock.patch.object(timeline, "NICKNAME_DB_MAX_CHARS", 7), \
             mock.patch.object(timeline, "NICKNAME_DB_MAX_BYTES", 100):
            _, run_codex, _ = self.correct(self.ORIGINAL, db_text)
        prompt = run_codex.call_args.kwargs["prompt"]
        self.assertIn("[치지직 스트리머 마스터 DB (참고 사전)]===\none\n\n", prompt)
        self.assertNotIn("longline", prompt)
        self.assertNotIn("three", prompt)


if __name__ == "__main__":
    unittest.main()
