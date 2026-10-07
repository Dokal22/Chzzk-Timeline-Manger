import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from contextlib import ExitStack, redirect_stdout
from io import StringIO
from unittest import mock


def load_timeline():
    requests = types.ModuleType("requests")
    requests.RequestException = Exception
    yt_dlp = types.ModuleType("yt_dlp")
    yt_dlp.YoutubeDL = object
    pydantic = types.ModuleType("pydantic")
    pydantic.BaseModel = object
    pydantic.ConfigDict = dict
    pydantic.Field = lambda *args, **kwargs: None
    sys.modules.setdefault("requests", requests)
    sys.modules.setdefault("yt_dlp", yt_dlp)
    sys.modules.setdefault("pydantic", pydantic)
    source = Path(__file__).parents[1] / "src" / "code" / "Timeline.py"
    sys.path.insert(0, str(source.parent))
    try:
        spec = importlib.util.spec_from_file_location("timeline_postprocessing", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    module.TimelineResponse.model_json_schema = classmethod(lambda cls: {"type": "object"})
    return module


def item(content, *, wf=40, wi=0, timestamp="00:00:10", **fields):
    return dict(group_large="저스트 채팅", topic="주제", timestamp=timestamp,
                wf=wf, wi=wi, content=content, **fields)


def response(items):
    return json.dumps({"items": items}, ensure_ascii=False, separators=(",", ":"))


class TimelinePostprocessingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.timeline = load_timeline()

    def generate(self, raw_response, script=""):
        timeline = self.timeline
        recorder = mock.Mock()
        with ExitStack() as stack:
            # Stub all context I/O and model calls: these tests are fully offline.
            for name, value in {
                "sanitize_chzzk_url": "",
                "select_streamer_profile_context": "",
                "_format_retrieved_knowledge": "",
                "_retrieve_namuwiki_knowledge": [],
                "load_streamer_knowledge": [],
                "load_and_filter_streamers_db": [],
                "format_content_persona_context": "",
                "_select_reference_sections": "",
                "run_codex": raw_response,
                "debug_prompt_before_call": None,
            }.items():
                stack.enter_context(mock.patch.object(timeline, name, return_value=value))
            stack.enter_context(mock.patch.object(timeline.time, "sleep"))
            stack.enter_context(mock.patch.object(timeline, "ACTIVE_RECORDER", recorder))
            stack.enter_context(redirect_stdout(StringIO()))
            result = timeline.generate_chzzk_timeline(
                script, streamer_profile_context="", prompt_snapshot={}
            )
        recorder.record.assert_called_once()
        self.assertIs(result, recorder.record.call_args.args[4])
        self.assertEqual(raw_response, recorder.record.call_args.args[3])
        return result

    def test_bad_item_never_replays_earlier_item_and_preserves_later_item(self):
        # wf=42 adjusts A to 9 seconds; the old score-blind fallback adjusted
        # it to 8, so final-output deduplication could not remove the duplicate.
        raw = response([
            item("핵심 장면", wf=42),
            item("잘못된 점수", wf="invalid"),
            item("후속 장면", timestamp="00:00:30"),
        ])
        with mock.patch.object(self.timeline, "_recover_timeline_items") as fallback:
            result = self.generate(raw, "[00:00:10] 핵심 장면")
        fallback.assert_not_called()
        self.assertEqual(["핵심 장면", "후속 장면"], [row["content"] for row in result])
        self.assertEqual([9, 30], [row["seconds"] for row in result])
        self.assertEqual("[00:00:09]", result[0]["timestamp"])

    def test_invalid_timestamp_or_non_object_does_not_abort_later_items(self):
        for bad in (item("잘못된 시간", timestamp="xx:00:10"), None):
            with self.subTest(bad=bad):
                result = self.generate(response([item("A"), bad, item("C")]))
                self.assertEqual(["A", "C"], [row["content"] for row in result])

    def test_unexpected_runtime_error_is_not_swallowed(self):
        error = RuntimeError("unexpected programming error")
        with mock.patch.object(self.timeline, "_postprocess_timeline_item", side_effect=error):
            with self.assertRaises(RuntimeError) as raised:
                self.generate(response([item("정상 입력")]))
        self.assertIs(error, raised.exception)

    def test_normal_and_fallback_score_boundaries(self):
        items = [item("39 제외", wf=39), item("40 유지", wf=40),
                 item("24 제외", wf=0, wi=24), item("25 유지", wf=0, wi=25)]
        for prefix in ("", "invalid JSON wrapper\n"):
            with self.subTest(fallback=bool(prefix)):
                result = self.generate(prefix + response(items))
                self.assertEqual(["40 유지", "25 유지"], [row["content"] for row in result])

    def test_fallback_does_not_borrow_scores_from_adjacent_objects(self):
        missing = item("점수 없는 항목")
        del missing["wf"]
        del missing["wi"]
        # The first object is truncated. Its high scores must never attach to
        # the next object, even when the response-level JSON cannot be parsed.
        raw = ('{"group_large":"저스트 채팅","topic":"주제",'
               '"timestamp":"00:00:10","wf":99,"wi":99,\n'
               + json.dumps(missing, ensure_ascii=False)
               + "\n" + response([item("낮은 점수", wf=1), item("유효 항목")]))
        result = self.generate(raw)
        self.assertEqual(["유효 항목"], [row["content"] for row in result])

    def test_missing_scores_default_to_zero_in_both_paths(self):
        no_scores = item("둘 다 누락")
        del no_scores["wf"]
        del no_scores["wi"]
        only_wi = item("중요도 유지", wf=0, wi=25)
        del only_wi["wf"]
        only_wf = item("재미 유지")
        del only_wf["wi"]
        for prefix in ("", "broken\n"):
            with self.subTest(fallback=bool(prefix)):
                result = self.generate(prefix + response([no_scores, only_wi, only_wf]))
                self.assertEqual(["중요도 유지", "재미 유지"], [row["content"] for row in result])

    def test_malformed_scores_are_not_coerced_and_later_items_survive(self):
        for prefix in ("", "broken\n"):
            for bad_scores in ({"wf": "40"}, {"wi": None}, {"wf": []}):
                with self.subTest(fallback=bool(prefix), scores=bad_scores):
                    bad = item("잘못된 점수")
                    bad.update(bad_scores)
                    result = self.generate(prefix + response([bad, item("후속 항목")]))
                    self.assertEqual(["후속 항목"], [row["content"] for row in result])

    def test_normal_and_fallback_share_time_and_content_normalization(self):
        scene = item('🔥[대주제; 소주제] [채팅폭발] 핵심 장면 (3 단계) ㅋㅋㅋㅋ 전개.', wf=42)
        scene["topic"] = "게임(닉네임)"
        raw = response([scene])
        normal = self.generate(raw, "[00:00:10] 핵심 장면")
        fallback = self.generate("```json\n" + raw + "\n```", "[00:00:10] 핵심 장면")
        self.assertEqual(normal, fallback)
        self.assertEqual(9, fallback[0]["seconds"])
        self.assertEqual("게임", fallback[0]["topic"])
        self.assertEqual("핵심 장면 ㅋㅋㅋ", fallback[0]["content"])
        self.assertEqual({"seconds", "timestamp", "group_large", "topic", "content"},
                         set(fallback[0]))

    def test_fallback_preserves_japanese_game_category_compatibility(self):
        scene = item("예전 합방 이야기")
        scene["group_large"] = "ゲーム 방송"
        result = self.generate("broken\n" + response([scene]))
        self.assertEqual("저스트 채팅", result[0]["group_large"])
        self.assertEqual("과거 합방 언급 및 토크", result[0]["topic"])

    def test_fallback_handles_escaped_quotes_and_braces_inside_strings(self):
        scene = item('인용 "장면" {내용}', wf=0, wi=25)
        result = self.generate("broken\n" + response([scene]))
        self.assertEqual(scene["content"], result[0]["content"])

    def test_fallback_recovers_complete_items_from_truncated_response(self):
        raw = response([item("완전한 항목")])[:-2]
        result = self.generate(raw)
        self.assertEqual(["완전한 항목"], [row["content"] for row in result])

    def test_valid_json_with_invalid_items_container_does_not_use_fallback(self):
        with mock.patch.object(self.timeline, "_recover_timeline_items") as fallback:
            result = self.generate(json.dumps({"items": None}))
        fallback.assert_not_called()
        self.assertEqual([], result)

    def test_distinct_source_items_are_not_deduplicated(self):
        for prefix in ("", "broken\n"):
            with self.subTest(fallback=bool(prefix)):
                result = self.generate(prefix + response([item("같은 표현"), item("같은 표현")]))
                self.assertEqual(2, len(result))


if __name__ == "__main__":
    unittest.main()
