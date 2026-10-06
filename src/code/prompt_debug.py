"""Opt-in diagnostics for the exact prompt string passed to the Codex CLI."""
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone


class PromptDebugger:
    MODES = {"off", "summary", "preview", "full"}
    PREVIEW_LINE_CHARS = 500

    def __init__(self):
        self.configure()

    def configure(self, mode="off", lines=10, root=None):
        normalized = str(mode or "off").strip().strip("`\"'").strip().lower()
        self.warning = ""
        if normalized not in self.MODES:
            self.warning = f"알 수 없는 PROMPT_DEBUG_MODE={mode!r}; off로 처리합니다."
            normalized = "off"
        try:
            preview_lines = int(lines)
        except (TypeError, ValueError):
            preview_lines = 10
            self.warning = "PROMPT_DEBUG_LINES 값이 잘못되어 10줄로 처리합니다."
        if preview_lines < 1 or preview_lines > 200:
            preview_lines = min(200, max(1, preview_lines))
            self.warning = "PROMPT_DEBUG_LINES는 1~200 사이로 제한했습니다."
        self.mode = normalized
        self.lines = preview_lines
        self.root = os.path.abspath(root or os.getcwd())
        if self.warning:
            print(f"⚠️ {self.warning}")

    @staticmethod
    def _digest(value):
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _selection(selected):
        return [{"order": index, "id": item.get("id", ""), "version": item.get("version", ""),
                 "name": item.get("name", "지침"), "source": item.get("source", "unknown")}
                for index, item in enumerate(selected or [], 1)]

    def _print_preview(self, prompt):
        rows = prompt.splitlines()
        count = len(rows)
        head_indexes = list(range(min(self.lines, count)))
        tail_indexes = list(range(max(self.lines, count - 3), count))
        indexes = head_indexes + [i for i in tail_indexes if i not in head_indexes]
        print(f"  미리보기: 앞 {min(self.lines, count)}줄, 뒤 지시문 포함 / 전체 {count}줄")
        previous = -1
        for index in indexes:
            if previous >= 0 and index > previous + 1:
                omitted = index - previous - 1
                print(f"  ... {omitted}줄 생략 ...")
            row = rows[index]
            if len(row) > self.PREVIEW_LINE_CHARS:
                clipped = len(row) - self.PREVIEW_LINE_CHARS
                row = row[:self.PREVIEW_LINE_CHARS] + f" … ({clipped}자 생략)"
            print(f"  {index + 1:>5}: {row}")
            previous = index

    def _save_full(self, stage, request_id, prompt, selected, model, schema, digest):
        folder = os.path.join(self.root, "prompt_debug")
        os.makedirs(folder, exist_ok=True)
        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(request_id or "request"))[:48].strip("._") or "request"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        stem = f"{stage}_{safe_id}_{stamp}_{uuid.uuid4().hex[:8]}"
        prompt_path = os.path.join(folder, stem + ".txt")
        with open(prompt_path, "w", encoding="utf-8", newline="") as handle:
            handle.write(prompt)
        schema_path = None
        if schema is not None:
            schema_path = os.path.join(folder, stem + ".schema.json")
            with open(schema_path, "w", encoding="utf-8", newline="") as handle:
                json.dump(schema, handle, ensure_ascii=False, indent=2)
        metadata = {"stage": stage, "request_id": str(request_id or "request"),
                    "requested_model": model or "CLI default (actual model unknown)",
                    "selected_prompts": self._selection(selected), "prompt_sha256": digest,
                    "prompt_chars": len(prompt), "prompt_utf8_bytes": len(prompt.encode("utf-8")),
                    "prompt_lines": len(prompt.splitlines()), "schema_included": schema is not None,
                    "schema_sha256": self._digest(json.dumps(schema, ensure_ascii=False, sort_keys=True)) if schema is not None else None,
                    "prompt_file": os.path.basename(prompt_path),
                    "schema_file": os.path.basename(schema_path) if schema_path else None}
        metadata_path = os.path.join(folder, stem + ".meta.json")
        with open(metadata_path, "w", encoding="utf-8", newline="") as handle:
            json.dump(metadata, handle, ensure_ascii=False, indent=2)
        return prompt_path, schema_path, metadata_path

    def before_call(self, stage, selected, prompt, model="", schema=None, request_id="request"):
        if self.mode == "off":
            return None
        prompt = prompt if isinstance(prompt, str) else str(prompt)
        digest = self._digest(prompt)
        rows = prompt.splitlines()
        selections = self._selection(selected)
        print(f"\n🔎 [프롬프트 디버그: {stage} / {request_id}]")
        print(f"  선택 지침 {len(selections)}개, 요청 모델: {model or 'CLI default (actual model unknown)'}")
        for item in selections:
            print(f"  {item['order']}. {item['name']} | {item['source']} | {item['id']} v{item['version']}")
        print(f"  전송 문자열: {len(prompt)}자 / {len(prompt.encode('utf-8'))} bytes / {len(rows)}줄")
        print(f"  SHA256: {digest}")
        print(f"  별도 output schema: {'있음' if schema is not None else '없음'}")
        if self.mode in {"preview", "full"}:
            self._print_preview(prompt)
        if self.mode == "full":
            try:
                prompt_path, schema_path, metadata_path = self._save_full(
                    stage, request_id, prompt, selected, model, schema, digest)
                print(f"  전체 프롬프트: {prompt_path}")
                if schema_path:
                    print(f"  Output schema: {schema_path}")
                print(f"  요청 정보: {metadata_path}")
            except Exception as exc:
                print(f"⚠️ 프롬프트 디버그 파일 저장 실패. 모델 호출은 계속합니다: {exc}")
        return digest


PROMPT_DEBUGGER = PromptDebugger()


def configure_prompt_debug(mode="off", lines=10, root=None):
    PROMPT_DEBUGGER.configure(mode, lines, root)


def debug_prompt_before_call(stage, selected, prompt, model="", schema=None, request_id="request"):
    try:
        return PROMPT_DEBUGGER.before_call(stage, selected, prompt, model, schema, request_id)
    except Exception as exc:
        print(f"⚠️ 프롬프트 디버그 출력 실패. 모델 호출은 계속합니다: {exc}")
        return None
