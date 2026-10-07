#!/usr/bin/env python3
"""Build a deterministic, content-free annotation manifest from local VOD artifacts.

Example:
    python tools/benchmark_manifest.py --output-dir .ai/evaluation/benchmark

The generated JSONL contains one-minute windows and aggregate evidence only.  Raw
STT/chat text is intentionally never copied to the manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

TIMESTAMP_RE = re.compile(r"^\s*\[(?P<stamp>\d{1,2}:\d{2}(?::\d{2})?)\]")
FIRE = "🔥"
WINDOW_SECONDS = 60


def parse_timestamp(value: str) -> int:
    parts = [int(part) for part in value.split(":")]
    if len(parts) == 2:
        minutes, seconds = parts
        if seconds >= 60:
            raise ValueError(f"invalid timestamp: {value}")
        return minutes * 60 + seconds
    if len(parts) == 3:
        hours, minutes, seconds = parts
        if minutes >= 60 or seconds >= 60:
            raise ValueError(f"invalid timestamp: {value}")
        return hours * 3600 + minutes * 60 + seconds
    raise ValueError(f"invalid timestamp: {value}")


def read_timestamps(path: Path) -> list[tuple[int, bool]]:
    rows: list[tuple[int, bool]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        match = TIMESTAMP_RE.match(line)
        if not match:
            continue
        try:
            second = parse_timestamp(match.group("stamp"))
        except ValueError as exc:
            raise ValueError(f"{path}:{line_number}: {exc}") from exc
        rows.append((second, FIRE in line))
    if not rows:
        raise ValueError(f"no supported timestamped rows found: {path}")
    return rows


def quantile_bucket(value: int, values: list[int]) -> str:
    ordered = sorted(values)
    if value <= ordered[len(ordered) // 3]:
        return "low"
    if value <= ordered[(2 * len(ordered)) // 3]:
        return "medium"
    return "high"


def stable_rank(*parts: object) -> str:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def paired_artifacts(root: Path) -> list[tuple[str, Path, Path]]:
    pairs = []
    for script in sorted((root / "voicepalette").glob("VOD_*/full_raw_script.txt")):
        vod_id = script.parent.name.removeprefix("VOD_")
        chat = root / "chat_cache" / vod_id / f"chat_{vod_id}_full.txt"
        if chat.is_file():
            pairs.append((vod_id, script, chat))
    if not pairs:
        raise ValueError("no paired voicepalette/VOD_*/full_raw_script.txt and chat_cache artifacts found")
    return pairs


def build_records(root: Path) -> list[dict]:
    records: list[dict] = []
    for vod_id, script_path, chat_path in paired_artifacts(root):
        stt = read_timestamps(script_path)
        chat = read_timestamps(chat_path)
        all_seconds = [second for second, _ in stt + chat]
        max_second = max(all_seconds)
        window_count = math.floor(max_second / WINDOW_SECONDS) + 1
        stt_counts = Counter(second // WINDOW_SECONDS for second, _ in stt)
        chat_counts = Counter(second // WINDOW_SECONDS for second, _ in chat)
        fire_counts = Counter(second // WINDOW_SECONDS for second, tagged in chat if tagged)
        density_values = [chat_counts[index] for index in range(window_count)]
        non_empty_density = [value for value in density_values if value]
        if not non_empty_density:
            continue
        for index in range(window_count):
            if not stt_counts[index] and not chat_counts[index]:
                continue
            start = index * WINDOW_SECONDS
            end = start + WINDOW_SECONDS
            fire_count = fire_counts[index]
            fire_bucket = "none" if fire_count == 0 else "single" if fire_count == 1 else "multiple"
            position = "early" if index < window_count / 3 else "middle" if index < 2 * window_count / 3 else "late"
            seam_distance = min(start % 3600, 3600 - (start % 3600))
            records.append({
                "window_id": f"{vod_id}:{start:08d}-{end:08d}",
                "vod_id": vod_id,
                "split": "",  # assigned after VOD-level split is computed
                "source": {
                    "stt_path": str(script_path.relative_to(root)).replace("\\", "/"),
                    "chat_path": str(chat_path.relative_to(root)).replace("\\", "/"),
                    "start_seconds": start,
                    "end_seconds": end,
                },
                "strata": {
                    "fire_bucket": fire_bucket,
                    "chat_density": quantile_bucket(chat_counts[index], non_empty_density),
                    "position": position,
                    "chunk_boundary": seam_distance <= 30 or seam_distance >= 3570,
                },
                "evidence": {
                    "stt_line_count": stt_counts[index],
                    "chat_line_count": chat_counts[index],
                    "fire_tag_count": fire_count,
                },
                "labels": {
                    "summary_worthiness": None,
                    "entertainment_value": None,
                    "acceptable_click_start_seconds": None,
                    "acceptable_click_end_seconds": None,
                    "evidence_modality": None,
                    "confidence": None,
                    "duplicate_relation": None,
                    "annotator_id": None,
                    "notes": None,
                },
            })
    return records


def assign_splits(records: list[dict]) -> None:
    vod_ids = sorted({record["vod_id"] for record in records})
    if len(vod_ids) < 2:
        raise ValueError("at least two paired VODs are required for leakage-free split")
    calibration_count = max(1, len(vod_ids) // 2)
    calibration = set(vod_ids[:calibration_count])
    for record in records:
        record["split"] = "calibration" if record["vod_id"] in calibration else "held_out"


def select_records(records: list[dict], per_stratum: int) -> list[dict]:
    grouped: dict[tuple[str, str, str, bool, str], list[dict]] = defaultdict(list)
    for record in records:
        strata = record["strata"]
        key = (record["split"], strata["fire_bucket"], strata["chat_density"], strata["position"], strata["chunk_boundary"])
        grouped[key].append(record)
    selected = []
    for key, group in sorted(grouped.items()):
        selected.extend(sorted(group, key=lambda row: stable_rank(row["window_id"]))[:per_stratum])
    return sorted(selected, key=lambda row: (row["split"], row["vod_id"], row["source"]["start_seconds"]))


def write_outputs(output_dir: Path, records: list[dict], per_stratum: int) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    selected = select_records(records, per_stratum)
    manifest_path = output_dir / "manifest.jsonl"
    with manifest_path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in selected:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    metadata = {
        "schema_version": "benchmark-manifest-v1",
        "window_seconds": WINDOW_SECONDS,
        "per_stratum": per_stratum,
        "source_vods": sorted({record["vod_id"] for record in records}),
        "selected_records": len(selected),
        "selection_rule": "stable SHA-256 rank within split/fire_bucket/chat_density/position/chunk_boundary strata",
        "privacy": "manifest contains paths, timestamps, aggregate counts, and empty labels; no source text",
    }
    metadata_path = output_dir / "manifest_metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path, metadata_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="project root containing voicepalette/ and chat_cache/")
    parser.add_argument("--output-dir", type=Path, default=Path(".ai/evaluation/benchmark"))
    parser.add_argument("--per-stratum", type=int, default=8)
    args = parser.parse_args()
    if args.per_stratum < 1:
        parser.error("--per-stratum must be positive")
    records = build_records(args.root.resolve())
    assign_splits(records)
    manifest, metadata = write_outputs(args.output_dir, records, args.per_stratum)
    print(f"wrote {manifest} ({sum(1 for _ in manifest.open(encoding='utf-8'))} records)")
    print(f"wrote {metadata}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
