"""Session metrics (#23) from the JSONL session logs (bench/recorder.py).

    cd server
    uv run python -m bench.metrics ../recordings/*.jsonl

Per session: turns, probes asked for, highest hint level, the fault ALTA diagnosed, time from the
student's first words to the confirmed fix. Then latency over every spoken turn, from button release
to each mark (the #22 target is release -> first audio, median <= 2.5 s).
"""

import argparse
import json
import statistics
import sys
from pathlib import Path

MARKS = ("stt", "first_text", "speaking", "first_sentence", "first_audio")
LABELS = {"stt": "transcript", "first_text": "first Claude text", "speaking": "speaking",
          "first_sentence": "first sentence sent", "first_audio": "first audio"}
END_STATES = ("idle", "listening", "error")


def turn_timing(recs: list[dict]) -> dict[str, float] | None:
    """recs starts at a talk-button release. Seconds from the release to the first of each mark."""
    if not recs or recs[0]["kind"] != "ptt":
        return None
    t0, out = recs[0]["t"], {}
    for r in recs[1:]:
        kind = "speaking" if r["kind"] == "state" and r.get("value") == "speaking" else r["kind"]
        if kind in MARKS and kind not in out:
            out[kind] = round(r["t"] - t0, 3)
    return out


def format_timing(timing: dict[str, float]) -> str:
    return " → ".join(f"{LABELS[k]} {v:.2f} s" for k, v in sorted(timing.items(), key=lambda kv: kv[1]))


def spoken_turns(recs: list[dict]) -> list[dict[str, float]]:
    """The timing of every turn that started with the talk button and got a transcript."""
    out, turn = [], None
    for r in recs:
        if r["kind"] == "ptt":
            turn = [r] if not r.get("down") else None
            continue
        if turn is None:
            continue
        turn.append(r)
        if r["kind"] == "state" and r.get("value") in END_STATES:
            timing = turn_timing(turn)
            if timing and "stt" in timing:
                out.append(timing)
            turn = None
    return out


def load(path: Path) -> list[dict]:
    recs = []
    for line in path.read_text().splitlines():
        try:
            recs.append(json.loads(line))
        except ValueError:
            pass  # a line cut off by a crash
    return recs


def summarize(recs: list[dict]) -> dict:
    head = next((r for r in recs if r["kind"] == "session"), {})
    tools = [r for r in recs if r["kind"] == "tool" and not r.get("error")]
    diags = [r for r in tools if r.get("name") == "record_diagnosis"]
    student = [r for r in recs if r["kind"] == "transcript" and r.get("role") == "student"]
    fixed = next((r for r in diags if r.get("input", {}).get("resolved")), None)
    faults = [d["input"].get("fault_id") for d in diags if d.get("input", {}).get("fault_id") not in (None, "unknown")]
    turns = [r for r in recs if r["kind"] == "turn"]
    return {
        "lab": head.get("lab"),
        "turns": len(turns),
        "events": sum(1 for r in turns if r.get("source") == "event"),
        "probes": sum(1 for r in tools if r.get("name") == "ask_for_probe"),
        "max_hint": max((d["input"].get("hint_level", 0) for d in diags), default=None),
        "fault": faults[-1] if faults else None,
        "fixed_after_s": round(fixed["t"] - student[0]["t"], 1) if fixed and student else None,
        "errors": sum(1 for r in recs if r["kind"] == "state" and r.get("value") == "error"),
        "spoken": spoken_turns(recs),
    }


def _stats(values: list[float]) -> str:
    if not values:
        return "–"
    v = sorted(values)
    p90 = v[min(len(v) - 1, round(0.9 * (len(v) - 1)))]
    return f"{statistics.median(v):.2f} / {p90:.2f} / {v[-1]:.2f}"


def report(paths: list[Path]) -> str:
    rows, spoken = [], []
    for p in paths:
        s = summarize(load(p))
        if not s["turns"]:
            continue
        spoken += s["spoken"]
        audio = [t.get("first_audio", t.get("speaking")) for t in s["spoken"]]
        audio = [a for a in audio if a is not None]
        rows.append([p.stem, s["lab"] or "?", f"{s['turns']} ({s['events']})", str(s["probes"]),
                     str(s["max_hint"] or "–"), s["fault"] or "–",
                     f"{s['fixed_after_s']} s" if s["fixed_after_s"] is not None else "–",
                     f"{statistics.median(audio):.2f} s" if audio else "–", str(s["errors"])])
    if not rows:
        return "No sessions with any turns."
    head = ["session", "lab", "turns (events)", "probes", "max hint", "fault", "fixed after", "median audio", "errors"]
    out = [_table(head, rows), "", f"Latency from button release, {len(spoken)} spoken turns (median / p90 / max, s):"]
    lat = [[LABELS[m], str(sum(1 for t in spoken if m in t)), _stats([t[m] for t in spoken if m in t])] for m in MARKS]
    out.append(_table(["mark", "turns", "median / p90 / max"], lat))
    return "\n".join(out)


def _table(head: list[str], rows: list[list[str]]) -> str:
    widths = [max(len(r[i]) for r in [head, *rows]) for i in range(len(head))]
    line = lambda r: "| " + " | ".join(c.ljust(w) for c, w in zip(r, widths)) + " |"
    return "\n".join([line(head), "|" + "|".join("-" * (w + 2) for w in widths) + "|", *map(line, rows)])


def main() -> None:
    p = argparse.ArgumentParser(prog="bench.metrics", description="Summarize ALTA session logs.")
    p.add_argument("paths", nargs="+", type=Path, help="recordings/*.jsonl")
    args = p.parse_args()
    missing = [x for x in args.paths if not x.is_file()]
    if missing:
        sys.exit(f"not a file: {', '.join(map(str, missing))}")
    print(report(sorted(args.paths)))


if __name__ == "__main__":
    main()
