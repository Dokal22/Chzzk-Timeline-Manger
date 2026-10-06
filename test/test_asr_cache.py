import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


def load_timeline_module():
    requests = types.ModuleType("requests")
    requests.RequestException = Exception
    sys.modules.setdefault("requests", requests)
    yt_dlp = types.ModuleType("yt_dlp")
    yt_dlp.YoutubeDL = object
    sys.modules.setdefault("yt_dlp", yt_dlp)
    pydantic = types.ModuleType("pydantic")
    pydantic.BaseModel = object
    pydantic.ConfigDict = dict
    pydantic.Field = lambda *args, **kwargs: None
    sys.modules.setdefault("pydantic", pydantic)
    source = Path(__file__).parents[1] / "src" / "code" / "Timeline.py"
    source_dir = str(source.parent)
    sys.path.insert(0, source_dir)
    try:
        spec = importlib.util.spec_from_file_location("timeline_asr_cache", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if sys.path[0] == source_dir:
            sys.path.pop(0)


class AsrCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.timeline = load_timeline_module()

    def test_cache_is_reused_only_for_matching_asr_options(self):
        fake_whisper = types.ModuleType("faster_whisper")
        segment = types.SimpleNamespace(start=12.0, end=14.0, text=" 테스트 발화")
        fake_model = mock.Mock()
        fake_model.transcribe.return_value = ([segment], types.SimpleNamespace())
        fake_whisper.WhisperModel = mock.Mock(return_value=fake_model)

        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "audio.ts"
            audio_path.write_bytes(b"audio")
            target_path = Path(temp_dir) / "full_raw_script.txt"
            target_path.write_text("[00:00:11] 오래된 무출처 캐시", encoding="utf-8")

            def split_audio(command, **kwargs):
                chunk_path = command[-1].replace("%03d", "000")
                Path(chunk_path).write_bytes(b"x" * 2048)
                return types.SimpleNamespace(returncode=0)

            with mock.patch.dict(sys.modules, {"faster_whisper": fake_whisper}):
                with mock.patch.object(self.timeline.subprocess, "run", side_effect=split_audio):
                    first = self.timeline.transcribe_chzzk_audio(
                        str(audio_path), str(target_path), model_size="base", language="ko"
                    )
                self.assertIn("[00:00:11] 테스트 발화", first)
                fake_whisper.WhisperModel.assert_called_once()

                with mock.patch.object(self.timeline.subprocess, "run", side_effect=AssertionError("cache miss")):
                    second = self.timeline.transcribe_chzzk_audio(
                        str(audio_path), str(target_path), model_size="base", language="ko"
                    )
                self.assertEqual(first, second)
                fake_whisper.WhisperModel.assert_called_once()

                cache_dir = Path(str(target_path) + ".asr_cache")
                base_meta = next(
                    json.loads(path.read_text(encoding="utf-8"))
                    for path in cache_dir.glob("*.json")
                    if json.loads(path.read_text(encoding="utf-8"))["options"]["model_size"] == "base"
                    and json.loads(path.read_text(encoding="utf-8"))["options"]["language"] == "ko"
                )
                base_meta_path = next(
                    path for path in cache_dir.glob("*.json")
                    if json.loads(path.read_text(encoding="utf-8"))["options"] == base_meta["options"]
                )
                base_meta["script_sha256"] = "corrupt"
                base_meta_path.write_text(json.dumps(base_meta), encoding="utf-8")
                with mock.patch.object(self.timeline.subprocess, "run", side_effect=split_audio):
                    self.timeline.transcribe_chzzk_audio(
                        str(audio_path), str(target_path), model_size="base", language="ko"
                    )
                self.assertEqual(2, fake_whisper.WhisperModel.call_count)

                with mock.patch.object(self.timeline.subprocess, "run", side_effect=split_audio):
                    self.timeline.transcribe_chzzk_audio(
                        str(audio_path), str(target_path), model_size="tiny", language="ko"
                    )
                self.assertEqual(3, fake_whisper.WhisperModel.call_count)

                with mock.patch.object(self.timeline.subprocess, "run", side_effect=split_audio):
                    self.timeline.transcribe_chzzk_audio(
                        str(audio_path), str(target_path), model_size="base", language="en"
                    )
                self.assertEqual(4, fake_whisper.WhisperModel.call_count)

    def test_hf_token_reads_dotenv_and_process_environment_takes_precedence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text("# local secret\nHF_TOKEN=\"hf_from_file\"\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"HF_TOKEN": ""}):
                self.assertEqual("hf_from_file", self.timeline.load_hf_token(str(env_path)))
                self.assertEqual("hf_from_file", os.environ["HF_TOKEN"])
            with mock.patch.dict(os.environ, {"HF_TOKEN": "hf_from_process"}):
                self.assertEqual("hf_from_process", self.timeline.load_hf_token(str(env_path)))

    def test_ffmpeg_pcm_decoder_passes_pyannote_mono_waveform_without_file_decoder(self):
        source_dir = str(Path(__file__).parents[1] / "src" / "code")
        sys.path.insert(0, source_dir)
        try:
            from asr_utils import decode_audio_to_pyannote_waveform
        finally:
            if sys.path[0] == source_dir:
                sys.path.pop(0)

        class FakeTensor:
            def __init__(self):
                self.steps = []

            def to(self, dtype):
                self.steps.append(("to", dtype))
                return self

            def div_(self, value):
                self.steps.append(("div", value))
                return self

            def unsqueeze(self, dimension):
                self.steps.append(("unsqueeze", dimension))
                return self

        fake_tensor = FakeTensor()
        fake_torch = types.SimpleNamespace(
            int16="int16", float32="float32",
            frombuffer=mock.Mock(return_value=fake_tensor),
        )
        completed = types.SimpleNamespace(returncode=0, stdout=b"\x00\x00\x01\x00", stderr=b"")
        with mock.patch("asr_utils.subprocess.run", return_value=completed) as run:
            result = decode_audio_to_pyannote_waveform("audio.ts", "ffmpeg", fake_torch)

        self.assertIs(fake_tensor, result)
        command = run.call_args.args[0]
        self.assertIn("16000", command)
        self.assertIn("pipe:1", command)
        self.assertEqual([("to", "float32"), ("div", 32768.0), ("unsqueeze", 0)], fake_tensor.steps)

    def test_diarization_device_policy_selects_cuda_cpu_and_fails_closed(self):
        def fake_torch(available):
            return types.SimpleNamespace(
                __version__="2.12.0+cpu",
                version=types.SimpleNamespace(cuda=None),
                cuda=types.SimpleNamespace(
                    is_available=lambda: available,
                    get_device_name=lambda _index: "Test GPU",
                ),
            )

        with mock.patch("builtins.print") as output:
            selected, _ = self.timeline.resolve_diarization_device("auto", fake_torch(True))
        self.assertEqual("cuda", selected)
        self.assertIn("Test GPU", " ".join(str(call) for call in output.call_args_list))

        with mock.patch("builtins.print") as output:
            selected, _ = self.timeline.resolve_diarization_device("auto", fake_torch(False))
        self.assertEqual("cpu", selected)
        self.assertIn("자동 선택", " ".join(str(call) for call in output.call_args_list))

        selected, _ = self.timeline.resolve_diarization_device("cpu", fake_torch(True))
        self.assertEqual("cpu", selected)
        with self.assertRaisesRegex(RuntimeError, "CUDA를 사용할 수 없습니다"):
            self.timeline.resolve_diarization_device("cuda", fake_torch(False))


if __name__ == "__main__":
    unittest.main()
