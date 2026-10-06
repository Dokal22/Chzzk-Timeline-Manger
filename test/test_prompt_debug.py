import importlib.util
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

MODULE = Path(__file__).parents[1] / "src" / "code" / "prompt_debug.py"
SPEC = importlib.util.spec_from_file_location("prompt_debug_test", MODULE)
DEBUG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DEBUG)


class PromptDebuggerTest(unittest.TestCase):
    def test_mode_accepts_backtick_or_quote_wrapped_config_value(self):
        debugger = DEBUG.PromptDebugger()
        debugger.configure("`preview`", root=tempfile.gettempdir())
        self.assertEqual("preview", debugger.mode)
        debugger.configure('"full"', root=tempfile.gettempdir())
        self.assertEqual("full", debugger.mode)

    def test_off_emits_nothing_and_creates_no_files(self):
        with tempfile.TemporaryDirectory() as root:
            debugger = DEBUG.PromptDebugger(); debugger.configure(root=root)
            output = StringIO()
            with redirect_stdout(output):
                debugger.before_call("timeline", [{"id": "x"}], "sensitive")
            self.assertEqual("", output.getvalue())
            self.assertEqual([], list(Path(root).iterdir()))

    def test_preview_shows_order_first_n_tail_and_marks_omitted_rows(self):
        with tempfile.TemporaryDirectory() as root:
            debugger = DEBUG.PromptDebugger(); debugger.configure("preview", 3, root)
            prompt = "\n".join([f"line-{i}" for i in range(1, 11)])
            output = StringIO()
            with redirect_stdout(output):
                debugger.before_call("timeline", [{"id":"b","version":2,"name":"B","source":"user"},
                                                     {"id":"a","version":1,"name":"A","source":"builtin"}],
                                     prompt, model="test-model", schema={"type":"object"})
            rendered = output.getvalue()
            self.assertLess(rendered.index("B | user"), rendered.index("A | builtin"))
            self.assertIn("line-1", rendered); self.assertIn("line-3", rendered)
            self.assertIn("line-8", rendered); self.assertIn("line-10", rendered)
            self.assertIn("4줄 생략", rendered)
            self.assertNotIn("line-4\n", rendered)

    def test_full_writes_exact_prompt_schema_and_non_colliding_metadata(self):
        with tempfile.TemporaryDirectory() as root:
            debugger = DEBUG.PromptDebugger(); debugger.configure("full", 10, root)
            prompt = "처음\r\n둘째\n마지막"
            schema = {"type":"object", "설명":"검증"}
            with redirect_stdout(StringIO()):
                debugger.before_call("timeline", [{"id":"x","version":3,"name":"선택","source":"builtin"}],
                                     prompt, "", schema, "chunk-1")
                debugger.before_call("timeline", [], prompt, "model", schema, "chunk-1")
            folder = Path(root) / "prompt_debug"
            prompts = list(folder.glob("*.txt"))
            self.assertEqual(2, len(prompts))
            self.assertEqual({prompt}, {p.read_bytes().decode("utf-8") for p in prompts})
            self.assertEqual(2, len(list(folder.glob("*.schema.json"))))
            metadata = json.loads(list(folder.glob("*.meta.json"))[0].read_text(encoding="utf-8"))
            self.assertEqual("x", metadata["selected_prompts"][0]["id"])
            self.assertEqual(DEBUG.PromptDebugger._digest(prompt), metadata["prompt_sha256"])
            self.assertEqual("CLI default (actual model unknown)", metadata["requested_model"])

    def test_file_write_failure_does_not_raise(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "prompt_debug").write_text("occupied", encoding="utf-8")
            debugger = DEBUG.PromptDebugger(); debugger.configure("full", root=root)
            with redirect_stdout(StringIO()) as output:
                self.assertIsNotNone(debugger.before_call("timeline", [], "prompt"))
            self.assertIn("모델 호출은 계속합니다", output.getvalue())


if __name__ == "__main__":
    unittest.main()
