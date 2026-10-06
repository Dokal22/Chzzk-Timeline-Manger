import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).parents[1] / "src" / "code" / "prompt_manager.py"
SPEC = importlib.util.spec_from_file_location("prompt_manager_test", MODULE)
PROMPTS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROMPTS)


class PromptRegistryTest(unittest.TestCase):
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
