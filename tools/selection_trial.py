#!/usr/bin/env python3
"""Compare chronological baseline and score-budget selection offline.

Uses the repository's exact merge function extracted from its AST, avoiding
Timeline.py's unrelated runtime imports. This is a candidate-level renderer
replay: STT timestamp correction and Codex nickname correction are not rerun.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Any

NOTICE = "🤖 이 댓글은 방송 하이라이트를 AI가 분석하여 생성한 타임라인으로 다소 부정확한 부분이 있을 수 있습니다."
LIMIT = 5000


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_production_merge(source: Path):
    tree = ast.parse(source.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "merge_and_format_final_timeline")
    module = ast.Module(body=[fn], type_ignores=[])
    scope: dict[str, Any] = {"re": re}
    exec(compile(module, str(source), "exec"), scope)
    return scope[fn.name]


def full_render(merge, candidates: list[dict[str, Any]], title: str) -> str:
    items = [{"seconds": c["seconds"], "timestamp": c["timestamp"],
              "group_large": str(c.get("group_large") or ""),
              "topic": str(c.get("topic") or ""), "content": str(c.get("content") or "")}
             for c in candidates]
    body = merge(items)
    return f"{NOTICE}\n[00:00:00] {title}\n\n{body}"


def eligible(candidate: dict[str, Any]) -> bool:
    score = candidate.get("raw_score") or {}
    wf, wi = score.get("wf"), score.get("wi")
    return (isinstance(wf, (int, float)) and not isinstance(wf, bool)
            and isinstance(wi, (int, float)) and not isinstance(wi, bool)
            and (wf + wi >= 40 or wi >= 25))


def collect_pool(audit: dict[str, Any], vod_id: str) -> tuple[list[dict[str, Any]], list[str]]:
    pool, excluded = [], []
    for c in audit.get("candidates", []):
        claimed = [a for a in c.get("associations", []) if a.get("claimed_vod_id") == vod_id]
        if not claimed:
            continue
        usable = [a for a in c.get("associations", [])
                  if a.get("claimed_vod_id") == vod_id and a.get("compatibility_status") == "compatible_unbound"]
        if not usable:
            excluded.append(c.get("candidate_id", "unknown"))
            continue
        if c.get("seconds") is None or not isinstance(c.get("content"), str) or not eligible(c):
            continue
        row = dict(c)
        row["provenance_status"] = "compatible_unbound"
        pool.append(row)
    return pool, excluded


def run_trial(audit: dict[str, Any], vod_id: str, title: str, merge, budget: int = LIMIT) -> dict[str, Any]:
    pool, excluded = collect_pool(audit, vod_id)
    chrono = sorted(pool, key=lambda c: (c["seconds"], c["candidate_id"]))
    baseline_text = full_render(merge, chrono, title)
    # One deliberately simple alternative: highest raw wf+wi first; include an
    # item only when the actual rendered output, including notice/title, fits.
    ranked = sorted(pool, key=lambda c: (-(c["raw_score"]["wf"] + c["raw_score"]["wi"]),
                                         c["seconds"], c["candidate_id"]))
    selected: list[dict[str, Any]] = []
    decisions = {}
    for c in ranked:
        proposed = sorted(selected + [c], key=lambda row: (row["seconds"], row["candidate_id"]))
        rendered = full_render(merge, proposed, title)
        if len(rendered) <= budget:
            selected.append(c)
            decisions[c["candidate_id"]] = "selected_score_rank_fits_budget"
        else:
            decisions[c["candidate_id"]] = "excluded_rendered_character_budget"
    selected_chrono = sorted(selected, key=lambda c: (c["seconds"], c["candidate_id"]))
    alternative_text = full_render(merge, selected_chrono, title)
    if len(alternative_text) > budget:
        raise AssertionError("budget selector emitted an over-budget result")
    return {"schema_version": 1, "experiment": "ca003-score-budget-v1", "vod_id": vod_id,
            "title": title, "budget": {"limit": budget, "unit": "Python Unicode code points (len); matches current Main.py check"},
            "pool_count": len(pool), "excluded_unbound_candidate_ids": sorted(excluded),
            "pool_sha256": digest(json.dumps([{ "candidate_id": c["candidate_id"], "raw": c["raw"],
                                                "raw_score": c["raw_score"]} for c in pool],
                                              ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()),
            "renderer": {"source": "src/code/Timeline.py", "function": "merge_and_format_final_timeline",
                         "function_sha256": _function_digest(Path("src/code/Timeline.py")),
                         "mode": "exact_merge_function_plus_Main.py_notice_and_title",
                         "omissions": ["STT timestamp correction", "Codex nickname correction", "input cleanup before merge"]},
            "provenance_limit": audit.get("matching_policy"),
            "baseline": {"policy": "all eligible pool candidates in chronological order", "selected_ids": [c["candidate_id"] for c in chrono],
                         "rendered_characters": len(baseline_text), "within_budget": len(baseline_text) <= budget,
                         "text": baseline_text},
            "alternative": {"policy": "descending wf+wi; greedily include if exact trial renderer stays within budget",
                             "selected_ids": [c["candidate_id"] for c in selected_chrono],
                             "rendered_characters": len(alternative_text), "within_budget": len(alternative_text) <= budget,
                             "text": alternative_text,
                             "decisions": [{"candidate_id": c["candidate_id"], "wf": c["raw_score"]["wf"],
                                            "wi": c["raw_score"]["wi"], "score_sum": c["raw_score"]["wf"] + c["raw_score"]["wi"],
                                            "rank": i + 1, "decision": decisions[c["candidate_id"]],
                                            "source_status": c["provenance_status"]} for i, c in enumerate(ranked)]},
            "changed_candidate_ids": sorted(set(c["candidate_id"] for c in chrono) - set(c["candidate_id"] for c in selected)),
            "quality_claim": None}


def _function_digest(source: Path) -> str:
    tree = ast.parse(source.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "merge_and_format_final_timeline")
    return digest(ast.dump(fn, include_attributes=False).encode())


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--audit", type=Path, default=Path("experiment_artifacts/ca003_audit_v2/candidate_audit.json"))
    p.add_argument("--metadata", type=Path, action="append", default=[])
    p.add_argument("--vod-id")
    p.add_argument("--output-dir", type=Path, default=Path("experiment_artifacts/feedback/selection_trial"))
    p.add_argument("--budget", type=int, default=LIMIT)
    a = p.parse_args()
    audit_bytes = a.audit.read_bytes()
    audit = json.loads(audit_bytes)
    metadata_files = a.metadata or sorted(Path(".").glob("TL_VOD_*_t[12].metadata.json"))
    metas = [json.loads(path.read_text(encoding="utf-8-sig")) for path in metadata_files]
    vod_id = a.vod_id or max(sorted({str(m.get("vod_id")) for m in metas}),
                             key=lambda vid: sum(c.get("vod_id") == vid for c in audit.get("candidates", [])))
    matching = [m for m in metas if str(m.get("vod_id")) == vod_id]
    title = next((m.get("title") for m in matching if m.get("title")), "[제목 미상]")
    source = Path("src/code/Timeline.py")
    result = run_trial(audit, vod_id, title, load_production_merge(source), a.budget)
    result["inputs"] = {"audit_path": str(a.audit), "audit_sha256": digest(audit_bytes),
                        "metadata": [{"path": str(path), "sha256": digest(path.read_bytes())}
                                     for path, meta in zip(metadata_files, metas) if str(meta.get("vod_id")) == vod_id]}
    out = a.output_dir / vod_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "trial.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "baseline.txt").write_text(result["baseline"]["text"], encoding="utf-8")
    (out / "alternative.txt").write_text(result["alternative"]["text"], encoding="utf-8")
    print(f"Wrote {out}: pool={result['pool_count']}, baseline={result['baseline']['rendered_characters']} chars, alternative={result['alternative']['rendered_characters']} chars")


if __name__ == "__main__":
    main()
