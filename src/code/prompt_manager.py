"""Section-based, versioned prompt catalog and local editor."""
import copy
import hashlib
import json
import os
import re
import tempfile
import uuid

try:
    from prompt_defaults import DEFAULT_PROMPTS
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from prompt_defaults import DEFAULT_PROMPTS
    except ImportError:
        DEFAULT_PROMPTS = {"timeline": "", "nickname_review": ""}

STAGES = {"timeline": "타임라인 분석", "nickname_review": "최종 교정"}
STORE_NAME = "prompt_registry.json"


def _hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def split_sections(stage, source, text):
    """Split standalone [heading] lines while preserving all source text."""
    matches = list(re.finditer(r"(?m)^(?:🚨\s*)?\[([^\]\r\n]+)\]\s*$", text))
    result = []
    if not matches:
        if text.strip():
            result.append(("역할 및 분석 목적" if stage == "timeline" else "역할 및 검수 목적", text.strip()))
        return result
    prefix = text[:matches[0].start()].strip()
    if prefix:
        result.append(("역할 및 분석 목적" if stage == "timeline" else "역할 및 검수 목적", prefix))
    for i, match in enumerate(matches):
        end = matches[i+1].start() if i+1 < len(matches) else len(text)
        body = text[match.end():end].strip()
        result.append((match.group(1).strip(), body))
    return [(title, body) for title, body in result if body]


def _initial_store(root):
    prompts = []
    active = {stage: [] for stage in STAGES}
    for stage, base in DEFAULT_PROMPTS.items():
        sources = [("builtin", base)]
        if stage == "timeline":
            path = os.path.join(root, "prompt.txt")
            try:
                with open(path, encoding="utf-8") as handle:
                    sources.append(("prompt.txt", handle.read()))
            except OSError:
                pass
        order = 0
        for source, body in sources:
            for index, (title, text) in enumerate(split_sections(stage, source, body)):
                pid = "section-" + _hash(f"{stage}\0{source}\0{index}\0{title}")[:20]
                item = {"id": pid, "stage": stage, "name": title, "version": 1,
                        "text": text, "enabled": True, "order": order,
                        "kind": "builtin", "source": source, "source_hash": _hash(text),
                        "section_index": index, "deleted": False}
                prompts.append(item); active[stage].append({"id": pid, "version": 1}); order += 1
    return {"schema_version": 2, "active": active, "prompts": prompts,
            "order_ids": {stage: [p["id"] for p in prompts if p["stage"] == stage] for stage in STAGES}}


