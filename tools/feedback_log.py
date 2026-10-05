#!/usr/bin/env python3
"""Append and inspect user feedback linked to immutable local artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict) or not value.get("feedback_id"):
            raise ValueError(f"{path}:{n}: invalid feedback record")
        rows.append(value)
    return rows


def add_feedback(log: Path, artifact: Path, feedback: str, *, vod_id: str | None = None,
                 candidate_id: str | None = None, output_line: str | None = None,
                 timestamp: str | None = None, proposed_change: str | None = None,
                 experiment: str | None = None) -> dict[str, Any]:
    if not feedback.strip():
        raise ValueError("feedback text must not be empty")
    artifact = artifact.resolve(strict=True)
    record = {"schema_version": 1, "feedback_id": "fb-" + uuid.uuid4().hex,
              "created_at": datetime.now(timezone.utc).isoformat(),
              "artifact_path": str(artifact), "artifact_sha256": sha256(artifact),
              "feedback": feedback.strip(), "vod_id": vod_id,
              "candidate_id": candidate_id, "output_line": output_line,
              "timestamp": timestamp, "proposed_change": proposed_change,
              "experiment": experiment, "status": "untriaged",
              "quality_label": None}
    log.parent.mkdir(parents=True, exist_ok=True)
    # Append one complete JSON record without rewriting prior feedback.
    with log.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add")
    add.add_argument("--artifact", type=Path, required=True)
    add.add_argument("--feedback", required=True)
    add.add_argument("--log", type=Path, default=Path("experiment_artifacts/feedback/feedback.jsonl"))
    for name in ("vod-id", "candidate-id", "output-line", "timestamp", "proposed-change", "experiment"):
        add.add_argument("--" + name, dest=name.replace("-", "_"))
    show = sub.add_parser("list")
    show.add_argument("--log", type=Path, default=Path("experiment_artifacts/feedback/feedback.jsonl"))
    args = parser.parse_args()
    if args.command == "add":
        record = add_feedback(args.log, args.artifact, args.feedback, vod_id=args.vod_id,
                              candidate_id=args.candidate_id, output_line=args.output_line,
                              timestamp=args.timestamp, proposed_change=args.proposed_change,
                              experiment=args.experiment)
        print(json.dumps(record, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(load_rows(args.log), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
