#!/usr/bin/env python3
"""Build a deduplicated candidate audit with separate run associations.

    python tools/candidate_audit.py --output-dir experiment_artifacts/ca003_audit_v2

Raw artifacts and metadata are read-only. A metadata item_count is the
post-filter returned count, so this tool checks it against numeric eligibility,
not raw JSON length. That check is compatibility evidence, never provenance proof.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from tools.benchmark_manifest import parse_timestamp
except ModuleNotFoundError:  # direct script
    from benchmark_manifest import parse_timestamp

TIMED_LINE = re.compile(r"^\s*\[(\d{2}:\d{2}:\d{2})\]\s*(.*)$")
STAMP = re.compile(r"\b(\d{2}:\d{2}:\d{2})\b")


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def safe_path(root: Path, raw: str | Path) -> Path:
    p = Path(raw)
    if not p.is_absolute():
        p = root / p
    resolved = p.resolve()
    if resolved != root.resolve() and root.resolve() not in resolved.parents:
        raise ValueError(f"path escapes project root: {raw}")
    return resolved


def norm_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"^[🔥⚡\s]+", "", text)
    text = re.sub(r"\[[^\]]+\]", "", text)
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE).casefold()


def timed_rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig", errors="replace").splitlines(), 1):
        match = TIMED_LINE.match(line)
        if match:
            rows.append({"line": line_number, "timestamp": match.group(1),
                         "seconds": parse_timestamp(match.group(1)), "text": match.group(2).strip()})
    return rows


def bounded_lines(path: Path | None, center: int, radius: int, line_cap: int, char_cap: int) -> dict[str, Any]:
    if not path or not path.is_file():
        return {"path": None, "lines": [], "truncated": False, "reason": "source_missing"}
    out, used, truncated = [], 0, False
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        stamp = STAMP.search(line)
        if not stamp:
            continue
        try:
            second = parse_timestamp(stamp.group(1))
        except ValueError:
            continue
        if not center - radius <= second <= center + radius:
            continue
        rendered = line[:500]
        if len(out) >= line_cap or used + len(rendered) + 1 > char_cap:
            truncated = True
            break
        out.append(rendered)
        used += len(rendered) + 1
    return {"path": str(path), "sha256": digest_file(path), "lines": out, "truncated": truncated,
            "truncation_limits": {"lines": line_cap, "characters": char_cap}}


def evidence_paths(root: Path, vod_id: str) -> tuple[Path | None, Path | None]:
    stt = root / "voicepalette" / f"VOD_{vod_id}" / "full_raw_script.txt"
    chatdir = root / "chat_cache" / vod_id
    chats = sorted(chatdir.glob(f"chat_{vod_id}_full*.txt")) if chatdir.exists() else []
    stt = stt if stt.is_file() else None
    chat = chats[0] if chats else None
    return stt, chat


def final_rows(root: Path, metadata_path: Path, metadata: dict[str, Any], errors: list[dict[str, str]]) -> tuple[Path | None, list[dict[str, Any]]]:
    fallback = root / metadata_path.name.replace(".metadata.json", ".txt")
    target = fallback
    if metadata.get("output_path"):
        try:
            target = safe_path(root, metadata["output_path"])
        except ValueError as exc:
            errors.append({"path": metadata_path.name, "error": f"unsafe output path: {exc}"})
            target = fallback
    if not target.is_file():
        errors.append({"path": str(target), "error": "final timeline missing"})
        return None, []
    return target, timed_rows(target)


def match_outputs(content: str, seconds: int | None, outputs: list[dict[str, Any]]) -> dict[str, Any]:
    if seconds is None:
        return {"status": "unknown_timestamp", "event_identity_verified": False}
    hits = [row for row in outputs if norm_text(content) == norm_text(row["text"])]
    close = [row for row in hits if abs(row["seconds"] - seconds) <= 180]
    if len(close) == 1:
        row = close[0]
        return {"status": "plausible", "basis": "normalized_text_and_within_180s", "line": row["line"],
                "timestamp": row["timestamp"], "delta_seconds": row["seconds"] - seconds,
                "event_identity_verified": False}
    if len(close) > 1:
        return {"status": "ambiguous", "basis": "multiple_text_and_time_matches",
                "lines": [row["line"] for row in close], "event_identity_verified": False}
    if hits:
        return {"status": "text_match_time_unconfirmed", "lines": [row["line"] for row in hits], "event_identity_verified": False}
    return {"status": "unmatched", "exclusion_reason": "unknown", "event_identity_verified": False}


def numeric_eligible(item: Any) -> bool | None:
    if not isinstance(item, dict):
        return False
    wf, wi = item.get("wf", 0), item.get("wi", 0)
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in (wf, wi)):
        return None
    return wf + wi >= 40 or wi >= 25


def _metadata_passes(metadata: dict[str, Any], chunk: dict[str, Any]) -> list[dict[str, Any]]:
    return chunk.get("passes") or ([{"pass": "t1", "raw_output_path": chunk.get("raw_output_path"),
                                      "item_count": chunk.get("item_count")}]
                                    if chunk.get("raw_output_path") else [])


def build_audit(root: Path, metadata_files: list[Path], radius: int = 45,
                stt_line_cap: int = 40, chat_line_cap: int = 20, char_cap: int = 6000) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    source_records: list[dict[str, Any]] = []
    unique: dict[tuple[str, int, str], dict[str, Any]] = {}

    for meta_arg in metadata_files:
        try:
            meta_path = safe_path(root, meta_arg)
            meta_bytes = meta_path.read_bytes()
            metadata = json.loads(meta_bytes.decode("utf-8-sig"))
            if not isinstance(metadata, dict):
                raise ValueError("metadata root must be an object")
        except Exception as exc:
            errors.append({"path": str(meta_arg), "error": f"metadata unreadable: {exc}"})
            continue
        vod_id = str(metadata.get("vod_id", ""))
        experiment = str(metadata.get("experiment", "unknown"))
        final_path, outputs = final_rows(root, meta_path, metadata, errors)
        meta_rel = str(meta_path.relative_to(root)).replace("\\", "/")
        meta_hash = digest_bytes(meta_bytes)
        run_checks = []

        for chunk in metadata.get("chunks", []):
            for pinfo in _metadata_passes(metadata, chunk):
                pass_name = str(pinfo.get("pass", "default"))
                raw_ref = pinfo.get("raw_output_path")
                if not raw_ref:
                    errors.append({"path": meta_rel, "error": f"chunk {chunk.get('chunk_index')} missing raw_output_path"})
                    continue
                try:
                    raw_path = safe_path(root, raw_ref)
                    raw_bytes = raw_path.read_bytes()
                    payload = json.loads(raw_bytes.decode("utf-8-sig"))
                    items = payload.get("items", []) if isinstance(payload, dict) else payload
                    if not isinstance(items, list):
                        raise ValueError("expected an item list")
                except Exception as exc:
                    errors.append({"path": str(raw_ref), "error": f"raw JSON unreadable: {exc}"})
                    continue
                raw_hash = digest_bytes(raw_bytes)
                threshold_results = [numeric_eligible(item) for item in items]
                eligible_count = sum(result is True for result in threshold_results)
                unknown_threshold_count = sum(result is None for result in threshold_results)
                returned = pinfo.get("item_count")
                if returned is None or unknown_threshold_count:
                    compatibility = "unknown"
                elif returned == eligible_count:
                    compatibility = "compatible_unbound"
                elif returned > len(items):
                    compatibility = "conflicting"
                else:
                    compatibility = "returned_count_differs_from_numeric_eligibility"
                raw_rel = str(raw_path.relative_to(root)).replace("\\", "/")
                run_check = {"metadata_path": meta_rel, "metadata_sha256": meta_hash,
                             "experiment": experiment, "claimed_vod_id": vod_id,
                             "title": metadata.get("title"),
                             "chunk_index": chunk.get("chunk_index"), "pass": pass_name,
                             "raw_output_path": raw_rel, "raw_output_sha256": raw_hash,
                             "raw_count": len(items), "numeric_eligible_count": eligible_count,
                             "unknown_threshold_count": unknown_threshold_count,
                             "metadata_returned_count": returned, "numeric_count_matches": returned == eligible_count if returned is not None else None,
                             "compatibility_status": compatibility,
                             "chunk_bounds_seconds": [chunk.get("start_sec"), chunk.get("end_sec")],
                             "final_path": str(final_path.relative_to(root)).replace("\\", "/") if final_path else None,
                             "final_sha256": digest_file(final_path) if final_path else None,
                             "final_rows_count": len(outputs)}
                run_checks.append(run_check)
                for index, item in enumerate(items):
                    if not isinstance(item, dict):
                        errors.append({"path": raw_rel, "error": f"chunk {chunk.get('chunk_index')} item {index} is not an object"})
                        continue
                    item_bytes = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                    item_hash = digest_bytes(item_bytes)
                    key = (raw_hash, index, item_hash)
                    candidate = unique.get(key)
                    if candidate is None:
                        candidate_id = "cand-" + digest_bytes(f"{raw_hash}|{index}|{item_hash}".encode())[:24]
                        stamp = item.get("timestamp")
                        timestamp_error = None
                        try:
                            seconds = parse_timestamp(stamp) if isinstance(stamp, str) else None
                            if not isinstance(stamp, str):
                                timestamp_error = "timestamp_missing_or_not_text"
                        except ValueError:
                            seconds = None
                            timestamp_error = "timestamp_invalid"
                        candidate = {"candidate_id": candidate_id, "vod_id": None, "title": None,
                                     "timestamp": stamp, "seconds": seconds, "timestamp_parse_status": "valid" if timestamp_error is None else timestamp_error,
                                     "group_large": item.get("group_large"), "topic": item.get("topic"),
                                     "content": item.get("content", ""), "raw_score": {"wf": item.get("wf"), "wi": item.get("wi")},
                                     "numeric_threshold_eligible": numeric_eligible(item),
                                     "ranking_score": None, "rank_order": None,
                                     "raw": {"sha256": raw_hash, "path": raw_rel, "item_index": index, "item_sha256": item_hash,
                                             "raw_count": len(items)},
                                     "associations": [], "evidence": None}
                        unique[key] = candidate
                    association = {**run_check}
                    if compatibility != "compatible_unbound":
                        association["output_match"] = {"status": "source_status_not_sufficient_for_output_comparison", "event_identity_verified": False}
                    elif candidate["numeric_threshold_eligible"] is False:
                        association["output_match"] = {"status": "below_normal_path_numeric_threshold_not_assessed", "event_identity_verified": False}
                    elif candidate["numeric_threshold_eligible"] is None:
                        association["output_match"] = {"status": "numeric_threshold_unknown", "event_identity_verified": False}
                    elif not isinstance(candidate["content"], str):
                        association["output_match"] = {"status": "invalid_content_type", "event_identity_verified": False}
                    else:
                        association["output_match"] = match_outputs(candidate["content"], candidate["seconds"], outputs)
                    candidate["associations"].append(association)

        source_records.append({"metadata_path": meta_rel, "metadata_sha256": meta_hash,
                               "experiment": experiment, "claimed_vod_id": vod_id,
                               "runs": run_checks})

    # Only create one association record per candidate/run even if duplicate JSON rows recur.
    for candidate in unique.values():
        associations = candidate["associations"]
        usable = [a for a in associations if a["compatibility_status"] == "compatible_unbound"]
        claimed_ids = sorted({a["claimed_vod_id"] for a in usable})
        candidate["vod_id"] = claimed_ids[0] if len(claimed_ids) == 1 else None
        titles = {a.get("title") for a in usable if a.get("title")}
        candidate["title"] = next(iter(titles)) if len(titles) == 1 else None
        # Evidence is read only for one compatible, single-VOD association and labeled as unbound.
        if candidate["vod_id"] and candidate["seconds"] is not None:
            stt, chat = evidence_paths(root, candidate["vod_id"])
            candidate["evidence"] = {"association_status": "compatible_unbound", "window_seconds": [max(0, candidate["seconds"]-radius), candidate["seconds"]+radius],
                                      "stt": bounded_lines(stt, candidate["seconds"], radius, stt_line_cap, char_cap),
                                      "chat_sample": bounded_lines(chat, candidate["seconds"], radius, chat_line_cap, char_cap)}
    claims: dict[tuple[str, str, int], list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for candidate in unique.values():
        for association in candidate["associations"]:
            match = association.get("output_match", {})
            if association["compatibility_status"] == "compatible_unbound" and match.get("status") == "plausible":
                key = (association["metadata_path"], association["pass"], match["line"])
                claims.setdefault(key, []).append((candidate, association))
    for (_, _, line), rows in claims.items():
        if len(rows) > 1:
            ids = sorted({candidate["candidate_id"] for candidate, _ in rows})
            for _, association in rows:
                association["output_match"] = {"status": "ambiguous", "basis": "multiple_raw_candidates_match_one_final_line",
                                                "line": line, "candidate_ids": ids,
                                                "event_identity_verified": False}
    output_statuses = Counter(a.get("output_match", {}).get("status", "unknown")
                              for c in unique.values() for a in c["associations"])
    return {"schema_version": 2, "generated_by": "tools/candidate_audit.py",
            "generated_from": [{"path": s["metadata_path"], "sha256": s["metadata_sha256"]} for s in source_records],
            "numeric_threshold_rule": "normal parser path: wf + wi >= 40 or wi >= 25; absent score fields default to 0 as in production; nonnumeric scores are unknown. Timeline.py's JSON exception fallback bypasses this numeric filter, so the replay cannot prove exact runtime selection.",
            "matching_policy": "Normalized text and within 180 seconds is a plausible text correspondence only. No event identity is inferred. compatibility_unbound means returned count agrees with the numeric threshold on the referenced raw JSON; metadata does not bind the raw hash to that run.",
            "source_status_policy": "compatible_unbound / returned_count_differs_from_numeric_eligibility / conflicting / unknown describe returned-count compatibility with a partial threshold replay, not verified provenance. Conflicting is used only when metadata returned_count exceeds the entire raw item count.",
            "association_row_count": sum(len(c["associations"]) for c in unique.values()),
            "candidate_count": len(unique), "unique_raw_file_count": len({c["raw"]["sha256"] for c in unique.values()}),
            "unique_raw_path_count": len({c["raw"]["path"] for c in unique.values()}),
            "raw_candidate_count": sum({c["raw"]["sha256"]: c["raw"]["raw_count"] for c in unique.values()}.values()),
            "association_status_counts": dict(Counter(a["compatibility_status"] for c in unique.values() for a in c["associations"])),
            "output_match_status_counts": dict(output_statuses),
            "sources": source_records, "errors": errors, "candidates": list(unique.values())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--metadata", type=Path, action="append", help="metadata JSON; repeatable; defaults to root T1/T2 metadata")
    parser.add_argument("--output-dir", type=Path, default=Path("experiment_artifacts/ca003_audit_v2"))
    args = parser.parse_args()
    root = args.root.resolve()
    metas = args.metadata or sorted(root.glob("TL_VOD_*_t[12].metadata.json"))
    if not metas:
        parser.error("no T1/T2 metadata files found")
    report = build_audit(root, metas)
    output_dir = safe_path(root, args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "candidate_audit.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output_path.relative_to(root)}: {report['candidate_count']} unique candidates, {report['association_row_count']} associations")
    print(f"Compatibility counts: {report['association_status_counts']}; parse errors: {len(report['errors'])}")


if __name__ == "__main__":
    main()
