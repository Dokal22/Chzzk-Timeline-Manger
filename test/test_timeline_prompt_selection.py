import importlib.util
from pathlib import Path
import sys
import types
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest import mock

CODE = Path(__file__).parents[1] / "src" / "code"
sys.path.insert(0, str(CODE))


def load_timeline():
    requests = types.ModuleType("requests"); requests.RequestException = Exception
    yt_dlp = types.ModuleType("yt_dlp"); yt_dlp.YoutubeDL = object
    pydantic = types.ModuleType("pydantic"); pydantic.BaseModel = object; pydantic.ConfigDict = dict; pydantic.Field = lambda *a, **k: None
    sys.modules.setdefault("requests", requests); sys.modules.setdefault("yt_dlp", yt_dlp); sys.modules.setdefault("pydantic", pydantic)
    path = CODE / "Timeline.py"; spec = importlib.util.spec_from_file_location("timeline_prompt_selection", path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


class TimelinePromptSelectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.timeline = load_timeline()

    def test_model_calls_receive_only_selected_revision_text(self):
        timeline = self.timeline; sent = []
        analysis_attempts = {"count": 0}
        def fake_codex(prompt, **kwargs):
            sent.append(prompt)
            if kwargs.get("output_schema"):
                analysis_attempts["count"] += 1
                if analysis_attempts["count"] == 1:
                    raise RuntimeError("mock retry")
            return '{"items": []}' if kwargs.get("output_schema") else "[00:00:10] [저스트 채팅; 인사] test"
        timeline.TimelineResponse.model_json_schema = classmethod(lambda cls: {"type": "object"})
        selected = {"timeline": [{"id": "t2", "version": 1, "name": "먼저", "source": "user", "text": "ORDER_FIRST"},
                                  {"id": "t", "version": 4, "name": "다음", "source": "builtin", "text": "ONLY_TIMELINE_REV4"}],
                    "nickname_review": [{"id": "n", "version": 2, "name": "검수", "source": "builtin", "text": "ONLY_REVIEW_REV2"}]}
        recorder = mock.Mock()
        debug_calls = []
        events = []
        output = StringIO()
        with mock.patch.multiple(timeline,
            sanitize_chzzk_url=mock.DEFAULT, select_streamer_profile_context=mock.DEFAULT,
            _format_retrieved_knowledge=mock.DEFAULT, _retrieve_namuwiki_knowledge=mock.DEFAULT,
            load_streamer_knowledge=mock.DEFAULT, load_and_filter_streamers_db=mock.DEFAULT,
            format_content_persona_context=mock.DEFAULT, load_chzzk_streamers_raw_db=mock.DEFAULT,
            run_codex=mock.DEFAULT):
            timeline.sanitize_chzzk_url.return_value = ""
            timeline.select_streamer_profile_context.return_value = ""
            timeline._format_retrieved_knowledge.return_value = ""
            timeline._retrieve_namuwiki_knowledge.return_value = []
            timeline.load_streamer_knowledge.return_value = []
            timeline.load_and_filter_streamers_db.return_value = []
            timeline.format_content_persona_context.return_value = ""
            timeline.load_chzzk_streamers_raw_db.return_value = ""
            def traced_codex(prompt, **kwargs):
                events.append("model_call")
                return fake_codex(prompt, **kwargs)
            timeline.run_codex.side_effect = traced_codex
            with mock.patch.object(timeline, "ACTIVE_RECORDER", recorder), \
                 mock.patch.object(timeline, "debug_prompt_before_call", side_effect=lambda *args, **kwargs: (debug_calls.append((args, kwargs)), events.append("debug"), print("DEBUG_SENTINEL"))), \
                 mock.patch.object(timeline.time, "sleep"):
                with redirect_stdout(output):
                    timeline.generate_chzzk_timeline("[00:00:10] phrase", streamer_profile_context="", prompt_snapshot=selected)
                    timeline.correct_streamer_nicknames_with_codex("[00:00:10] [저스트 채팅; 인사] test", prompt_snapshot=selected)
        self.assertEqual(3, len(sent))
        self.assertEqual(sent[0], sent[1])
        self.assertLess(sent[0].index("ORDER_FIRST"), sent[0].index("ONLY_TIMELINE_REV4"))
        self.assertNotIn("ONLY_REVIEW_REV2", sent[0])
        self.assertIn("ONLY_REVIEW_REV2", sent[2]); self.assertNotIn("ONLY_TIMELINE_REV4", sent[2])
        self.assertNotIn("무조건적인 도입부 가점", sent[0])
        self.assertNotIn("소주제 닉네임 박제 전면 차단 지침", sent[2])
        versions=recorder.record.call_args_list[0].kwargs["prompt_versions"]
        self.assertEqual(["t2", "t"], [item["id"] for item in versions])
        self.assertEqual(sent[0], debug_calls[0][0][2])
        self.assertEqual(2, len(debug_calls))
        self.assertEqual(["debug", "model_call", "model_call", "debug", "model_call"], events)
        rendered = output.getvalue()
        self.assertLess(rendered.index("DEBUG_SENTINEL"), rendered.index("Codex 구독 모델 호출 중 (청크 인덱스: 0)"))
        self.assertEqual(sent[2], debug_calls[1][0][2])
        self.assertEqual(sent[2], recorder.record.call_args_list[1].args[2])
        self.assertIn("파일을 읽거나 수정하거나 셸 명령을 실행하지 마십시오.", recorder.record.call_args_list[1].args[2])


if __name__ == "__main__": unittest.main()
