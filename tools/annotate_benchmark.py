#!/usr/bin/env python3
"""Review calibration windows and store safe, resumable benchmark annotations.

Examples (from the project root)::

    python tools/annotate_benchmark.py annotate
    python tools/annotate_benchmark.py validate

The manifest is read-only.  Annotations are stored separately and rewritten
atomically, so source STT/chat files and the generated sampling frame remain
unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import webbrowser
from pathlib import Path
from typing import Any, Iterable

try:  # Works both as ``python -m tools.annotate_benchmark`` and direct script.
    from tools.benchmark_manifest import TIMESTAMP_RE, parse_timestamp
except ModuleNotFoundError:  # pragma: no cover - exercised by the documented command
    from benchmark_manifest import TIMESTAMP_RE, parse_timestamp

SUMMARY_VALUES = {0, 1, 2}
ENTERTAINMENT_VALUES = {0, 1, 2}
MODALITIES = {"stt", "chat", "stt+chat", "unknown"}
CONFIDENCES = {"low", "medium", "high"}
DUPLICATE_RE = re.compile(r"^(none|same_event|related_event)(?::([A-Za-z0-9_.:-]+))?$")
LABEL_KEYS = {
    "summary_worthiness", "entertainment_value", "acceptable_click_start_seconds",
    "acceptable_click_end_seconds", "evidence_modality", "confidence",
    "duplicate_relation", "annotator_id", "notes",
}


def vod_url(record: dict[str, Any]) -> str:
    """Return the user-verified Chzzk VOD link for this review window."""
    vod_id = record.get("vod_id")
    start = record.get("source", {}).get("start_seconds")
    if vod_id in (None, "") or not isinstance(start, (int, float)):
        raise ValueError("record is missing vod_id or source.start_seconds")
    return f"https://chzzk.naver.com/video/{vod_id}?currentTime={int(start)}"


def open_vod(record: dict[str, Any]) -> tuple[str, bool]:
    """Open a review link, returning the URL and whether the opener accepted it."""
    url = vod_url(record)
    try:
        return url, bool(webbrowser.open_new_tab(url))
    except Exception:
        # Browser availability is outside the annotation tool's control.  Keep
        # the text-only fallback usable and let the caller display the failure.
        return url, False


def load_manifest(path: Path) -> list[dict[str, Any]]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{number}: invalid JSON: {exc}") from exc
        if not isinstance(row, dict) or not isinstance(row.get("window_id"), str):
            raise ValueError(f"{path}:{number}: missing record identity")
        rows.append(row)
    if not rows:
        raise ValueError(f"empty manifest: {path}")
    return rows


def record_digest(record: dict[str, Any]) -> str:
    """Bind an annotation to immutable record identity and source bounds."""
    source = record.get("source", {})
    payload = "|".join(str(record.get(key, "")) for key in ("window_id", "vod_id", "split"))
    payload += "|" + "|".join(str(source.get(key, "")) for key in ("stt_path", "chat_path", "start_seconds", "end_seconds"))
    payload += "|" + json.dumps(record.get("source_hashes", {}), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer or null")
    return value


def validate_labels(labels: dict[str, Any], record: dict[str, Any], records_by_id: dict[str, dict[str, Any]]) -> None:
    if record.get("split") != "calibration":
        raise ValueError("annotations are restricted to calibration records")
    if set(labels) != LABEL_KEYS:
        raise ValueError("labels must contain exactly the rubric fields")
    if labels["summary_worthiness"] not in SUMMARY_VALUES:
        raise ValueError("summary_worthiness must be 0, 1, or 2")
    if labels["entertainment_value"] not in ENTERTAINMENT_VALUES:
        raise ValueError("entertainment_value must be 0, 1, or 2")
    start, end = labels["acceptable_click_start_seconds"], labels["acceptable_click_end_seconds"]
    if (start is None) != (end is None):
        raise ValueError("click interval must contain both bounds or both null")
    source = record.get("source", {})
    lo, hi = source.get("start_seconds"), source.get("end_seconds")
    if start is not None:
        start, end = _integer(start, "acceptable_click_start_seconds"), _integer(end, "acceptable_click_end_seconds")
        if start > end or start < lo or end > hi:
            raise ValueError("click interval must be ordered and within the record window")
    if labels["evidence_modality"] not in MODALITIES:
        raise ValueError(f"evidence_modality must be one of {sorted(MODALITIES)}")
    if labels["confidence"] not in CONFIDENCES:
        raise ValueError(f"confidence must be one of {sorted(CONFIDENCES)}")
    relation = labels["duplicate_relation"]
    if not isinstance(relation, str):
        raise ValueError("duplicate_relation must be a string")
    match = DUPLICATE_RE.fullmatch(relation)
    if not match or (match.group(1) == "none" and match.group(2)) or (match.group(1) != "none" and not match.group(2)):
        raise ValueError("duplicate_relation must be none, same_event:<window_id>, or related_event:<window_id>")
    if match.group(2):
        target = records_by_id.get(match.group(2))
        if target is None or target["split"] != "calibration":
            raise ValueError("duplicate reference must name an existing calibration record")
        if target["window_id"] == record["window_id"]:
            raise ValueError("duplicate reference cannot point to the current record")
    if not isinstance(labels["annotator_id"], str) or not labels["annotator_id"].strip() or len(labels["annotator_id"]) > 100:
        raise ValueError("annotator_id must be a non-empty string of at most 100 characters")
    if labels["notes"] is not None and (not isinstance(labels["notes"], str) or len(labels["notes"]) > 500 or "\n" in labels["notes"] or "\r" in labels["notes"]):
        raise ValueError("notes must be a single line of at most 500 characters or null")


def load_annotations(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    result = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            row = json.loads(line)
            key = row["window_id"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ValueError(f"{path}:{number}: invalid annotation row") from exc
        if key in result:
            raise ValueError(f"{path}:{number}: duplicate annotation for {key}")
        result[key] = row
    return result


def atomic_write_annotations(path: Path, annotations: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            for key in sorted(annotations):
                handle.write(json.dumps(annotations[key], ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def bounded_evidence(root: Path, record: dict[str, Any], max_lines: int = 40, max_chars: int = 6000) -> dict[str, list[str]]:
    """Load only timestamped lines in the selected window, bounded by count/bytes."""
    source = record["source"]
    result: dict[str, list[str]] = {}
    for kind in ("stt", "chat"):
        relative = Path(source[f"{kind}_path"])
        path = (root / relative).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError(f"{kind} source escapes project root: {relative}") from exc
        if not path.is_file():
            raise ValueError(f"missing {kind} source: {relative}")
        lines = []
        used = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            match = TIMESTAMP_RE.match(line)
            if not match:
                continue
            second = parse_timestamp(match.group("stamp"))
            if source["start_seconds"] <= second < source["end_seconds"]:
                if len(lines) >= max_lines or used + len(line) + 1 > max_chars:
                    break
                lines.append(line)
                used += len(line) + 1
        result[kind] = lines
    return result


def validate_annotations(manifest_path: Path, annotation_path: Path, root: Path) -> list[str]:
    records = load_manifest(manifest_path)
    by_id = {record["window_id"]: record for record in records}
    annotations = load_annotations(annotation_path)
    errors = []
    for key, row in annotations.items():
        record = by_id.get(key)
        if record is None:
            errors.append(f"{key}: record identity not found in manifest")
            continue
        if record.get("split") != "calibration":
            errors.append(f"{key}: held-out annotation is not allowed")
            continue
        if row.get("record_digest") != record_digest(record):
            errors.append(f"{key}: record identity digest mismatch")
        try:
            validate_labels(row.get("labels", {}), record, by_id)
        except ValueError as exc:
            errors.append(f"{key}: {exc}")
        try:
            bounded_evidence(root, record)
        except ValueError as exc:
            errors.append(f"{key}: {exc}")
    return errors


def _ask_int(prompt: str, allow_null: bool = False, default: int | None = None) -> int | None:
    while True:
        value = input(prompt).strip()
        if not value and default is not None:
            return default
        if value.lower() in {"n", "null", "none"}:
            return None
        if allow_null and value.lower() in {"", "null", "none"}:
            return None
        try:
            return int(value)
        except ValueError:
            print("Enter an integer" + (" or blank for null." if allow_null else "."))


def _choice(prompt: str, choices: dict[str, Any], default: str | None = None) -> Any:
    """Read a single-key choice; labels stay visible so no enum memorization is needed."""
    while True:
        value = input(prompt).strip().lower()
        if not value and default is not None:
            value = default
        if value in choices:
            return choices[value]
        print("Choose one of: " + ", ".join(choices))


def _collect_labels(record: dict[str, Any], annotator_id: str) -> dict[str, Any]:
    start = record["source"]["start_seconds"]
    end = record["source"]["end_seconds"]
    labels = {
        "summary_worthiness": _choice("summary [0=none, 1=some, 2=strong] (0/1/2): ", {"0": 0, "1": 1, "2": 2}),
        "entertainment_value": _choice("entertainment [0=none, 1=some, 2=strong] (0/1/2): ", {"0": 0, "1": 1, "2": 2}),
        "acceptable_click_start_seconds": _ask_int(f"click start [{start}] (Enter=default, n=null): ", default=start),
        "acceptable_click_end_seconds": _ask_int(f"click end [{end}] (Enter=default, n=null): ", default=end),
        "evidence_modality": _choice("evidence [1=STT, 2=chat, 3=STT+chat, 4=unknown] (3): ", {"1": "stt", "2": "chat", "3": "stt+chat", "4": "unknown"}, "3"),
        "confidence": _choice("confidence [1=low, 2=medium, 3=high] (2): ", {"1": "low", "2": "medium", "3": "high"}, "2"),
        "duplicate_relation": "none",
        "annotator_id": annotator_id,
        "notes": None,
    }
    click_start = labels["acceptable_click_start_seconds"]
    if click_start is None:
        labels["acceptable_click_end_seconds"] = None
    duplicate = input("duplicate [Enter=none, 1=same event, 2=related event]: ").strip().lower()
    if duplicate in {"1", "2"}:
        relation = "same_event" if duplicate == "1" else "related_event"
        target = input("target window_id: ").strip()
        labels["duplicate_relation"] = f"{relation}:{target}"
    notes = input("notes [Enter=empty]: ").strip()
    labels["notes"] = notes or None
    return labels


def annotate(args: argparse.Namespace) -> int:
    records = load_manifest(args.manifest)
    by_id = {row["window_id"]: row for row in records}
    annotations = load_annotations(args.annotations)
    pending = [row for row in records if row.get("split") == "calibration" and row["window_id"] not in annotations]
    print(f"Calibration records: {len(records) - sum(row.get('split') == 'held_out' for row in records)}; pending: {len(pending)}")
    annotator_id = getattr(args, "annotator", None)
    if pending and not annotator_id:
        annotator_id = input("Annotator ID (set once for this run): ").strip()
        if not annotator_id:
            print("Annotator ID is required.")
            return 2
    for record in pending:
        print(f"\n[{record['window_id']}] {record['strata']} (Enter=annotate, s=skip, r=reopen, q=quit)")
        try:
            url, opened = open_vod(record)
            print(f"VOD: {url} ({'browser opened' if opened else 'browser unavailable; continue with text evidence'})")
        except ValueError as exc:
            print(f"VOD: unavailable ({exc}); continue with text evidence")
        evidence = bounded_evidence(args.root, record)
        for kind in ("stt", "chat"):
            print(f"-- {kind.upper()} ({len(evidence[kind])} bounded lines) --")
            print("\n".join(evidence[kind]) or "(no lines)")
        action = input("Action [Enter=annotate, s=skip, r=reopen, q=quit]: ").strip().lower()
        if action == "q":
            break
        if action == "s":
            continue
        if action == "r":
            try:
                url, opened = open_vod(record)
                print(f"Reopen VOD: {url} ({'browser opened' if opened else 'browser unavailable'})")
            except ValueError as exc:
                print(f"VOD unavailable: {exc}")
            action = input("Continue annotation? [Enter=yes, s=skip, q=quit]: ").strip().lower()
            if action == "q":
                break
            if action == "s":
                continue
        labels = _collect_labels(record, annotator_id)
        try:
            validate_labels(labels, record, by_id)
        except ValueError as exc:
            print(f"Not saved: {exc}")
            continue
        annotations[record["window_id"]] = {"window_id": record["window_id"], "record_digest": record_digest(record), "labels": labels}
        atomic_write_annotations(args.annotations, annotations)
        print(f"Saved {args.annotations}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("annotate", "validate"))
    parser.add_argument("--manifest", type=Path, default=Path(".ai/evaluation/benchmark/manifest.jsonl"))
    parser.add_argument("--annotations", type=Path, default=Path(".ai/evaluation/benchmark/annotations.jsonl"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--annotator", help="annotator identity (otherwise ask once at startup)")
    args = parser.parse_args()
    try:
        if args.command == "annotate":
            return annotate(args)
        errors = validate_annotations(args.manifest, args.annotations, args.root)
        if errors:
            print("\n".join(errors))
            return 1
        print(f"validated {len(load_annotations(args.annotations))} annotations")
        return 0
    except ValueError as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
