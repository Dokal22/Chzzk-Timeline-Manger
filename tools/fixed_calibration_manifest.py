#!/usr/bin/env python3
"""Create a deterministic, small calibration frame from paired local VOD data."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from tools.benchmark_manifest import build_records, paired_artifacts, stable_rank
except ModuleNotFoundError:
    from benchmark_manifest import build_records, paired_artifacts, stable_rank

SEED = "CA002-fixed-calibration-v1-2026-10-05"
PREFERRED_VODS = ("15425885", "15426176")
ROLES = ("early", "middle", "late", "low_chat", "high_chat", "chunk_boundary")


def select_fixed(records: list[dict[str, Any]], root: Path) -> list[dict[str, Any]]:
    available = {row["vod_id"] for row in records}
    ordered = [v for v in PREFERRED_VODS if v in available]
    ordered.extend(v for v in sorted(available) if v not in ordered)
    selected_vods = ordered[:2]
    if len(selected_vods) < 2:
        raise ValueError("fixed calibration needs at least two VODs with paired local STT/chat")

    selections: list[dict[str, Any]] = []
    for vod_id in selected_vods:
        pool = [r for r in records if r["vod_id"] == vod_id
                and r["evidence"]["stt_line_count"] > 0
                and r["evidence"]["chat_line_count"] > 0]
        chosen: set[str] = set()
        for role in ROLES:
            def matches(row: dict[str, Any]) -> bool:
                strata = row["strata"]
                if role in {"early", "middle", "late"}:
                    return strata["position"] == role
                if role in {"low_chat", "high_chat"}:
                    return strata["chat_density"] == role.removesuffix("_chat")
                start = row["source"]["start_seconds"]
                end = row["source"]["end_seconds"]
                first_boundary = (start // 3600 + 1) * 3600
                return start > 0 and first_boundary <= end

            options = [r for r in pool if r["window_id"] not in chosen and matches(r)]
            if not options:
                raise ValueError(f"cannot fill role {role} for VOD {vod_id}")
            row = min(options, key=lambda r: stable_rank(SEED, vod_id, role, r["window_id"]))
            row = json.loads(json.dumps(row))
            row["split"] = "calibration"
            row["selection_roles"] = [role]
            row["selection_seed"] = SEED
            for key in ("stt_path", "chat_path"):
                row["source"][key] = str((root / row["source"][key]).resolve().relative_to(root.resolve())).replace("\\", "/")
            row["source_hashes"] = {
                "stt_sha256": hashlib.sha256((root / row["source"]["stt_path"]).read_bytes()).hexdigest(),
                "chat_sha256": hashlib.sha256((root / row["source"]["chat_path"]).read_bytes()).hexdigest(),
            }
            chosen.add(row["window_id"])
            selections.append(row)
    return sorted(selections, key=lambda r: (r["vod_id"], r["source"]["start_seconds"]))


def write_manifest(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    metadata = {"schema_version": "ca002-fixed-calibration-v1", "selection_seed": SEED,
                "selected_records": len(rows), "source_vods": sorted({r["vod_id"] for r in rows}),
                "rule": "six distinct 60-second windows per VOD: early, middle, late, low/high chat density, and hourly chunk boundary; deterministic hash tie-break", 
                "labels": "all selected rows begin unlabeled; no labels inferred from chat strata"}
    path.with_name("manifest_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path("experiment_artifacts/ca002_review/manifest.jsonl"))
    args = parser.parse_args()
    root = args.root.resolve()
    records = build_records(root)
    paired = {vod for vod, _, _ in paired_artifacts(root)}
    selected = select_fixed([r for r in records if r["vod_id"] in paired], root)
    out = args.output if args.output.is_absolute() else root / args.output
    write_manifest(out, selected)
    counts = Counter(role for row in selected for role in row["selection_roles"])
    print(f"wrote {out}: {len(selected)} calibration windows across {len({r['vod_id'] for r in selected})} VODs")
    print(f"roles: {dict(counts)}")


if __name__ == "__main__":
    main()
