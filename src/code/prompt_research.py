"""Opt-in local records for reproducible prompt experiments."""
import hashlib
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone


def sha256(value):
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class ResearchRecorder:
    def __init__(self, root=None):
        self.root = os.path.abspath(root or os.getcwd())
        self.run_id = uuid.uuid4().hex
        self.metadata = {}
        self.enabled = False

    def start(self, enabled, **metadata):
        self.enabled = bool(enabled)
        self.metadata = dict(metadata)
        if self.enabled:
            try:
                os.makedirs(os.path.join(self.root, "prompt_research"), exist_ok=True)
            except OSError:
                self.enabled = False

    def record(self, stage, input_text, prompt_text, raw_output, processed_output,
               model_requested="", prompt_versions=None, schema=None, status="success"):
        if not self.enabled:
            return
        entry = {
            "run_id": self.run_id,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "metadata": self.metadata,
            "stage": stage,
            "model_requested": model_requested,
            "model_actual": model_requested or "unknown (CLI default)",
            "prompt_versions": prompt_versions or [],
            "input_sha256": sha256(input_text),
            "prompt_sha256": sha256(prompt_text),
            "status": status,
            "schema": schema,
            "prompt": prompt_text,
            "raw_output": raw_output,
            "processed_output": processed_output,
        }
        path = os.path.join(self.root, "prompt_research", self.run_id + ".json")
        fd, temp = tempfile.mkstemp(prefix=".research-", suffix=".tmp", dir=os.path.dirname(path))
        try:
            existing = []
            if os.path.exists(path):
                with open(path, encoding="utf-8") as handle:
                    existing = json.load(handle)
            existing.append(entry)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(existing, handle, ensure_ascii=False, indent=2)
                handle.flush(); os.fsync(handle.fileno())
            os.replace(temp, path)
        except Exception:
            try: os.unlink(temp)
            except OSError: pass
            return False
        return True


ACTIVE_RECORDER = ResearchRecorder()
