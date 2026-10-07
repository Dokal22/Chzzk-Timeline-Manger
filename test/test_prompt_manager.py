import importlib.util
from contextlib import redirect_stdout
from io import StringIO
import json
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).parents[1] / "src" / "code" / "prompt_manager.py"
SPEC = importlib.util.spec_from_file_location("prompt_manager_test", MODULE)
PROMPTS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROMPTS)


class PromptRegistryTest(unittest.TestCase):
    LEGACY_PROMPT = "서문\n\n[한 규칙]\n내용\n\n[둘 규칙]\n내용2"

    def create_saved_registry(self, root, prompt_text=LEGACY_PROMPT):
        root_path = Path(root)
        if prompt_text is not None:
            (root_path / "prompt.txt").write_text(prompt_text, encoding="utf-8")
        registry = PROMPTS.PromptRegistry(root)
        registry.save()
        registry_path = root_path / "prompts" / PROMPTS.STORE_NAME
        return registry_path, registry.snapshot(), registry_path.read_bytes()

    def test_section_parser_only_splits_standalone_headings_and_keeps_preamble(self):
        source = "역할 설명 [본문 속 대괄호]\n\n[규칙 A]\n문장 [예시] 보존\n시간 [01:02:03]\n\n[규칙 B]\n둘째"
        sections = PROMPTS.split_sections("timeline", "test", source)
        self.assertEqual(["역할 및 분석 목적", "규칙 A", "규칙 B"], [x[0] for x in sections])
        self.assertIn("[예시]", sections[1][1]); self.assertIn("[01:02:03]", sections[1][1])

    def test_initial_catalog_selects_defaults_and_legacy_as_separate_sections(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "prompt.txt").write_text("서문\n\n[한 규칙]\n내용\n\n[둘 규칙]\n내용2", encoding="utf-8")
            registry = PROMPTS.PromptRegistry(root)
            timeline = registry.list("timeline")
            legacy = [x for x in timeline if x["source"] == "prompt.txt"]
            self.assertEqual(["역할 및 분석 목적", "한 규칙", "둘 규칙"], [x["name"] for x in legacy])
            self.assertEqual(len(timeline), len(registry.snapshot()["timeline"]))
            self.assertEqual(3, len(registry.snapshot()["nickname_review"]))

    def test_missing_registry_bootstraps_defaults_and_legacy_without_warning(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "prompt.txt").write_text(self.LEGACY_PROMPT, encoding="utf-8")
            output = StringIO()
            with redirect_stdout(output):
                registry = PROMPTS.PromptRegistry(root)
            self.assertEqual("", registry.warning)
            self.assertEqual("", output.getvalue())
            self.assertTrue(any(item["source"] == "builtin" for item in registry.list("timeline")))
            self.assertTrue(any(item["source"] == "prompt.txt" for item in registry.list("timeline")))
            self.assertFalse((Path(root) / "prompts" / PROMPTS.STORE_NAME).exists())

    def test_missing_registry_and_prompt_txt_bootstraps_defaults_only(self):
        with tempfile.TemporaryDirectory() as root:
            output = StringIO()
            with redirect_stdout(output):
                registry = PROMPTS.PromptRegistry(root)
            self.assertEqual("", registry.warning)
            self.assertEqual("", output.getvalue())
            self.assertTrue(registry.snapshot()["timeline"])
            self.assertTrue(registry.snapshot()["nickname_review"])
            self.assertFalse(any(item["source"] == "prompt.txt" for item in registry.list("timeline")))

    def test_existing_registry_and_identical_prompt_txt_has_no_warning(self):
        with tempfile.TemporaryDirectory() as root:
            self.create_saved_registry(root)
            output = StringIO()
            with redirect_stdout(output):
                registry = PROMPTS.PromptRegistry(root)
            self.assertEqual("", registry.warning)
            self.assertEqual("", output.getvalue())

    def test_existing_registry_mismatches_warn_without_replacing_registry(self):
        changed_sources = {
            "body changed": self.LEGACY_PROMPT.replace("내용2", "수정된 내용"),
            "title changed": self.LEGACY_PROMPT.replace("둘 규칙", "새 제목"),
            "section added": self.LEGACY_PROMPT + "\n\n[추가 규칙]\n추가 내용",
            "section deleted": "서문\n\n[한 규칙]\n내용",
            "prompt missing": None,
        }
        for name, changed_prompt in changed_sources.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as root:
                registry_path, original_snapshot, original_bytes = self.create_saved_registry(root)
                prompt_path = Path(root) / "prompt.txt"
                if changed_prompt is None:
                    prompt_path.unlink()
                else:
                    prompt_path.write_text(changed_prompt, encoding="utf-8")

                output = StringIO()
                with redirect_stdout(output):
                    registry = PROMPTS.PromptRegistry(root)

                self.assertIn("prompt.txt가 저장된 프롬프트 레지스트리와 달라졌습니다", output.getvalue())
                self.assertIn("기존 prompts/prompt_registry.json이 우선 적용됩니다", output.getvalue())
                self.assertIn("prompt.txt가 저장된 프롬프트 레지스트리와 달라졌습니다", registry.warning)
                self.assertEqual(original_snapshot, registry.snapshot())
                self.assertEqual(original_bytes, registry_path.read_bytes())

    def test_same_mismatch_warns_only_once_per_process_key(self):
        with tempfile.TemporaryDirectory() as root:
            self.create_saved_registry(root)
            (Path(root) / "prompt.txt").write_text(
                self.LEGACY_PROMPT.replace("내용2", "수정된 내용"), encoding="utf-8")
            output = StringIO()
            with redirect_stdout(output):
                first = PROMPTS.PromptRegistry(root)
                second = PROMPTS.PromptRegistry(root)
            warning = "prompt.txt가 저장된 프롬프트 레지스트리와 달라졌습니다"
            self.assertEqual(1, output.getvalue().count(warning))
            self.assertIn(warning, first.warning)
            self.assertIn(warning, second.warning)

    def test_version_pin_delete_restore_and_minimum_selection(self):
        with tempfile.TemporaryDirectory() as root:
            registry=PROMPTS.PromptRegistry(root)
            defaults=registry.list("timeline")
            chosen=registry.active_refs("timeline")
            first=defaults[0]
            registry.select("timeline",[r for r in chosen if r["id"]!=first["id"]])
            modified=registry.add_version("timeline",first["name"],"changed",first["id"],source_section_id=first["id"])
            self.assertNotIn(first["id"],[p["id"] for p in registry.snapshot()["timeline"]])
            registry.select("timeline",[{"id":first["id"],"version":modified["version"]}])
            self.assertEqual("changed",registry.snapshot()["timeline"][0]["text"])
            registry.delete(first["id"])
            with self.assertRaises(ValueError):registry.snapshot()
            registry.restore(first["id"])
            registry.select("timeline",[{"id":first["id"],"version":1}])
            self.assertTrue(registry.snapshot()["timeline"])
            with self.assertRaises(ValueError):registry.select("nickname_review",[])

    def test_custom_delete_soft_removes_every_revision_and_restore_does_not_auto_select(self):
        with tempfile.TemporaryDirectory() as root:
            registry=PROMPTS.PromptRegistry(root)
            item=registry.add_version("timeline","x","one");registry.add_version("timeline","x","two",item["id"])
            registry.select("timeline",[{"id":item["id"],"version":2}]);registry.delete(item["id"])
            registry.restore(item["id"])
            self.assertNotIn(item["id"],registry.active_ids("timeline"))
            self.assertEqual(2,len(registry.versions(item["id"])))

    def test_v1_migration_backs_up_and_pins_legacy_active_revision(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)/"prompts";folder.mkdir()
            old={"schema_version":1,"active":{"timeline":["x"],"nickname_review":[]},"prompts":[
                {"id":"x","stage":"timeline","name":"custom","version":1,"text":"one","enabled":True,"order":0},
                {"id":"x","stage":"timeline","name":"custom","version":2,"text":"two","enabled":True,"order":0},
                {"id":"y","stage":"timeline","name":"inactive","version":1,"text":"off","enabled":True,"order":1}]}
            path=folder/PROMPTS.STORE_NAME;raw=json.dumps(old);path.write_text(raw,encoding="utf-8")
            registry=PROMPTS.PromptRegistry(root)
            saved=json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(2,saved["schema_version"])
            self.assertEqual(raw,(folder/(PROMPTS.STORE_NAME+".v1.bak")).read_text(encoding="utf-8"))
            self.assertIn({"id":"x","version":2},registry.active_refs("timeline"))
            self.assertIn("y",[p["id"] for p in registry.list("timeline")])

    def test_corrupt_store_is_not_overwritten_and_compose_uses_only_selected_rows(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"prompts"/PROMPTS.STORE_NAME;path.parent.mkdir();path.write_text("{bad",encoding="utf-8")
            registry=PROMPTS.PromptRegistry(root)
            self.assertTrue(registry.warning);self.assertEqual("{bad",path.read_text(encoding="utf-8"))
            snapshot=registry.snapshot();only=snapshot["timeline"][:1]
            result=PROMPTS.PromptRegistry.compose("timeline","ignored base",{"timeline":only},"ignored legacy")
            self.assertIn(only[0]["text"],result);self.assertNotIn("ignored base",result);self.assertNotIn("ignored legacy",result)

    def test_order_persists_and_controls_list_snapshot_and_atomic_apply(self):
        with tempfile.TemporaryDirectory() as root:
            registry=PROMPTS.PromptRegistry(root)
            all_items=registry.list("timeline")
            a,b,c=all_items[:3]
            order=registry.order_ids("timeline")
            order.remove(c['id']);order.insert(order.index(a['id']),c['id'])
            orders={key:registry.order_ids(key) for key in PROMPTS.STAGES};orders['timeline']=order
            selections={key:registry.active_refs(key) for key in PROMPTS.STAGES}
            selections['timeline']=[{'id':a['id'],'version':1},{'id':c['id'],'version':1}]
            registry.apply(selections,orders)
            self.assertEqual([c['id'],a['id']],[p['id'] for p in registry.snapshot()['timeline']])
            self.assertEqual(c['id'],registry.list('timeline')[0]['id'])
            registry.save();reloaded=PROMPTS.PromptRegistry(root)
            self.assertEqual([c['id'],a['id']],[p['id'] for p in reloaded.snapshot()['timeline']])
            before={key:reloaded.active_refs(key) for key in PROMPTS.STAGES}
            with self.assertRaises(ValueError):
                reloaded.apply({**before,'nickname_review':[]},{key:reloaded.order_ids(key) for key in PROMPTS.STAGES})
            self.assertEqual(before,reloaded.data['active'])

    def test_trash_retains_position_and_new_prompt_appends(self):
        with tempfile.TemporaryDirectory() as root:
            registry=PROMPTS.PromptRegistry(root);before=registry.order_ids('timeline')
            target=before[1];registry.delete(target)
            self.assertEqual(before,registry.order_ids('timeline'))
            self.assertNotIn(target,[p['id'] for p in registry.list('timeline')])
            trashed=[p for p in registry.list('timeline',include_deleted=True) if p['id']==target][0]
            self.assertTrue(trashed['deleted'])
            registry.restore(target);self.assertEqual(before,registry.order_ids('timeline'))
            created=registry.add_version('timeline','new','new body')
            self.assertEqual(created['id'],registry.order_ids('timeline')[-1])

    def test_legacy_duplicate_orders_normalize_deterministically(self):
        with tempfile.TemporaryDirectory() as root:
            registry=PROMPTS.PromptRegistry(root)
            items=registry.list('timeline');items[0]['order']=7;items[1]['order']=7
            for record in registry.data['prompts']:
                if record['id'] in {items[0]['id'],items[1]['id']}:record['order']=7
            registry.data.pop('order_ids',None)
            first=registry.order_ids('timeline')
            registry.data.pop('order_ids')
            second=registry.order_ids('timeline')
            self.assertEqual(first,second)


if __name__ == "__main__": unittest.main()
