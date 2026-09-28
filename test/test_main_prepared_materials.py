import contextlib
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest


def load_main_module():
    chzzk_api = types.ModuleType("Chzzk_api")
    chzzk_api.select_chzzk_vod = lambda *args, **kwargs: None
    chzzk_api.download_chzzk_vod_chats = lambda *args, **kwargs: ""
    chzzk_api.CONFIG = {}

    timeline = types.ModuleType("Timeline")
    for name in (
        "download_chzzk_vod_audio",
        "transcribe_chzzk_audio",
        "generate_chzzk_timeline",
        "merge_and_format_final_timeline",
        "timestamp_to_seconds",
        "correct_streamer_nicknames_with_codex",
        "ensure_codex_ready",
    ):
        setattr(timeline, name, lambda *args, **kwargs: None)

    sys.modules["Chzzk_api"] = chzzk_api
    sys.modules["Timeline"] = timeline
    main_path = Path(__file__).parents[1] / "src" / "code" / "Main.py"
    spec = importlib.util.spec_from_file_location("main_under_test", main_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PreparedTimelineMaterialsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = load_main_module()

    def test_loads_prepared_transcription_when_both_materials_exist(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            vod_id = "123"
            script_dir = Path(temp_dir) / "voicepalette" / f"VOD_{vod_id}"
            chat_dir = Path(temp_dir) / "chat_cache" / vod_id
            script_dir.mkdir(parents=True)
            chat_dir.mkdir(parents=True)
            (script_dir / "full_raw_script.txt").write_text(
                "[00:00:01] 충분히 긴 테스트 대본", encoding="utf-8"
            )
            (chat_dir / f"chat_{vod_id}_full.txt").write_text(
                "[00:00:01] 테스트 채팅", encoding="utf-8"
            )

            previous_cwd = os.getcwd()
            try:
                os.chdir(temp_dir)
                result = self.main.load_prepared_timeline_materials(vod_id)
            finally:
                os.chdir(previous_cwd)

            self.assertIn("충분히 긴 테스트 대본", result)

    def test_rejects_incomplete_materials_without_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            previous_cwd = os.getcwd()
            output = io.StringIO()
            try:
                os.chdir(temp_dir)
                with contextlib.redirect_stdout(output):
                    result = self.main.load_prepared_timeline_materials("456")
            finally:
                os.chdir(previous_cwd)

            self.assertEqual("", result)
            self.assertIn("STT 대본", output.getvalue())
            self.assertIn("채팅 캐시", output.getvalue())


if __name__ == "__main__":
    unittest.main()