class PromptRegistry:
    def __init__(self, root=None):
        self.root = os.path.abspath(root or os.getcwd())
        self.path = os.path.join(self.root, "prompts", STORE_NAME)
        self.backup_path = self.path + ".v1.bak"
        self.corrupt_backup_path = self.path + ".corrupt.bak"
        self.warning = ""
        self.corrupt = False
        self.data, self.needs_migration = self._load()
        if self.needs_migration:
            try:self.save(migrate=True)
            except OSError as exc:self.warning=f"v1 원본은 유지했습니다. 마이그레이션 저장 실패: {exc}"

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
            version = data.get("schema_version")
            if version == 2:
                if not isinstance(data.get("prompts"), list) or not isinstance(data.get("active"), dict):
                    raise ValueError("잘못된 v2 저장소")
                for item in data["prompts"]: self._validate(item)
                return data, False
            if version == 1:
                migrated = _initial_store(self.root)
                migrated["prompts"].extend(copy.deepcopy(data.get("prompts", [])))
                for stage in STAGES:
                    refs = list(migrated["active"][stage])
                    wanted = set(data.get("active", {}).get(stage, []))
                    latest = {}
                    for item in migrated["prompts"]:
                        if item.get("stage") == stage and item.get("kind") != "builtin" and item.get("id") in wanted:
                            current = latest.get(item["id"])
                            if current is None or item.get("version", 0) > current.get("version", 0): latest[item["id"]] = item
                    refs.extend({"id": item["id"], "version": item["version"]} for item in latest.values())
                    migrated["active"][stage] = refs
                return migrated, True
            raise ValueError("알 수 없는 prompt registry schema")
        except FileNotFoundError:
            return _initial_store(self.root), False
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            self.warning = f"프롬프트 저장소를 읽지 못했습니다: {exc}"
            self.corrupt = True
            return _initial_store(self.root), False

    @staticmethod
    def _validate(item):
        if item.get("stage") not in STAGES or not item.get("id") or not str(item.get("text", "")).strip():
            raise ValueError("프롬프트 항목에 stage, id, text가 필요합니다")
        if not isinstance(item.get("version"), int) or item["version"] < 1:
            raise ValueError("프롬프트 version이 올바르지 않습니다")

    def save(self, migrate=False):
        directory = os.path.dirname(self.path); os.makedirs(directory, exist_ok=True)
        if self.corrupt and os.path.exists(self.path) and not os.path.exists(self.corrupt_backup_path):
            with open(self.path, "rb") as source, open(self.corrupt_backup_path, "xb") as backup:
                backup.write(source.read()); backup.flush(); os.fsync(backup.fileno())
        should_backup_v1 = False
        if os.path.exists(self.path) and not os.path.exists(self.backup_path):
            try:
                with open(self.path, encoding="utf-8") as source: should_backup_v1 = json.load(source).get("schema_version") == 1
            except (OSError, ValueError, TypeError): pass
        if (migrate or should_backup_v1) and os.path.exists(self.path) and not os.path.exists(self.backup_path):
            with open(self.path, "rb") as source, open(self.backup_path, "xb") as backup:
                backup.write(source.read()); backup.flush(); os.fsync(backup.fileno())
        fd, temp = tempfile.mkstemp(prefix=".prompt-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self.data, handle, ensure_ascii=False, indent=2); handle.flush(); os.fsync(handle.fileno())
            os.replace(temp, self.path)
        except Exception:
            try: os.unlink(temp)
            except OSError: pass
            raise

    def list(self, stage, include_deleted=False):
        latest = {}
        for item in self.data["prompts"]:
            if item["stage"] != stage: continue
            old = latest.get(item["id"])
            if old is None or item["version"] > old["version"]: latest[item["id"]] = item
        ordering = self.order_ids(stage)
        rank = {pid: i for i, pid in enumerate(ordering)}
        return sorted([copy.deepcopy(x) for x in latest.values() if include_deleted or not x.get("deleted", False)],
                      key=lambda x: (rank.get(x["id"], len(rank)), x.get("order", 0), x["id"]))

    def order_ids(self, stage):
        """Return normalized catalog order, keeping trashed IDs in their original slots."""
        if stage not in STAGES: raise ValueError("잘못된 프롬프트 단계")
        latest = {}
        for item in self.data["prompts"]:
            if item["stage"] != stage: continue
            old = latest.get(item["id"])
            if old is None or item["version"] > old["version"]: latest[item["id"]] = item
        stored = self.data.setdefault("order_ids", {}).get(stage, [])
        ids = list(latest)
        rank = {pid: index for index, pid in enumerate(ids)}
        ordered = []
        for pid in stored if isinstance(stored, list) else []:
            if pid in latest and pid not in ordered: ordered.append(pid)
        fallback = sorted((p for p in latest if p not in ordered),
                          key=lambda pid: (latest[pid].get("order", 0), rank[pid], pid))
        ordered.extend(fallback)
        self.data.setdefault("order_ids", {})[stage] = ordered
        return list(ordered)

    def set_order(self, stage, ids):
        expected = self.order_ids(stage)
        if len(ids) != len(expected) or set(ids) != set(expected):
            raise ValueError("항목 순서가 현재 프롬프트 목록과 일치하지 않습니다")
        self.data["order_ids"][stage] = list(ids)

    def apply(self, selections, orders):
        """Validate all stages before changing any applied selection or catalog order."""
        normalized = {}
        for stage in STAGES:
            refs = selections[stage]
            items = []
            for ref in refs:
                version = int(ref["version"])
                item = next((p for p in self.data["prompts"] if p["id"] == ref["id"] and p["version"] == version), None)
                if item is None or item["stage"] != stage or item.get("deleted"):
                    raise ValueError("삭제되었거나 존재하지 않는 revision입니다")
                items.append({"id": ref["id"], "version": version})
            if not items: raise ValueError(f"{STAGES[stage]} 단계에서 프롬프트를 최소 1개 선택하세요")
            if len({r["id"] for r in items}) != len(items): raise ValueError("같은 프롬프트 구간을 중복 선택할 수 없습니다")
            order = list(orders[stage])
            if len(order) != len(set(order)) or set(order) != set(self.order_ids(stage)):
                raise ValueError("항목 순서가 현재 프롬프트 목록과 일치하지 않습니다")
            rank = {pid: i for i, pid in enumerate(order)}
            normalized[stage] = (sorted(items, key=lambda ref: rank[ref["id"]]), order)
        for stage, (refs, order) in normalized.items():
            self.data["active"][stage] = refs
            self.data["order_ids"][stage] = order

    def versions(self, prompt_id):
        return sorted([copy.deepcopy(p) for p in self.data["prompts"] if p["id"] == prompt_id], key=lambda p: p["version"])

    def active_refs(self, stage):
        return copy.deepcopy(self.data["active"].get(stage, []))

    def active_ids(self, stage):
        return [r["id"] for r in self.active_refs(stage)]

    def select(self, stage, refs, require_one=True):
        if stage not in STAGES: raise ValueError("잘못된 프롬프트 단계")
        normalized = [{"id": r["id"], "version": int(r["version"])} if isinstance(r, dict) else {"id": r, "version": self._latest_version(r)} for r in refs]
        if require_one and not normalized: raise ValueError(f"{STAGES[stage]} 단계에서 프롬프트를 최소 1개 선택하세요")
        if len({r["id"] for r in normalized}) != len(normalized): raise ValueError("같은 프롬프트 구간을 중복 선택할 수 없습니다")
        valid = {(p["id"], p["version"]) for p in self.data["prompts"] if p["stage"] == stage and not p.get("deleted", False)}
        if any((r["id"], r["version"]) not in valid for r in normalized): raise ValueError("삭제되었거나 존재하지 않는 revision입니다")
        rank = {pid: i for i, pid in enumerate(self.order_ids(stage))}
        normalized.sort(key=lambda ref: rank.get(ref["id"], len(rank)))
        self.data["active"][stage] = normalized

    def _latest_version(self, prompt_id):
        versions = self.versions(prompt_id)
        if not versions: raise ValueError("알 수 없는 프롬프트 ID")
        return versions[-1]["version"]

    def add_version(self, stage, name, text, prompt_id=None, source_section_id=None):
        if stage not in STAGES or not text.strip(): raise ValueError("단계와 비어 있지 않은 본문이 필요합니다")
        prompt_id = prompt_id or uuid.uuid4().hex
        previous = self.versions(prompt_id)
        if previous and previous[0]["stage"] != stage: raise ValueError("프롬프트 단계는 버전 사이에서 바꿀 수 없습니다")
        latest = previous[-1] if previous else {}
        if latest.get("deleted"): raise ValueError("휴지통에서 먼저 복원한 뒤 새 버전을 저장하세요")
        item = {"id": prompt_id, "stage": stage, "name": name.strip() or "새 지침",
                "version": latest.get("version", 0)+1, "text": text, "enabled": True,
                "order": latest.get("order", len(self.list(stage))), "kind": latest.get("kind", "user"),
                "source": latest.get("source", "user"), "source_hash": latest.get("source_hash", ""),
                "source_section_id": source_section_id or latest.get("source_section_id"), "deleted": False}
        self.data["prompts"].append(item)
        if not previous:
            ordering = self.order_ids(stage)
            ordering.append(prompt_id)
            self.data["order_ids"][stage] = ordering
        return copy.deepcopy(item)

    def snapshot(self, validate=True):
        result = {}
        for stage in STAGES:
            refs = self.active_refs(stage)
            if validate and not refs: raise ValueError(f"{STAGES[stage]} 단계에서 프롬프트를 최소 1개 선택하세요")
            by_key = {(p["id"], p["version"]): p for p in self.data["prompts"]}
            result[stage] = [copy.deepcopy(by_key[(r["id"], r["version"])]) for r in refs
                             if (r["id"], r["version"]) in by_key and not by_key[(r["id"], r["version"])].get("deleted", False)]
            if validate and len(result[stage]) != len(refs): raise ValueError(f"{STAGES[stage]} 단계 선택에 삭제된 프롬프트가 있습니다")
        return result

    def delete(self, prompt_id):
        versions = self.versions(prompt_id)
        if not versions: return False
        for item in self.data["prompts"]:
            if item["id"] == prompt_id: item["deleted"] = True
        for stage in STAGES:
            self.data["active"][stage] = [r for r in self.active_refs(stage) if r["id"] != prompt_id]
        return True

    def restore(self, prompt_id):
        versions = self.versions(prompt_id)
        if not versions: return False
        latest = versions[-1]
        for item in self.data["prompts"]:
            if item["id"] == prompt_id: item["deleted"] = False
        return True

    @staticmethod
    def compose(stage, base, snapshot, legacy_text=""):
        """`base` and legacy_text retained in signature for old callers; selected snapshot is authoritative."""
        selected = (snapshot or {}).get(stage, [])
        return "\n\n".join(f"=====[{item.get('name', '지침')} · v{item['version']} · {item.get('source','user')}]=====\n{item['text']}" for item in selected)

    @staticmethod
    def digest(text): return _hash(text)


def open_prompt_editor(root=None):
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
        registry = PromptRegistry(root); window = tk.Tk()
    except Exception: return None
    window.title("프롬프트 구간 설정"); window.geometry("1120x740")
    stage = tk.StringVar(value="timeline"); selected_version = tk.StringVar()
    chosen = {key: registry.active_refs(key) for key in STAGES}
    orders = {key: registry.order_ids(key) for key in STAGES}
    selected = {key: None for key in STAGES}; draft_versions = {key: {r['id']:r['version'] for r in chosen[key]} for key in STAGES}
    outcome = {"applied": False}; current_tab = {"value":"active"}; visible = {"items":[]}
    top=ttk.Frame(window,padding=8);top.pack(fill="x")
    ttk.Label(top,text="적용 단계").pack(side="left")
    selector=ttk.Combobox(top,textvariable=stage,values=[f"{k} — {v}" for k,v in STAGES.items()],state="readonly",width=30);selector.pack(side="left",padx=8);selector.current(0)
    body=ttk.Frame(window,padding=8);body.pack(fill="both",expand=True)
    left=ttk.Frame(body);left.pack(side="left",fill="y")
    notebook=ttk.Notebook(left);notebook.pack(fill="both",expand=True)
    active_tab=ttk.Frame(notebook);trash_tab=ttk.Frame(notebook)
    notebook.add(active_tab,text="프롬프트");notebook.add(trash_tab,text="휴지통")
    active_list=tk.Listbox(active_tab,width=45,height=26,selectmode="extended",exportselection=False);active_list.pack(fill="both",expand=True)
    trash_list=tk.Listbox(trash_tab,width=45,height=26,selectmode="browse",exportselection=False);trash_list.pack(fill="both",expand=True)
    right=ttk.Frame(body);right.pack(side="left",fill="both",expand=True,padx=(12,0))
    name=tk.StringVar();ttk.Entry(right,textvariable=name).pack(fill="x")
    versions=ttk.Combobox(right,textvariable=selected_version,state="readonly",width=16);versions.pack(anchor="w",pady=5)
    text_box=tk.Text(right,wrap="word",undo=True);text_box.pack(fill="both",expand=True)
    status=tk.StringVar(value=registry.warning);ttk.Label(window,textvariable=status).pack(fill="x",padx=8)
    ttk.Label(window,text="후처리 코드는 선택과 별도로 점수 기준에 따라 항목을 거르고, 시간·분류·표기를 보정할 수 있습니다.",foreground="#8a4b08").pack(fill="x",padx=8)

    def stage_key(): return stage.get().split(" — ",1)[0]
    def current_list(): return trash_list if current_tab["value"]=="trash" else active_list
    def current_items(): return visible["items"]
    def refresh(*_, preserve_id=None):
        key=stage_key(); is_trash=current_tab["value"]=="trash"
        items=registry.list(key,include_deleted=True)
        items=[item for item in items if bool(item.get("deleted"))==is_trash]
        rank={pid:i for i,pid in enumerate(orders[key])};items.sort(key=lambda item:rank.get(item['id'],len(rank)))
        visible["items"]=items
        widget=current_list(); widget.configure(state="normal"); widget.delete(0,"end")
        for item in items:
            selected_ref=next((r for r in chosen[key] if r['id']==item['id']),None)
            mark="✓" if selected_ref and not is_trash else "□"
            state="기본" if item.get('kind')=='builtin' else "사용자"
            label=f"{mark} [{state}] {item['name']}  v{item['version']}"
            if selected_ref and selected_ref['version']!=item['version']:label=f"{mark} [{state}] {item['name']}  적용 v{selected_ref['version']} / 최신 v{item['version']}"
            widget.insert("end",label)
        if preserve_id:
            for i,item in enumerate(items):
                if item['id']==preserve_id:widget.selection_set(i);widget.activate(i);break
        if not items:
            widget.insert("end","(항목 없음)");widget.configure(state="disabled")
        text_box.delete("1.0","end");name.set("");selected_version.set("")
        selected[key]=preserve_id if preserve_id and any(i['id']==preserve_id for i in items) else None
        notebook.tab(active_tab,text=f"프롬프트 ({len(registry.list(key))})")
        notebook.tab(trash_tab,text=f"휴지통 ({sum(1 for item in registry.list(key,True) if item.get('deleted'))})")
        update_controls()

    def update_controls():
        trash=current_tab["value"]=="trash";items=current_items();ids=orders[stage_key()]
        try: indexes=list(current_list().curselection())
        except Exception:indexes=[]
        active_buttons=("disabled" if trash else "normal")
        toggle_btn.configure(state=active_buttons);new_btn.configure(state=active_buttons);save_btn.configure(state=active_buttons);delete_btn.configure(text="복원" if trash else "삭제",state="normal" if indexes else "disabled")
        up_btn.configure(state="normal" if not trash and indexes and min(indexes)>0 else "disabled")
        down_btn.configure(state="normal" if not trash and indexes and max(indexes)<len(items)-1 else "disabled")

    def show_item(_event=None):
        key=stage_key();widget=current_list();indexes=widget.curselection()
        if not indexes:return
        items=current_items();idx=indexes[0]
        if idx>=len(items):return
        item=items[idx];selected[key]=item['id'];name.set(item['name'])
        history=registry.versions(item['id']);versions['values']=[f"v{x['version']}" for x in history]
        ref=next((r for r in chosen[key] if r['id']==item['id']),None)
        version=ref['version'] if ref and current_tab['value']=="active" else item['version']
        selected_version.set(f"v{version}");viewed=next((v for v in history if v['version']==version),item)
        text_box.delete("1.0","end");text_box.insert("1.0",viewed['text']);draft_versions[key][item['id']]=version
        update_controls()

    def choose_version(_event=None):
        key=stage_key();pid=selected.get(key)
        if not pid or not selected_version.get():return
        version=int(selected_version.get()[1:]);item=next(x for x in registry.versions(pid) if x['version']==version)
        text_box.delete("1.0","end");text_box.insert("1.0",item['text']);draft_versions[key][pid]=version
        for ref in chosen[key]:
            if ref['id']==pid:ref['version']=version

    def toggle():
        key=stage_key()
        for idx in current_list().curselection():
            if idx>=len(current_items()):continue
            item=current_items()[idx];pid=item['id']
            ref=next((r for r in chosen[key] if r['id']==pid),None)
            if ref:chosen[key].remove(ref)
            else:chosen[key].append({'id':pid,'version':draft_versions[key].get(pid,item['version'])})
        refresh()

    def reorder(direction):
        key=stage_key();items=current_items();selected_indexes=list(current_list().curselection())
        if not selected_indexes:return
        moved=[items[i]['id'] for i in selected_indexes if i<len(items)]
        order=orders[key];positions=sorted(order.index(pid) for pid in moved if pid in order)
        if len(positions)!=len(moved):return
        if direction<0:
            for pos in positions:
                if pos>0 and order[pos-1] not in moved:order[pos-1],order[pos]=order[pos],order[pos-1]
        else:
            for pos in reversed(positions):
                if pos<len(order)-1 and order[pos+1] not in moved:order[pos],order[pos+1]=order[pos+1],order[pos]
        refresh(preserve_id=moved[0]);w=current_list();w.selection_clear(0,"end")
        for i,item in enumerate(current_items()):
            if item['id'] in moved:w.selection_set(i)
        update_controls()

    def save_version():
        key=stage_key();pid=selected.get(key);body=text_box.get('1.0','end-1c')
        if not body.strip():messagebox.showerror("본문 필요","프롬프트 본문을 입력하세요.");return
        if pid:
            previous=registry.versions(pid)[-1]
            item=registry.add_version(key,name.get() or previous['name'],body,pid,source_section_id=pid if previous.get('kind')=='builtin' else None)
        else:item=registry.add_version(key,name.get(),body)
        ref=next((r for r in chosen[key] if r['id']==item['id']),None)
        if ref:ref['version']=item['version']
        elif not pid:chosen[key].append({'id':item['id'],'version':item['version']})
        if item['id'] not in orders[key]:orders[key].append(item['id'])
        draft_versions[key][item['id']]=item['version'];registry.save()
        selected[key]=item['id'];status.set(f"{item['name']} v{item['version']} 저장됨. 적용 전까지 실행에는 반영되지 않습니다.");refresh(preserve_id=item['id'])

    def add_new():
        key=stage_key();selected[key]=None;name.set("새 지침");selected_version.set("");text_box.delete("1.0","end");current_tab["value"]="active";notebook.select(active_tab);update_controls()

    def delete_or_restore():
        if not current_list().curselection():return
        items=current_items();idx=current_list().curselection()[0]
        if idx>=len(items):return
        item=items[idx];pid=item['id'];key=stage_key()
        try:
            if current_tab['value']=="trash":
                registry.restore(pid)
                if item.get('kind')=='builtin' and not any(r['id']==pid for r in chosen[key]):chosen[key].append({'id':pid,'version':1})
                status.set("휴지통에서 복원했습니다. 적용 전에 선택을 확인하세요.")
            else:
                registry.delete(pid);chosen[key]=[r for r in chosen[key] if r['id']!=pid]
                status.set("구간을 휴지통으로 옮겼습니다.")
            registry.save()
        except OSError as exc:messagebox.showerror("저장 실패",str(exc));return
        refresh()

    def preview():
        key=stage_key();rank={pid:i for i,pid in enumerate(orders[key])}
        refs=sorted(chosen[key],key=lambda r:rank.get(r['id'],len(rank)));by_key={(p['id'],p['version']):p for p in registry.data['prompts']}
        data=[by_key[(r['id'],r['version'])] for r in refs if (r['id'],r['version']) in by_key and not by_key[(r['id'],r['version'])].get('deleted')]
        combined=PromptRegistry.compose(key,"",{key:data});popup=tk.Toplevel(window);popup.title("현재 미적용 변경 포함 미리보기")
        pane=tk.Text(popup,wrap="word",width=110,height=38);pane.pack(fill="both",expand=True);pane.insert("1.0",combined);pane.configure(state="disabled")

    def apply():
        try:registry.apply(chosen,orders);registry.save();outcome['applied']=True
        except (ValueError,OSError) as exc:messagebox.showerror("적용할 수 없습니다",str(exc));return
        window.destroy()

    controls=ttk.Frame(window,padding=8);controls.pack(fill="x")
    toggle_btn=ttk.Button(controls,text="선택 전환",command=toggle);toggle_btn.pack(side="left")
    new_btn=ttk.Button(controls,text="새 구간",command=add_new);new_btn.pack(side="left",padx=3)
    save_btn=ttk.Button(controls,text="부분 수정/새 버전 저장",command=save_version);save_btn.pack(side="left",padx=3)
    delete_btn=ttk.Button(controls,text="삭제",command=delete_or_restore);delete_btn.pack(side="left",padx=3)
    up_btn=ttk.Button(controls,text="위로",command=lambda:reorder(-1));up_btn.pack(side="left",padx=3)
    down_btn=ttk.Button(controls,text="아래로",command=lambda:reorder(1));down_btn.pack(side="left",padx=3)
    ttk.Button(controls,text="선택 조합 미리보기",command=preview).pack(side="left",padx=3)
    ttk.Button(controls,text="적용",command=apply).pack(side="right");ttk.Button(controls,text="취소",command=window.destroy).pack(side="right",padx=4)
    def on_tab_change(_event=None):
        current_tab['value']="trash" if notebook.index("current")==1 else "active";refresh()
    selector.bind("<<ComboboxSelected>>",lambda e:(stage.set(selector.get()),refresh()))
    notebook.bind("<<NotebookTabChanged>>",on_tab_change)
    active_list.bind("<<ListboxSelect>>",show_item);trash_list.bind("<<ListboxSelect>>",show_item);versions.bind("<<ComboboxSelected>>",choose_version)
    active_list.bind("<Double-Button-1>",lambda e:toggle());trash_list.bind("<Double-Button-1>",show_item)
    refresh();window.mainloop();return outcome['applied']


def edit_prompts_console(root=None):
    """Console fallback with tab-equivalent trash filtering and persisted ordering."""
    registry=PromptRegistry(root);chosen={key:registry.active_refs(key) for key in STAGES};orders={key:registry.order_ids(key) for key in STAGES}
    for key,label in STAGES.items():
        tab="active"
        while True:
            items=[item for item in registry.list(key,include_deleted=True) if bool(item.get('deleted'))==(tab=="trash")]
            rank={pid:i for i,pid in enumerate(orders[key])};items.sort(key=lambda item:rank.get(item['id'],len(rank)))
            refs=chosen[key]
            print(f"\n[{label} / {'휴지통' if tab=='trash' else '프롬프트'}]")
            for i,item in enumerate(items,1):
                mark="x" if any(r['id']==item['id'] for r in refs) and tab=="active" else " "
                print(f" {i}. [{mark}] {item['name']} v{item['version']} ({item.get('source','user')})")
            raw=input("번호 선택/해제, u번호 위로, d번호 아래로, a 추가, x번호 삭제, r번호 복원, t 탭 전환, done 적용: ").strip().lower()
            if raw=='done' or not raw:break
            if raw=='t':tab="trash" if tab=="active" else "active";continue
            if raw=='a' and tab=="active":
                title=input("이름: ");body=input("본문: ");item=registry.add_version(key,title,body);chosen[key].append({'id':item['id'],'version':item['version']});orders[key].append(item['id']);continue
            if raw[:1] in ('u','d') and tab=="active":
                try:
                    idx=int(raw[1:])-1;item=items[idx];order=orders[key];pos=order.index(item['id']);target=pos+(-1 if raw[0]=='u' else 1)
                    if 0<=target<len(order):order[pos],order[target]=order[target],order[pos]
                except (ValueError,IndexError):print("이동 번호를 확인하세요.")
                continue
            if raw.startswith('x'):
                try:
                    item=items[int(raw[1:])-1]
                    if tab=="trash":print("휴지통 탭에서는 x번호를 사용할 수 없습니다.")
                    else:registry.delete(item['id']);chosen[key]=[r for r in chosen[key] if r['id']!=item['id']]
                except (ValueError,IndexError):print("삭제 번호를 확인하세요.")
                continue
            if raw.startswith('r') and tab=="trash":
                try:
                    item=items[int(raw[1:])-1];registry.restore(item['id'])
                    if item.get('kind')=='builtin' and not any(r['id']==item['id'] for r in chosen[key]):chosen[key].append({'id':item['id'],'version':1})
                except (ValueError,IndexError):print("복원 번호를 확인하세요.")
                continue
            if raw.isdigit() and tab=="active" and 1<=int(raw)<=len(items):
                item=items[int(raw)-1];ref=next((r for r in chosen[key] if r['id']==item['id']),None)
                if ref:chosen[key].remove(ref)
                else:chosen[key].append({'id':item['id'],'version':item['version']})
            else:print("명령을 확인하세요.")
    try:registry.apply(chosen,orders);registry.save();return True
    except (ValueError,OSError) as exc:print(f"적용 실패: {exc}");return False
