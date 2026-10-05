#!/usr/bin/env python3
"""Build a local CA002 calibration review page from fixed windows and audit v2."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from tools.annotate_benchmark import load_annotations, record_digest, validate_annotations
    from tools.benchmark_manifest import parse_timestamp, TIMESTAMP_RE
except ModuleNotFoundError:
    from annotate_benchmark import load_annotations, record_digest, validate_annotations
    from benchmark_manifest import parse_timestamp, TIMESTAMP_RE


def safe_path(root: Path, rel: str | Path) -> Path:
    path = Path(rel)
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    if resolved != root.resolve() and root.resolve() not in resolved.parents:
        raise ValueError(f"path escapes project root: {rel}")
    return resolved


def evidence_for(root: Path, record: dict[str, Any], kind: str, line_cap: int = 40, char_cap: int = 6000) -> dict[str, Any]:
    source = record["source"]
    key = f"{kind}_path"
    path = safe_path(root, source[key])
    start, end = source["start_seconds"], source["end_seconds"]
    lines, used, truncated = [], 0, False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = TIMESTAMP_RE.match(line)
        if not match:
            continue
        second = parse_timestamp(match.group("stamp"))
        if start <= second < end:
            if len(lines) >= line_cap or used + len(line) + 1 > char_cap:
                truncated = True
                break
            lines.append({"timestamp": match.group("stamp"), "seconds": second, "text": line})
            used += len(line) + 1
    return {"lines": lines, "truncated": truncated, "limits": {"max_lines": line_cap, "max_chars": char_cap}}


def build_review(root: Path, manifest_path: Path, annotations_path: Path,
                 audit_path: Path) -> dict[str, Any]:
    root = root.resolve()
    rows = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not 6 <= len(rows) <= 12:
        raise ValueError(f"fixed calibration manifest must contain 6–12 rows; got {len(rows)}")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    annotations_exist = annotations_path.is_file()
    annotations, annotation_errors = {}, []
    if annotations_exist:
        try:
            annotations = load_annotations(annotations_path)
            annotation_errors = validate_annotations(manifest_path, annotations_path, root)
        except (ValueError, OSError) as exc:
            annotation_errors = [f"annotation file: {exc}"]
    errors_by_id = {}
    for err in annotation_errors:
        record = next((r for r in rows if err.startswith(r["window_id"] + ":")), None)
        if record:
            errors_by_id.setdefault(record["window_id"], []).append(err[len(record["window_id"]) + 1:].strip())

    windows = []
    for record in rows:
        source = record["source"]
        stt_path, chat_path = (safe_path(root, source[f"{kind}_path"]) for kind in ("stt", "chat"))
        actual_hashes = {"stt_sha256": hashlib.sha256(stt_path.read_bytes()).hexdigest(),
                         "chat_sha256": hashlib.sha256(chat_path.read_bytes()).hexdigest()}
        expected_hashes = record.get("source_hashes", {})
        source_status = "verified" if expected_hashes == actual_hashes else "source_hash_mismatch"
        ann = annotations.get(record["window_id"])
        if not annotations_exist:
            label_status, labels = "annotation_file_absent", None
        elif ann is None:
            label_status, labels = "unlabeled", None
        elif errors_by_id.get(record["window_id"]):
            label_status, labels = "annotation_invalid", ann.get("labels")
        elif ann.get("record_digest") != record_digest(record):
            label_status, labels = "digest_mismatch", ann.get("labels")
        else:
            label_status, labels = "labeled", ann.get("labels")

        vod_candidates = []
        start, end = source["start_seconds"], source["end_seconds"]
        for c in audit.get("candidates", []):
            if c.get("vod_id") != record["vod_id"] or not isinstance(c.get("seconds"), int):
                continue
            if start <= c["seconds"] < end:
                associations = [{"claimed_vod_id": a.get("claimed_vod_id"), "experiment": a.get("experiment"),
                                "pass": a.get("pass"), "chunk_index": a.get("chunk_index"),
                                "status": a.get("compatibility_status")}
                               for a in c.get("associations", [])]
                vod_candidates.append({"candidate_id": c["candidate_id"], "timestamp": c.get("timestamp"),
                                      "seconds": c["seconds"], "content": c.get("content"),
                                      "raw_score": c.get("raw_score"), "raw_sha256": c.get("raw", {}).get("sha256"),
                                      "source_status": "compatible_unbound", "associations": associations})
        vod_candidates.sort(key=lambda c: c["seconds"])
        windows.append({"window_id": record["window_id"], "vod_id": record["vod_id"],
                        "start_seconds": start, "end_seconds": end,
                        "start_label": parse_timestamp(str(start // 3600).zfill(2)+":"+str(start % 3600 // 60).zfill(2)+":"+str(start % 60).zfill(2)),
                        "strata": record.get("strata"), "selection_roles": record.get("selection_roles", []),
                        "source_status": source_status, "source_expected_hashes": expected_hashes,
                        "source_actual_hashes": actual_hashes,
                        "label_status": label_status, "labels": labels,
                        "annotation_errors": errors_by_id.get(record["window_id"], []),
                        "stt": evidence_for(root, record, "stt"), "chat": evidence_for(root, record, "chat"),
                        "candidates": vod_candidates})
    return {"window_count": len(windows), "vod_count": len({w["vod_id"] for w in windows}),
            "annotation_file_exists": annotations_exist, "annotation_file": str(annotations_path),
            "annotation_file_errors": [e for e in annotation_errors if not any(e.startswith(r["window_id"] + ":") for r in rows)],
            "candidate_policy": audit.get("matching_policy", "audit policy unavailable"),
            "windows": windows}


def html_page(data: dict[str, Any]) -> str:
    embedded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    for old, new in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"), ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
        embedded = embedded.replace(old, new)
    return PAGE.replace("__DATA__", embedded)


PAGE = r'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CA002 고정 창 검토</title>
<style>body{margin:0;background:#f2f5f8;color:#172330;font:15px/1.5 system-ui}header{background:#183149;color:white;padding:18px 4vw}h1{margin:0}header p{margin:5px 0 0;color:#d5e1eb}.toolbar{position:sticky;top:0;background:white;padding:12px 4vw;display:flex;gap:9px;align-items:center;box-shadow:0 2px 8px #0002;z-index:2}select,input{padding:9px;border:1px solid #bbc6d0;border-radius:6px}main{padding:20px 4vw}.notice{background:#fff5d7;padding:12px;border-radius:8px;margin-bottom:12px}.card{background:white;border:1px solid #dce2e8;border-radius:9px;padding:15px}.meta{color:#4e5e6d;font-size:.88rem}.nav{display:flex;justify-content:space-between;margin:12px 0}.cols{display:grid;grid-template-columns:1fr 1fr;gap:12px}.box{background:#f7f9fb;border-radius:8px;padding:12px;min-width:0}.box h2{font-size:1rem;margin:0 0 8px}.line{border-bottom:1px solid #e6ebef;padding:5px 0;overflow-wrap:anywhere}.line a,.candidate a{white-space:nowrap;color:#075d9e}.candidate{border-top:1px solid #ddd;padding:9px 0}.candidate strong{display:block}.labels{white-space:pre-wrap;background:#eef2f5;padding:10px;border-radius:6px}.badge{display:inline-block;padding:2px 8px;border-radius:20px;background:#e7edf2;margin-right:5px}.trunc{color:#a33;font-weight:600}@media(max-width:720px){.cols{grid-template-columns:1fr}.toolbar{flex-wrap:wrap}}</style>
<header><h1>CA002 · 고정 calibration 창</h1><p>12개 source grounded 창, 원래 초 링크, 기존 라벨 상태, CA003 후보 시간 겹침을 표시합니다.</p></header>
<div class="toolbar"><button id="prev">이전</button><select id="pick"></select><button id="next">다음</button><input id="q" placeholder="현재 창 내 STT·채팅·후보 검색"></div><main><div id="notice" class="notice"></div><div id="root"></div></main>
<script id="data" type="application/json">__DATA__</script><script>
const d=JSON.parse(document.getElementById('data').textContent),$=x=>document.getElementById(x),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),fmt=n=>{let h=Math.floor(n/3600),m=Math.floor(n%3600/60),s=n%60;return [h,m,s].map(x=>String(x).padStart(2,'0')).join(':')};let index=0;
d.windows.forEach((w,i)=>{let o=document.createElement('option');o.value=i;o.textContent=`${w.vod_id} · ${fmt(w.start_seconds)} · ${w.selection_roles.join(', ')}`;$('pick').append(o)});
$('notice').textContent=d.annotation_file_exists?`라벨 파일: ${d.annotation_file}. 저장된 annotation은 digest 검증 결과를 표시합니다.${d.annotation_file_errors.length?' 파일 오류: '+d.annotation_file_errors.join('; '):''}`:`annotation 파일이 없습니다. ${d.window_count}개 창은 모두 미라벨이며, 자동 라벨은 없습니다.`;
function render(){index=Number($('pick').value||0);let w=d.windows[index],q=$('q').value.toLocaleLowerCase();$('pick').value=index;
const rows=(kind)=>w[kind].lines.filter(x=>!q||x.text.toLocaleLowerCase().includes(q)).map(x=>`<div class="line"><a target="_blank" rel="noopener" href="https://chzzk.naver.com/video/${encodeURIComponent(w.vod_id)}?currentTime=${x.seconds}">${fmt(x.seconds)} 열기</a> · ${esc(x.text)}</div>`).join('')||'<div class="meta">검색/창에 맞는 행이 없습니다.</div>';
const cand=w.candidates.filter(c=>!q||String(c.content).toLocaleLowerCase().includes(q)||c.candidate_id.includes(q)).map(c=>`<div class="candidate"><strong>${esc(c.content)}</strong><span class="meta">${esc(c.timestamp)} · wf ${esc(c.raw_score?.wf)} / wi ${esc(c.raw_score?.wi)} · ${esc(c.source_status)} · ${esc(c.candidate_id)}</span> <a target="_blank" rel="noopener" href="https://chzzk.naver.com/video/${encodeURIComponent(w.vod_id)}?currentTime=${c.seconds}">후보 시각 열기</a><div class="meta">metadata 연결 주장: ${c.associations.map(a=>`${esc(a.claimed_vod_id)} ${esc(a.experiment)}/${esc(a.pass)} chunk${esc(a.chunk_index)}=${esc(a.status)}`).join(' · ')}</div></div>`).join('')||'<div class="meta">이 시간대에 연결된 감사 후보가 없습니다.</div>';
let labels=w.labels?JSON.stringify(w.labels,null,2):w.label_status;
$('root').innerHTML=`<div class="nav"><span>${index+1} / ${d.window_count}</span><span>${esc(w.window_id)} · ${fmt(w.start_seconds)}–${fmt(w.end_seconds)} · <span class="badge">source ${esc(w.source_status)}</span><span class="badge">label ${esc(w.label_status)}</span></span></div><section class="card"><div class="meta">표집 역할: ${esc(w.selection_roles.join(', '))} · STT/chat source SHA-256 확인: ${esc(w.source_actual_hashes.stt_sha256.slice(0,12))} / ${esc(w.source_actual_hashes.chat_sha256.slice(0,12))}</div><div class="labels">${esc(labels)}${w.annotation_errors.length?'\n검증 오류: '+esc(w.annotation_errors.join('; ')):''}</div><div class="cols"><section class="box"><h2>STT ${w.stt.truncated?'<span class="trunc">표시 제한으로 잘림</span>':''}</h2>${rows('stt')}</section><section class="box"><h2>압축 채팅 ${w.chat.truncated?'<span class="trunc">표시 제한으로 잘림</span>':''}</h2>${rows('chat')}</section></div><section class="box"><h2>시간 범위에 놓인 CA003 후보</h2><div class="meta">시간 구간 연결만 표시하며 같은 사건이라고 판정하지 않습니다. provenance는 compatible_unbound입니다.</div>${cand}</section></section>`}
$('pick').addEventListener('change',render);$('q').addEventListener('input',render);$('prev').onclick=()=>{$('pick').value=Math.max(0,index-1);render()};$('next').onclick=()=>{$('pick').value=Math.min(d.windows.length-1,index+1);render()};render();
</script></html>'''


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path.cwd())
    p.add_argument("--manifest", type=Path, default=Path("experiment_artifacts/ca002_review/manifest.jsonl"))
    p.add_argument("--annotations", type=Path, default=Path("experiment_artifacts/ca002_review/annotations.jsonl"))
    p.add_argument("--audit", type=Path, default=Path("experiment_artifacts/ca003_audit_v2/candidate_audit.json"))
    p.add_argument("--output", type=Path, default=Path("experiment_artifacts/ca002_review/review.html"))
    args = p.parse_args()
    root = args.root.resolve()
    paths = [safe_path(root, pth) for pth in (args.manifest, args.annotations, args.audit, args.output)]
    manifest, annotations, audit, output = paths
    data = build_review(root, manifest, annotations, audit)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html_page(data), encoding="utf-8")
    print(f"wrote {output.relative_to(root)}: {data['window_count']} windows, {data['vod_count']} VODs, labels file {'present' if data['annotation_file_exists'] else 'absent'}")


if __name__ == "__main__":
    main()
