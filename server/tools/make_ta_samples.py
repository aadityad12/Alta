"""Make the TA dashboard's simulated benches (#24) from scenario session logs (#23).

    uv run python tools/make_ta_samples.py ../recordings/scenarios/v2-opus-fast-r3

Keeps one run per fault, and only the status a TA would see: turns (who started them, no words), state,
manual step, probe requests and diagnoses (fault, hint level, confidence, resolved; no evidence text).
No transcript, no audio, no photos. Writes bench/ta_samples/<lab>-<fault>.jsonl.
"""

import json
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "bench" / "ta_samples"
KEEP_INPUT = {
    "record_diagnosis": ("fault_id", "hint_level", "confidence", "resolved"),
    "show_manual_step": ("step",),
    "ask_for_probe": ("probe", "at"),
}


def strip(rec: dict) -> dict | None:
    kind = rec["kind"]
    if kind == "turn":
        return {"t": rec["t"], "kind": "turn", "source": rec.get("source")}
    if kind == "state":
        return {"t": rec["t"], "kind": "state", "value": rec.get("value")}
    if kind == "tool" and rec.get("name") in KEEP_INPUT and not rec.get("error"):
        keep = KEEP_INPUT[rec["name"]]
        return {"t": rec["t"], "kind": "tool", "name": rec["name"],
                "input": {k: v for k, v in (rec.get("input") or {}).items() if k in keep}}
    return None


def main() -> None:
    src = Path(sys.argv[1])
    OUT.mkdir(exist_ok=True)
    for path in sorted(src.glob("*-1.jsonl")):  # run 1 of each fault
        m = re.search(r"-(lab\d-[a-z]+)-(\w+)-1\.jsonl$", path.name)
        if not m:
            continue
        lab, fault = m.groups()
        recs = [r for r in (strip(json.loads(line)) for line in path.open()) if r]
        out = OUT / f"{lab}-{fault}.jsonl"
        with out.open("w") as f:
            f.write(json.dumps({"t": 0.0, "kind": "session", "lab": lab, "fault": fault}) + "\n")
            for r in recs:
                f.write(json.dumps(r) + "\n")
        print(f"{out.name}: {len(recs)} records, {recs[-1]['t'] if recs else 0} s")


if __name__ == "__main__":
    main()
