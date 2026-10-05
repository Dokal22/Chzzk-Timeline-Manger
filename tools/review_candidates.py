#!/usr/bin/env python3
"""Build a self-contained, read-only CA002 review page from CA003 audit JSON."""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


def js_json(value: Any) -> str:
    # Prevent data in the embedded JSON from closing the script element.
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            .replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("&", "\\u0026").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


PAGE = r'''<!doctype html>
<html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CA002 · 후보 근거 검토</title>
<style>
:root{font:15px/1.5 system-ui,sans-serif;color:#18212b;background:#f3f5f8}body{margin:0}header{background:#172637;color:white;padding:20px 4vw}h1{margin:0 0 5px;font-size:1.4rem}header p{margin:0;color:#c8d4e0}.bar{position:sticky;top:0;background:#fff;padding:12px 4vw;box-shadow:0 2px 8px #17263718;display:flex;gap:8px;flex-wrap:wrap;z-index:2}input,select{padding:9px;border:1px solid #bbc6d1;border-radius:6px;background:white}input{min-width:220px;flex:1}main{padding:20px 4vw}.note{background:#fff6dc;padding:12px;border-radius:8px;margin-bottom:14px}.candidate{background:white;border:1px solid #dce2e8;border-radius:9px;margin:10px 0;padding:14px}.top{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.title{font-weight:700;font-size:1.05rem}.meta{color:#526171;font-size:.88rem}.badge{display:inline-block;border-radius:99px;background:#e9eef4;padding:2px 9px;font-size:.8rem}.score{white-space:nowrap;font-variant-numeric:tabular-nums}.cols{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:10px}.box{background:#f7f9fb;padding:10px;border-radius:7px;min-width:0}.box h3{font-size:.9rem;margin:0 0 6px}.lines{white-space:pre-wrap;overflow-wrap:anywhere;max-height:240px;overflow:auto;font-size:.88rem}.actions{margin-top:10px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}a{color:#075eab}footer{color:#526171;font-size:.85rem;margin-top:12px}@media(max-width:700px){.cols{grid-template-columns:1fr}.top{display:block}.score{margin-top:6px}}
</style>
<header><h1>CA002 · 후보 근거 검토</h1><p>CA003 감사 자료의 후보를 원래 시각, 점수, 청크/pass, 주변 STT·샘플 채팅과 함께 확인합니다.</p></header>
<div class="bar"><input id="q" placeholder="내용, 후보 ID, 영상 ID 검색"><select id="exp"><option value="">모든 실험</option></select><select id="status"><option value="">모든 대응 상태</option><option>compatible_unbound</option><option>conflicting</option><option>unknown</option><option>plausible</option><option>ambiguous</option><option>unmatched</option></select><label><input id="unknown" type="checkbox"> 출처가 확인되지 않은 후보만</label></div>
<main><div class="note" id="policy"></div><div id="summary"></div><div id="rows"></div></main>
<script id="audit-data" type="application/json">__DATA__</script>
<script>
const d=JSON.parse(document.getElementById('audit-data').textContent), $=id=>document.getElementById(id);
const exps=[...new Set(d.candidates.flatMap(c=>(c.associations||[]).map(a=>a.experiment)))];for(const e of exps){const o=document.createElement('option');o.value=e;o.textContent=e;$('exp').append(o)}
$('policy').textContent=d.matching_policy;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=n=>{if(n==null)return '시각 없음';const h=Math.floor(n/3600),m=Math.floor(n%3600/60),s=n%60;return [h,m,s].map(x=>String(x).padStart(2,'0')).join(':')};
function render(){const q=$('q').value.toLocaleLowerCase(),e=$('exp').value,s=$('status').value,u=$('unknown').checked;
const rows=d.candidates.filter(c=>{const aa=c.associations||[],assocOK=aa.some(a=>(!e||a.experiment===e)&&(!s||a.compatibility_status===s||a.output_match?.status===s));return (!q||[c.content,c.candidate_id,c.vod_id,c.topic].join(' ').toLocaleLowerCase().includes(q))&&assocOK&&(!u||!aa.some(a=>a.compatibility_status==='compatible_unbound'))});
$('summary').textContent=`${rows.length} / ${d.candidate_count} 후보 · 출력 대응 여부는 텍스트 기반 참고 정보입니다.`;
$('rows').innerHTML=rows.map(c=>{const m=(c.associations||[]).find(a=>a.compatibility_status==='compatible_unbound')?.output_match||{},ev=c.evidence||{},url=c.seconds==null||!c.vod_id?'':`https://chzzk.naver.com/video/${encodeURIComponent(c.vod_id)}?currentTime=${Math.floor(c.seconds)}`;
const lines=x=>x&&x.length?x.map(esc).join('\n'):'이 시각 주변 자료 없음';
const associations=(c.associations||[]).map(a=>`${esc(a.experiment)}/${esc(a.pass)} chunk${esc(a.chunk_index)} · ${esc(a.claimed_vod_id)} ${esc(a.compatibility_status)} · output ${esc(a.output_match?.status||'not compared')}`).join('<br>');
return `<article class="candidate"><div class="top"><div><div class="title">${esc(c.content)}</div><div class="meta">metadata VOD ${esc(c.vod_id||'association unresolved')} · ${esc(c.timestamp)} · raw ${esc(c.raw.path)} #${esc(c.raw.item_index)} · SHA-256 ${esc(c.raw.sha256)}</div></div><div class="score">wf ${esc(c.raw_score?.wf)} · wi ${esc(c.raw_score?.wi)}<br><span class="badge">${esc(m.status||'unmatched')}</span></div></div>
<div class="actions">${url?`<a target="_blank" rel="noopener" href="${url}">metadata-compatible VOD의 후보 시각 열기</a>`:''}<span class="meta">ID ${esc(c.candidate_id)} · 최종 출력 ${m.timestamp?`${esc(m.timestamp)} (${esc(m.delta_seconds)}초 차이)`:m.lines?`후보 행: ${esc(m.lines.join(', '))}`:'대응 없음'} · 제외 사유 ${esc(m.exclusion_reason||'unknown')}</span></div><div class="meta">${associations}</div>
<div class="cols"><section class="box"><h3>주변 STT · ${esc(ev.window_seconds?.join('–')||'')}</h3><div class="lines">${lines(ev.stt?.lines)}</div></section><section class="box"><h3>압축 채팅 샘플</h3><div class="lines">${lines(ev.chat_sample?.lines)}</div></section></div>
<footer>compatible_unbound는 수치 조건과 metadata 반환 수의 일치만 뜻하며 원본 hash의 run binding은 확인되지 않았습니다. 텍스트 유사도/근접 시각은 사건 동일성 검증이 아닙니다. 채팅은 캐시된 샘플입니다.</footer></article>`}).join('')}
for(const id of ['q','exp','status','unknown'])$(id).addEventListener('input',render);render();
</script></html>'''


def build_page(audit: dict[str, Any]) -> str:
    return PAGE.replace("__DATA__", js_json(audit))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--audit", type=Path, default=Path("experiment_artifacts/ca003_audit_v2/candidate_audit.json"))
    p.add_argument("--output", type=Path, default=Path("experiment_artifacts/ca003_audit_v2/review.html"))
    a = p.parse_args()
    audit = json.loads(a.audit.read_text(encoding="utf-8"))
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(build_page(audit), encoding="utf-8")
    print(f"Wrote {a.output}")


if __name__ == "__main__":
    main()
