import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


def load_timeline_module():
    # Profile tests do not exercise network/audio/model code. Keep this test
    # runnable in the repository's lightweight test environment.
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
    spec = importlib.util.spec_from_file_location("timeline_profile_scope", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if sys.path[0] == source_dir:
        sys.path.pop(0)
    return module


class ChannelScopedStreamerProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.timeline = load_timeline_module()

    def test_root_legacy_profile_is_never_loaded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "streamer_info.txt").write_text(
                "[방송 정보]\n- 스트리머: 같은이름\n- 팬덤: legacy-only\n",
                encoding="utf-8",
            )

            name, profile = self.timeline.load_streamer_profile(
                "channel-a", "같은이름", profile_root=str(root / "streamer_profiles")
            )

            self.assertEqual("같은이름", name)
            self.assertIn("치지직 채널 ID: channel-a", profile)
            self.assertNotIn("legacy-only", profile)

    def test_profiles_are_isolated_by_channel_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            profile_root = Path(temp_dir)
            for channel_id, name in (("channel-a", "같은이름"), ("channel-b", "같은이름")):
                path = profile_root / f"{channel_id}.txt"
                path.write_text(
                    f"[방송인 기본 정보]\n- 스트리머 이름: {name}\n- 표식: {channel_id}\n",
                    encoding="utf-8",
                )

            _, profile_a = self.timeline.load_streamer_profile(
                "channel-a", "같은이름", profile_root=str(profile_root)
            )
            _, profile_b = self.timeline.load_streamer_profile(
                "channel-b", "같은이름", profile_root=str(profile_root)
            )

            self.assertIn("표식: channel-a", profile_a)
            self.assertNotIn("channel-b", profile_a)
            self.assertIn("표식: channel-b", profile_b)
            self.assertNotIn("channel-a", profile_b)

    def test_update_writes_channel_profile_and_metadata_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            profile_root = Path(temp_dir) / "streamer_profiles"
            metadata = {"channel_id": "channel-update", "schema_version": 1}
            with mock.patch.object(
                self.timeline, "research_streamer_profile",
                return_value=("[방송인 기본 정보]\n- 스트리머 이름: 업데이트", metadata),
            ), mock.patch("builtins.input", return_value="update"):
                name, profile = self.timeline.prepare_streamer_profile(
                    "channel-update", "업데이트", profile_root=str(profile_root)
                )

            profile_path = profile_root / "channel-update.txt"
            metadata_path = profile_root / "channel-update.meta.json"
            self.assertEqual("업데이트", name)
            self.assertIn("업데이트", profile)
            self.assertTrue(profile_path.is_file())
            self.assertTrue(metadata_path.is_file())
            self.assertEqual(profile, profile_path.read_text(encoding="utf-8"))
            self.assertNotIn("streamer_info.txt", str(profile_path))

    def test_namuwiki_filter_keeps_broadcast_and_excludes_sensitive(self):
        html = """
        <html><head><title>방송인 - 나무위키</title></head><body>
        <h2>개요</h2><p>치지직에서 게임 방송을 진행한다.</p>
        <h2>방송 활동</h2><p>주요 콘텐츠는 종합 게임과 시청자 소통이다.</p>
        <h2>논란</h2><p>절대 캐시되면 안 되는 내용</p>
        </body></html>
        """
        extracted, digest = self.timeline._extract_namuwiki_broadcast_content(html, "방송인")
        self.assertIn("게임 방송", extracted)
        self.assertNotIn("절대 캐시", extracted)
        self.assertTrue(digest)

    def test_namuwiki_compaction_coalesces_and_caps_noisy_lists(self):
        raw = "[방송 활동]\n- 치지직에서 게임 방송을 진행한다.\n- 치지직에서 게임 방송을 진행한다.\n[플레이한 게임]\n" + "\n".join(f"- 게임이름{i}" for i in range(30)) + "\n- 레벨 250 아이템 20"
        compact, meta = self.timeline._compact_namuwiki_profile(raw, "방송인")
        self.assertIn("방송 유형/주요 포맷", compact)
        self.assertLessEqual(meta["retained_content_items"], 10)
        self.assertNotIn("레벨 250", compact)
        self.assertEqual(1, compact.count("치지직에서 게임 방송을 진행한다."))
        self.assertLessEqual(len(compact), 1800)
        selected = self.timeline.select_streamer_profile_context(compact, "오늘 방송", "일반 잡담", "")
        self.assertNotIn("게임이름0", selected)
        relevant = self.timeline.select_streamer_profile_context(compact, "게임이름0 방송", "", "")
        self.assertEqual(1, relevant.count("게임이름0"))

    def test_adverse_allowed_section_and_table_noise_never_survive(self):
        raw = "[방송 특징]\n- 치지직 게임 방송\n- 메이플 확률조작 사건을 언급했다\n- 공식영상\n- 레벨 250 아이템 20\n[플레이한 게임]\n- 메이플스토리"
        compact, _ = self.timeline._compact_namuwiki_profile(raw, "방송인")
        selected = self.timeline.select_streamer_profile_context(compact, "메이플스토리 방송", "", "")
        for value in (compact, selected):
            self.assertNotIn("메이플 확률조작 사건", value)
            self.assertNotIn("레벨 250", value)
            self.assertNotIn("공식영상", value)

    def test_inline_html_text_nodes_become_one_coherent_fact(self):
        html = "<title>방송인 - 나무위키</title><h2>방송 활동</h2><p>치지직에서 <b>게임</b> 방송을 진행한다.</p>"
        extracted, _ = self.timeline._extract_namuwiki_broadcast_content(html, "방송인")
        self.assertIn("치지직에서 게임 방송을 진행한다.", extracted)

    def test_chunk_selector_activates_conditional_keyword_only_with_evidence(self):
        profile = "[방송 요약용 핵심 프로필]\n- 공식 스트리머/플랫폼: 방송인 / 치지직\n[조건부 키워드 참고]\n- 키워드: 마인크래프트 | 맥락: 서버 콘텐츠"
        selected = self.timeline.select_streamer_profile_context(profile, "오늘 방송", "마인크래프트에서 시작", "")
        self.assertIn("마인크래프트", selected)
        omitted = self.timeline.select_streamer_profile_context(profile, "오늘 방송", "일반 잡담", "")
        self.assertNotIn("마인크래프트", omitted)
        self.assertIn("공식 스트리머/플랫폼", omitted)

    def test_prompt_wrapper_uses_selected_context_and_forbids_current_event_inference(self):
        selected = "[방송 요약용 핵심 프로필]\n- 공식 스트리머/플랫폼: 방송인 / 치지직"
        prompt = self.timeline.build_streamer_profile_prompt_context(selected)
        self.assertIn(selected, prompt)
        self.assertIn("현재 사건, 활동, 참여자", prompt)
        self.assertNotIn("게임0", prompt)

    def test_user_persona_context_still_reads_full_profile(self):
        profile = "[콘텐츠별 페르소나]\n- 콘텐츠: 예시 서버\n- 게임/서버: 예시 서버\n- 캐릭터명: 예시캐릭터\n- 실제 스트리머: 방송인\n- 활성화 키워드: 예시 서버"
        context = self.timeline.format_content_persona_context(profile, "예시 서버 방송", "", "", "방송인")
        self.assertIn("예시캐릭터", context)

    def test_compaction_metadata_records_raw_and_compact_hashes(self):
        with mock.patch.object(self.timeline, "_fetch_namuwiki_page_detailed", return_value=("<html>", "https://namu.wiki/w/x", "page_ok")):
            with mock.patch.object(self.timeline, "_extract_namuwiki_broadcast_content", return_value=("[3.3. 플레이한 게임]\n- 갱비스트", "rawhash")):
                compact, metadata = self.timeline._enrich_profile_from_namuwiki("방송인")
        self.assertIn('"records"', compact)
        self.assertEqual("rawhash", metadata["raw_filtered_content_sha256"])
        self.assertTrue(metadata["compact_profile_sha256"])
        self.assertEqual("deterministic_index_v1", metadata["compaction_method"])
        self.assertTrue(metadata["deterministic_fallback"])

    def test_namuwiki_ambiguous_identity_is_skipped(self):
        html = "<html><head><title>다른 사람 - 나무위키</title></head><body><h2>방송 활동</h2><p>치지직 방송</p></body></html>"
        extracted, digest = self.timeline._extract_namuwiki_broadcast_content(html, "방송인")
        self.assertEqual(("", ""), (extracted, digest))

    def test_excluded_heading_blocks_allowed_descendants(self):
        html = """
        <html><head><title>방송인 - 나무위키</title></head><body>
        <h2>논란</h2><h3>방송 활동</h3><p>치지직에서 활동했다면 캐시 금지</p>
        <h2>방송 활동</h2><p>치지직에서 게임 방송을 진행한다.</p>
        </body></html>
        """
        extracted, _ = self.timeline._extract_namuwiki_broadcast_content(html, "방송인")
        self.assertIn("게임 방송을 진행", extracted)
        self.assertNotIn("캐시 금지", extracted)

    def test_namuwiki_fetch_failures_fail_closed(self):
        with mock.patch.object(self.timeline, "_namuwiki_robots_policy", return_value=(False, "robots_denied")):
            self.assertEqual(("", ""), self.timeline._fetch_namuwiki_page("방송인"))
        response = types.SimpleNamespace(status_code=302, content=b"", headers={"Location": "https://evil.example/w/x"})
        with mock.patch.object(self.timeline, "_namuwiki_robots_policy", return_value=(True, "robots_allowed")):
            with mock.patch.object(self.timeline.requests, "get", return_value=response, create=True):
                self.assertEqual(("", ""), self.timeline._fetch_namuwiki_page("방송인"))
        oversized = types.SimpleNamespace(status_code=200, content=b"x" * (self.timeline.NAMUWIKI_MAX_BYTES + 1), headers={})
        with mock.patch.object(self.timeline, "_namuwiki_robots_policy", return_value=(True, "robots_allowed")):
            with mock.patch.object(self.timeline.requests, "get", return_value=oversized, create=True):
                self.assertEqual(("", ""), self.timeline._fetch_namuwiki_page("방송인"))
        with mock.patch.object(self.timeline, "_namuwiki_robots_policy", return_value=(False, "robots_fetch_failed")):
            self.assertEqual(("", ""), self.timeline._fetch_namuwiki_page("방송인"))

    def test_robots_precedence_allows_w_document_but_denies_unrelated(self):
        policy = "User-agent: *\nDisallow: /\nAllow: /w/\n"
        allowed, reason = self.timeline._parse_robots_policy(policy, "/w/%EB%87%A8%EB%A1%B1%EC%9D%B4")
        self.assertTrue(allowed)
        self.assertEqual("robots_allowed", reason)
        denied, reason = self.timeline._parse_robots_policy(policy, "/api/status")
        self.assertFalse(denied)
        self.assertEqual("robots_denied", reason)

    def test_robots_longest_match_and_equal_allow_tie(self):
        policy = "User-agent: *\nDisallow: /\nAllow: /w/\nDisallow: /w/private\nAllow: /w/private\n"
        self.assertTrue(self.timeline._parse_robots_policy(policy, "/w/private/x")[0])
        self.assertTrue(self.timeline._parse_robots_policy("User-agent: *\nDisallow: /\nAllow: /w/\n", "/w/x")[0])
        self.assertFalse(self.timeline._parse_robots_policy("User-agent: *\nDisallow: /\n", "/w/x")[0])

    def test_malformed_robots_policy_denies(self):
        self.assertEqual((False, "robots_parse_failed"), self.timeline._parse_robots_policy("Allow: /w/", "/w/x"))

    def test_permitted_robots_reaches_page_and_reason_propagates(self):
        response = types.SimpleNamespace(status_code=200, content=b"<html>", text="<html>", headers={})
        with mock.patch.object(self.timeline, "_namuwiki_robots_policy", return_value=(True, "robots_allowed")):
            with mock.patch.object(self.timeline.requests, "get", return_value=response, create=True) as get:
                html, url, reason = self.timeline._fetch_namuwiki_page_detailed("방송인")
        self.assertEqual("page_ok", reason)
        self.assertEqual("<html>", html)
        self.assertTrue(url.startswith("https://namu.wiki/w/"))
        get.assert_called_once()

        with mock.patch.object(self.timeline, "_fetch_namuwiki_page_detailed", return_value=("", "", "robots_denied")):
            _, metadata = self.timeline._enrich_profile_from_namuwiki("방송인")
        self.assertEqual("robots_denied", metadata["reason"])

    def test_malformed_or_non_broadcast_document_is_skipped(self):
        self.assertEqual(("", ""), self.timeline._extract_namuwiki_broadcast_content("<not-closed", "방송인"))
        html = "<title>방송인 - 나무위키</title><h2>개요</h2><p>일반적인 소개만 있음</p>"
        self.assertEqual(("", ""), self.timeline._extract_namuwiki_broadcast_content(html, "방송인"))

    def test_enabled_success_metadata_contains_namuwiki_provenance(self):
        response = types.SimpleNamespace(status_code=200, content=b"{}")
        response.json = lambda: {"content": {"channelName": "방송인", "channelDescription": "게임 방송"}}
        namu_meta = {
            "status": "included", "url": "https://namu.wiki/w/%EB%B0%A9%EC%86%A1%EC%9D%B8",
            "type": "namuwiki", "fetched_at": "2026-09-29T00:00:00+09:00", "used_content_sha256": "abc",
        }
        with mock.patch.object(self.timeline.requests, "get", return_value=response, create=True):
            with mock.patch.object(self.timeline, "_enrich_profile_from_namuwiki", return_value=(json.dumps({"records": [{"type": "game_or_content", "canonical": "게임방송", "context": "방송 활동"}]}), namu_meta)):
                profile, metadata = self.timeline.research_streamer_profile("channel-a", "방송인", namuwiki_enabled=True)
        self.assertEqual("included", metadata["namuwiki"]["status"])
        self.assertEqual("namuwiki", metadata["sources"][1]["type"])
        self.assertEqual("abc", metadata["namuwiki"]["used_content_sha256"])
        self.assertNotIn("나무위키 방송 참고 정보", profile)
        self.assertTrue(metadata.get("knowledge_records"))
        self.assertTrue(metadata["profile_sha256"])

    def test_failed_namuwiki_update_preserves_existing_enriched_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "streamer_profiles"
            root.mkdir()
            profile_path = root / "channel-a.txt"
            metadata_path = root / "channel-a.meta.json"
            old_profile = "[방송인 기본 정보]\n- 스트리머 이름: 방송인\n\n[나무위키 방송 참고 정보]\n- 게임 방송"
            profile_path.write_text(old_profile, encoding="utf-8")
            metadata_path.write_text('{"namuwiki":{"status":"included"}}', encoding="utf-8")
            with mock.patch.object(self.timeline, "research_streamer_profile", return_value=(
                "[방송인 기본 정보]\n- 스트리머 이름: 방송인", {"namuwiki": {"status": "skipped"}}
            )), mock.patch("builtins.input", return_value="update"):
                _, profile = self.timeline.prepare_streamer_profile("channel-a", "방송인", profile_root=str(root), namuwiki_enabled=True)
            self.assertEqual(old_profile, profile)
            self.assertEqual(old_profile, profile_path.read_text(encoding="utf-8"))

    def test_old_generated_block_is_removed_but_user_persona_survives(self):
        old = "[방송인 기본 정보]\n- 스트리머 이름: 방송인\n\n[콘텐츠별 페르소나]\n- 콘텐츠: 서버\n- 캐릭터명: 캐릭터\n\n[나무위키 방송 참고 정보 — 비신뢰 참고자료]\n- 오래된 게임"
        cleaned = self.timeline._remove_generated_namuwiki_block(old)
        self.assertIn("[콘텐츠별 페르소나]", cleaned)
        self.assertNotIn("오래된 게임", cleaned)

    def test_numbered_live_headings_keep_intact_entities_and_skip_prose(self):
        raw = """[3. 콘텐츠]\n- 과 게임 방송을 진행한다. 시청자와 소통한다.\n- 60 Seconds! Reatomized\n- 8번 출구\n- 갱비스트\n[3.3. 플레이한 게임]\n- 60 Seconds! Reatomized\n- 8번 출구\n[1. 방송 특징]\n- 대한민국\n- 픽셀네트워크\n- 인터넷 방송인\n- 스토리\n- 타임\n- 제로"""
        records = self.timeline._build_namuwiki_knowledge_index(raw, "방송인")
        canonicals = {item["canonical"] for item in records}
        self.assertIn("60 Seconds! Reatomized", canonicals)
        self.assertIn("8번 출구", canonicals)
        self.assertIn("갱비스트", canonicals)
        for value in ("대한민국", "픽셀네트워크", "인터넷 방송인", "60", "Seconds", "출구", "스토리", "타임", "제로", "과 게임 방송을 진행한다. 시청자와 소통한다."):
            self.assertNotIn(value, canonicals)

    def test_knowledge_retrieval_requires_full_phrase_and_prioritizes_title(self):
        records = [
            {"type": "game_or_content", "canonical": "8번 출구", "aliases": [], "context": "게임"},
            {"type": "game_or_content", "canonical": "60 Seconds! Reatomized", "aliases": [], "context": "게임"},
        ]
        self.assertEqual([], self.timeline._retrieve_namuwiki_knowledge(records, "출구", "", ""))
        result = self.timeline._retrieve_namuwiki_knowledge(records, "8번 출구 방송", "60 Seconds! Reatomized", "")
        self.assertEqual("8번 출구", result[0]["canonical"])
        self.assertEqual(2, len(result))

    def test_bundle_rollback_restores_all_three_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = [root / "a.txt", root / "a.meta.json", root / "a.knowledge.json"]
            for path, value in zip(paths, ("old", "old-meta", "old-knowledge")):
                path.write_text(value, encoding="utf-8")
            original = self.timeline._atomic_write_json
            with mock.patch.object(self.timeline, "_atomic_write_json", side_effect=OSError("injected")):
                with self.assertRaises(OSError):
                    self.timeline._save_streamer_profile_bundle(str(paths[0]), str(paths[1]), str(paths[2]), "new", {}, "new-k")
            self.assertEqual(["old", "old-meta", "old-knowledge"], [path.read_text(encoding="utf-8") for path in paths])

    def test_reference_html_sections_filter_and_retrieve(self):
        html = "<h1>봉누도 2</h1><h2>봉누도 규칙</h2><p>서버 규칙과 진행 방식</p><h2>논란</h2><p>제외 내용</p><h2>봉누도 참여 인원</h2><p>철수와 영희</p>".encode("utf-8")
        text = self.timeline._extract_reference_text(html, "text/html", "https://example.com/x")
        context = "[출처: https://example.com/x]\n" + text
        selected = self.timeline._select_reference_sections(context, "봉누도 2", "봉누도 규칙 참여 인원", "")
        self.assertIn("규칙", selected)
        self.assertNotIn("논란", selected)
        self.assertLessEqual(len(selected.encode("utf-8")), self.timeline.REFERENCE_MAX_CONTEXT_BYTES)

    def test_reference_policy_is_source_specific_without_parser_branching(self):
        self.assertTrue(self.timeline._reference_policy("https://namu.wiki/w/example")["drop_h1_chrome"])
        self.assertFalse(self.timeline._reference_policy("https://example.com/server")["drop_h1_chrome"])
        html = "<h1>서버 문서</h1><p>일반 문서 본문</p>".encode("utf-8")
        text = self.timeline._extract_reference_text(html, "text/html", "https://example.com/server")
        records = self.timeline._compact_reference_records(text, "https://example.com/server")
        self.assertEqual("서버 문서", records[0]["heading"])
        self.assertIn("일반 문서 본문", records[0]["lines"])

    def test_live_namuwiki_heading_edit_controls_do_not_collapse_sections(self):
        html = (
            "<h1>봉누도 2</h1>"
            "<p>최근 수정 시각:</p><p>ACL 로그인 편집 요청</p>"
            "<div class='toc'>분류 관련 문서 [ 펼치기 · 접기 ]</div>"
            "<h2><a>1.</a><span>개요<span><a>[편집]</a></span></span></h2>"
            "<p>남봉이 주최한 GTA 인터넷 방송인 서버.</p>"
            "<h2><a>4.</a><span>규칙<span><a>[편집]</a></span></span></h2>"
            "<p>봉누도경찰청 관련 서버 규칙.</p>"
            "<h2><a>15.</a><span>논란 및 사건 사고<span><a>[편집]</a></span></span></h2>"
            "<h3><span>세부 항목<span><a>[편집]</a></span></span></h3>"
            "<p>제외되어야 하는 내용</p>"
        ).encode("utf-8")
        source = "https://namu.wiki/w/example"
        text = self.timeline._extract_reference_text(html, "text/html", source)
        records = self.timeline._compact_reference_records(text, source)
        self.assertEqual(["개요", "규칙"], [record["heading"] for record in records])
        serialized = self.timeline._serialize_reference_records(records)
        self.assertNotIn("최근 수정", serialized)
        self.assertNotIn("ACL", serialized)
        self.assertNotIn("관련 문서", serialized)
        self.assertNotIn("논란", serialized)
        self.assertNotIn("제외되어야", serialized)

    def test_reference_compaction_coalesces_inline_text_and_balances_line_budget(self):
        headings_and_paragraphs = []
        for section in range(12):
            start = section * 80
            section_paragraphs = "".join(
                f"<div class='wiki-paragraph'><a>고유명사{section}-{line}</a> 관련 설명입니다.</div>"
                for line in range(start, start + 80)
            )
            headings_and_paragraphs.append(f"<h2>{section + 1}. 섹션{section} [편집]</h2>{section_paragraphs}")
        html = ("<h1>문서</h1>" + "".join(headings_and_paragraphs)).encode("utf-8")
        source = "https://namu.wiki/w/example"
        text = self.timeline._extract_reference_text(html, "text/html", source)
        records = self.timeline._compact_reference_records(text, source)
        logical_lines = sum(1 + len(record["lines"]) for record in records)
        self.assertEqual(12, len(records))
        self.assertLessEqual(logical_lines, self.timeline.REFERENCE_MAX_COMPACT_LINES)
        self.assertTrue(all(record["lines"] for record in records))
        self.assertTrue(all("관련 설명입니다" in record["lines"][0] for record in records))

    def test_reference_html_table_cells_do_not_concatenate(self):
        html = (
            "<h1>서버</h1><h2>추가모집</h2>"
            "<table><tr><th>이름</th><th>직업</th></tr>"
            "<tr><td>철수</td><td>경찰</td></tr>"
            "<tr><td>영희</td><td>의사</td></tr></table>"
        ).encode("utf-8")
        source = "https://namu.wiki/w/example"
        text = self.timeline._extract_reference_text(html, "text/html", source)
        records = self.timeline._compact_reference_records(text, source)
        lines = records[0]["lines"]
        self.assertIn("철수", lines)
        self.assertIn("경찰", lines)
        self.assertIn("영희", lines)
        self.assertNotIn("철수경찰", lines)
        self.assertEqual("B", records[0]["relevance"])

    def test_reference_adjacent_links_keep_roster_boundaries(self):
        html = (
            "<h1>서버</h1><h2>최초 입주</h2>"
            "<p><a>감도이</a><a>다주</a><a>기세령</a><a>기령</a><a>도라희</a><a>쇼코코</a></p>"
        ).encode("utf-8")
        source = "https://namu.wiki/w/example"
        text = self.timeline._extract_reference_text(html, "text/html", source)
        records = self.timeline._compact_reference_records(text, source)
        self.assertEqual(["감도이 다주 기세령 기령 도라희 쇼코코"], records[0]["lines"])
        self.assertEqual("B", records[0]["relevance"])

    def test_reference_link_only_sections_are_removed(self):
        html = (
            "<h1>서버</h1>"
            "<h2>집단 및 세력</h2><p>자세한 내용은 봉누도 2/집단 및 세력 문서를 참고하십시오.</p>"
            "<h2>규칙</h2><p>서버 규칙과 진행 방식</p>"
        ).encode("utf-8")
        source = "https://namu.wiki/w/example"
        text = self.timeline._extract_reference_text(html, "text/html", source)
        records = self.timeline._compact_reference_records(text, source)
        self.assertEqual(["규칙"], [record["heading"] for record in records])
        self.assertEqual("A", records[0]["relevance"])

    def test_reference_retrieval_rejects_generic_only_and_keeps_exact_entity_lines(self):
        context = "[출처: fixture]\n__REF_HEADING_1__ 봉누도 경찰청\n서버 진행 규칙\n봉누도 경찰청의 참여 인원\n긴 unrelated line " + ("x" * 5000)
        self.assertEqual("", self.timeline._select_reference_sections(context, "서버", "서버 진행", ""))
        selected = self.timeline._select_reference_sections(context, "봉누도 경찰청", "", "")
        self.assertIn("봉누도 경찰청의 참여 인원", selected)
        self.assertNotIn("x" * 5000, selected)

    def test_reference_retrieval_has_dedicated_small_caps_and_title_priority(self):
        records = []
        for index in range(20):
            records.append(f"__REF_HEADING_1__ 고유콘텐츠{index}\n고유콘텐츠{index} 설명")
        context = "[출처: fixture]\n" + "\n".join(records)
        selected = self.timeline._select_reference_sections(context, "고유콘텐츠1", "고유콘텐츠2 고유콘텐츠3", "")
        self.assertLessEqual(selected.count("[출처:"), self.timeline.REFERENCE_RETRIEVAL_MAX_RECORDS)
        self.assertLessEqual(len(selected), self.timeline.REFERENCE_RETRIEVAL_MAX_CHARS)
        self.assertLessEqual(len(selected.encode("utf-8")), self.timeline.REFERENCE_RETRIEVAL_MAX_BYTES)
        self.assertTrue(selected.find("고유콘텐츠1") <= selected.find("고유콘텐츠2") or selected.find("고유콘텐츠2") == -1)

    def test_reference_raw_response_cap_is_one_mib_and_streaming(self):
        self.assertEqual(1024 * 1024, self.timeline.REFERENCE_MAX_URL_BYTES)
        self.assertEqual(300 * 1024, self.timeline.REFERENCE_MAX_CONTEXT_BYTES)
        response = types.SimpleNamespace(status_code=200, headers={"Content-Type": "text/html"}, is_redirect=False)
        response.iter_content = lambda chunk_size: [b"x" * (self.timeline.REFERENCE_MAX_URL_BYTES + 1)]
        response.close = lambda: None
        global_dns_answer = [
            (self.timeline.socket.AF_INET, self.timeline.socket.SOCK_STREAM,
             self.timeline.socket.IPPROTO_TCP, "", ("93.184.216.34", 0))
        ]
        with mock.patch.object(self.timeline.socket, "getaddrinfo", return_value=global_dns_answer), \
             mock.patch.object(self.timeline.requests, "get", return_value=response, create=True):
            status, text, metadata = self.timeline._fetch_reference_url("https://example.com/page")
        self.assertEqual(0, status)
        self.assertEqual("", text)

    def test_reference_cache_v2_is_canonical_and_v1_migrates_in_memory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            url = "https://example.com/server"
            legacy = {"schema_version": 1, "source_url": url, "final_url": url, "fetched_at": "now", "content_type": "text/html", "parser_version": 1, "content_sha256": "x", "text": "__REF_HEADING_1__ 규칙\n서버 규칙"}
            with mock.patch.object(self.timeline.os, "getcwd", return_value=temp_dir):
                directory, path = self.timeline._reference_cache_paths("cache", url)
                Path(directory).mkdir(parents=True, exist_ok=True)
                Path(path).write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
                migrated = self.timeline._load_reference_cache("cache", url)
                self.assertEqual(2, migrated["schema_version"])
                self.assertTrue(migrated["section_records"])
                self.assertTrue(self.timeline._save_reference_cache("cache", url, "__REF_HEADING_1__ 규칙\n서버 규칙", {"final_url": url, "content_type": "text/html"}))
                saved = json.loads(Path(path).read_text(encoding="utf-8"))
                physical_lines = Path(path).read_text(encoding="utf-8").splitlines()
            self.assertNotIn("text", saved)
            self.assertIn("section_records", saved)
            self.assertGreater(len(physical_lines), 1)

    def test_old_v2_parser_cache_is_marked_stale_without_deletion(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            url = "https://namu.wiki/w/example"
            text = "__REF_HEADING_1__ 문서\n오래된 정제 결과"
            old = {
                "schema_version": 2,
                "source_url": url,
                "final_url": url,
                "fetched_at": "now",
                "content_type": "text/html",
                "parser_version": 2,
                "content_sha256": self.timeline.hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "section_records": [{"heading": "문서", "level": 1, "parent_heading": "", "source": url, "lines": ["오래된 정제 결과"]}],
            }
            with mock.patch.object(self.timeline.os, "getcwd", return_value=temp_dir):
                directory, path = self.timeline._reference_cache_paths("cache", url)
                Path(directory).mkdir(parents=True, exist_ok=True)
                Path(path).write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
                loaded = self.timeline._load_reference_cache("cache", url)
                self.assertTrue(loaded["_stale_parser"])
                self.assertTrue(Path(path).exists())

    def test_namuwiki_disabled_is_recorded_without_fetch(self):
        response = types.SimpleNamespace(status_code=200, content='{"content":{"channelName":"방송인"}}'.encode("utf-8"))
        response.json = lambda: {"content": {"channelName": "방송인"}}
        with mock.patch.object(self.timeline.requests, "get", return_value=response, create=True):
            with mock.patch.object(self.timeline, "_enrich_profile_from_namuwiki") as enrich:
                with mock.patch.object(self.timeline, "_namuwiki_robots_allowed", return_value=True):
                    # Disabled mode must never enter the NamuWiki path.
                    profile, metadata = self.timeline.research_streamer_profile("channel-a", "방송인", namuwiki_enabled=False)
        enrich.assert_not_called()
        self.assertEqual("disabled", metadata["namuwiki"]["status"])
        self.assertNotIn("나무위키 방송 참고 정보", profile)


if __name__ == "__main__":
    unittest.main()
