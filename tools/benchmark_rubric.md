# Timeline benchmark annotation rubric

The generated `manifest.jsonl` is a content-free sampling frame. Annotators must
review the referenced STT/chat source window in the local project and fill only
the `labels` object. `🔥` and the other strata are sampling metadata, never a
ground-truth entertainment label.

## Required labels

| Field | Allowed values / format | Rule |
| --- | --- | --- |
| `summary_worthiness` | `0`, `1`, `2` | 0 = routine/no durable event; 1 = useful context or topic transition; 2 = important event a timeline should cover |
| `entertainment_value` | `0`, `1`, `2` | 0 = not entertaining; 1 = mildly notable; 2 = clearly entertaining/reaction-worthy. Judge the event, not chat volume. |
| `acceptable_click_start_seconds` / `end` | integer seconds, or `null` for no event | Smallest interval in which a viewer can understand/usefully reach the event. Include setup when necessary. |
| `evidence_modality` | `stt`, `chat`, `stt+chat`, `unknown` | Evidence that supports the label. Use `unknown` when the source window is insufficient. |
| `confidence` | `low`, `medium`, `high` | Confidence in the labels after reading the available evidence. |
| `duplicate_relation` | `none`, `same_event:<window_id>`, `related_event:<window_id>` | Link repeated/overlapping windows only after comparing their evidence; otherwise `none`. |

`annotator_id` identifies the reviewer. `notes` should contain a short reason or
miss taxonomy (for example `setup-before-apex`, `chat-only`, `routine-topic`),
not copied source text. Labels are independent: a window may be summary-worthy
without being entertaining, or both/neither.

## Calibration and held-out use

The tool assigns whole VODs to `calibration` or `held_out`; no VOD is split
between them. Use calibration rows to reconcile disagreements and freeze the
rubric. Do not inspect held-out labels while tuning rules. The default command
selects up to eight rows per combined stratum in each split; rerunning it with
the same inputs produces byte-identical JSONL.

## Reproducible command

From the project root:

```bash
python tools/benchmark_manifest.py --output-dir .ai/evaluation/benchmark
```

The output directory is separate from `voicepalette/` and `chat_cache/` and can
be deleted/recreated without modifying source caches.

## Local annotation workflow

From the project root, start (or resume) the deterministic calibration-only
terminal reviewer:

```bash
python tools/annotate_benchmark.py annotate
```

The reviewer shows only timestamped lines in the current 60-second window,
bounded to 40 lines and 6,000 characters per source. It never copies full STT
or chat files. Press `q` to stop; already saved rows are skipped on the next
run. Labels are written separately to
`.ai/evaluation/benchmark/annotations.jsonl`, one JSON object per line, bound
to the manifest record by a digest. Writes use a temporary file, `fsync`, and
atomic replacement. The manifest and source caches are read-only.

Validate saved annotations before using them in an evaluation:

```bash
python tools/annotate_benchmark.py validate
```

Validation rejects unknown record identities, digest changes, held-out rows,
invalid rubric enums, unordered or out-of-window click intervals, malformed or
missing duplicate references, and malformed annotator fields. Held-out rows are
never offered by the annotation command and cannot be saved through its normal
path.
