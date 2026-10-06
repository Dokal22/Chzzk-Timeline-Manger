"""Compare two opt-in prompt_research JSON run files."""
import json
import sys


def load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def compare(left_path, right_path):
    left, right = load(left_path), load(right_path)
    right_by_key = {(row["stage"], row["input_sha256"]): row for row in right}
    pairs = []
    for row in left:
        other = right_by_key.get((row["stage"], row["input_sha256"]))
        if other:
            pairs.append((row, other))
    print(f"Matched identical stage/input records: {len(pairs)}")
    if not pairs:
        print("No same-input comparison is possible; no quality conclusion.")
        return 2
    for a, b in pairs:
        print(f"\nStage: {a['stage']} | input sha256: {a['input_sha256']}")
        print(f"Requested models: {a.get('model_requested') or 'unknown'} / {b.get('model_requested') or 'unknown'}")
        print(f"Prompt hashes differ: {a.get('prompt_sha256') != b.get('prompt_sha256')}")
        if a.get("model_requested") != b.get("model_requested"):
            print("WARNING: requested model settings differ; this pair does not isolate prompt changes.")
        if a.get("prompt_sha256") == b.get("prompt_sha256"):
            print("WARNING: prompts are identical; this pair does not compare prompt variants.")
        print(f"Output chars: {len(str(a.get('processed_output', '')))} / {len(str(b.get('processed_output', '')))}")
        print("Semantic quality is not measured by this structural comparison.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python src/code/compare_prompt_runs.py <run-A.json> <run-B.json>")
    raise SystemExit(compare(sys.argv[1], sys.argv[2]))
