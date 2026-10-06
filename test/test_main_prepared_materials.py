import contextlib
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


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
        "load_chzzk_streamers_raw_db",
        "validate_diarization_device",
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

    def test_parses_supported_time_formats(self):
        self.assertEqual(754, self.main.parse_time_input("12:34"))
        self.assertEqual(3723, self.main.parse_time_input("01:02:03"))

    def test_rejects_invalid_time_components(self):
        for invalid_value in ("90", "1:60", "00:00:60", "aa:bb"):
            with self.subTest(invalid_value=invalid_value):
                with self.assertRaises(ValueError):
                    self.main.parse_time_input(invalid_value)

    def test_time_range_reprompts_until_valid(self):
        values = iter(("00:20", "00:10", "00:05", "00:30"))
        with mock.patch("builtins.input", side_effect=lambda *_: next(values)):
            with contextlib.redirect_stdout(io.StringIO()):
                result = self.main.ask_analysis_time_range(60)
        self.assertEqual((5, 30), result)

    def test_time_range_prompt_shows_full_video_range(self):
        values = iter(("00:00", "01:00"))
        output = io.StringIO()
        def fake_input(prompt):
            output.write(prompt)
            return next(values)

        with mock.patch("builtins.input", side_effect=fake_input):
            self.main.ask_analysis_time_range(35670)
        self.assertIn("영상 범위: 00:00:00 ~ 09:54:30", output.getvalue())

    def test_normal_mode_passes_range_to_audio_and_stt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "range_audio.ts"
            audio_path.write_bytes(b"audio")
            download_audio = mock.Mock(return_value=str(audio_path))
            transcribe = mock.Mock(return_value="[00:10:00] 테스트 대본")

            patches = (
                mock.patch.object(self.main, "ensure_codex_ready"),
                mock.patch.object(
                    self.main, "select_chzzk_vod",
                    return_value=("123", "테스트 VOD", 3600, "스트리머"),
                ),
                mock.patch.object(self.main, "ask_use_collab_member_reference", return_value=False),
                mock.patch.object(self.main, "download_chzzk_vod_audio", download_audio),
                mock.patch.object(self.main, "transcribe_chzzk_audio", transcribe),
                mock.patch.object(self.main, "download_chzzk_vod_chats", return_value=""),
                mock.patch.object(self.main, "timestamp_to_seconds", return_value=600),
                mock.patch.object(self.main, "generate_chzzk_timeline", return_value=[]),
                mock.patch("builtins.input", side_effect=("", "n", "", "00:10:00", "00:20:00")),
            )
            previous_cwd = os.getcwd()
            try:
                os.chdir(temp_dir)
                with contextlib.ExitStack() as stack:
                    for active_patch in patches:
                        stack.enter_context(active_patch)
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.main.run_pure_test()
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(600, download_audio.call_args.kwargs["start_sec"])
            self.assertEqual(1200, download_audio.call_args.kwargs["end_sec"])
            self.assertEqual(600, transcribe.call_args.kwargs["timestamp_offset_sec"])
            self.assertEqual("base", transcribe.call_args.kwargs["model_size"])
            self.assertEqual("ko", transcribe.call_args.kwargs["language"])
            self.assertFalse(transcribe.call_args.kwargs["diarization_enabled"])
            self.assertTrue(
                transcribe.call_args.kwargs["target_path"].endswith(
                    os.path.join("VOD_123", "raw_script_600_1200.txt")
                )
            )

    def test_asr_options_accept_config_default_and_model_override(self):
        config = {"WHISPER_MODEL": "base", "WHISPER_LANGUAGE": "ko", "DIARIZATION_ENABLED": False}
        with mock.patch("builtins.input", side_effect=["", "y"]):
            options = self.main.choose_asr_options(config)
        self.assertEqual(("base", "ko", True, "pyannote/speaker-diarization-community-1"), options)

        with mock.patch("builtins.input", side_effect=["medium", "n"]):
            options = self.main.choose_asr_options(config)
        self.assertEqual("medium", options[0])
        self.assertFalse(options[2])

    def test_asr_options_reprompt_invalid_model_and_diarization_answer(self):
        config = {"WHISPER_MODEL": "base", "DIARIZATION_ENABLED": False}
        with mock.patch("builtins.input", side_effect=["not-a-model", "turbo", "maybe", "n"]):
            options = self.main.choose_asr_options(config)
        self.assertEqual("turbo", options[0])
        self.assertFalse(options[2])

    def test_prepared_material_mode_does_not_prompt_or_change_options(self):
        config = {"WHISPER_MODEL": "small", "WHISPER_LANGUAGE": "ko", "DIARIZATION_ENABLED": True}
        with mock.patch("builtins.input", side_effect=AssertionError("must not prompt")):
            options = self.main.choose_asr_options(config, timeline_only=True)
        self.assertEqual(("small", "ko", True, "pyannote/speaker-diarization-community-1"), options)

    def test_explicit_cuda_failure_stops_before_vod_or_audio_work(self):
        with (
            mock.patch.dict(self.main.CONFIG, {"DIARIZATION_DEVICE": "cuda"}, clear=True),
            mock.patch.object(
                self.main, "choose_asr_options",
                return_value=("base", "ko", True, "pyannote/speaker-diarization-community-1"),
            ),
            mock.patch.object(
                self.main, "validate_diarization_device",
                side_effect=RuntimeError("CUDA 미지원 torch"),
            ),
            mock.patch.object(self.main, "ensure_codex_ready") as ensure_ready,
            mock.patch.object(self.main, "select_chzzk_vod") as select_vod,
            mock.patch.object(self.main, "download_chzzk_vod_audio") as download_audio,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.main.run_pure_test()
        ensure_ready.assert_not_called()
        select_vod.assert_not_called()
        download_audio.assert_not_called()

    def test_diarization_overlap_policy(self):
        timeline_path = Path(__file__).parents[1] / "src" / "code" / "Timeline.py"
        timeline_dir = str(timeline_path.parent)
        sys.path.insert(0, timeline_dir)
        try:
            from asr_utils import select_diarized_speaker
        finally:
            if sys.path[0] == timeline_dir:
                sys.path.pop(0)

        turns = [(0.0, 1.0, "SPEAKER_00"), (1.0, 2.0, "SPEAKER_01")]
        self.assertEqual("SPEAKER_00", select_diarized_speaker(0.0, 0.8, turns))
        self.assertEqual("SPEAKER_MIXED", select_diarized_speaker(0.0, 2.0, turns))
        self.assertEqual("UNKNOWN", select_diarized_speaker(3.0, 4.0, turns))


if __name__ == "__main__":
    unittest.main()
