"""Scenario tests (#23): the real agent against every fault, with a scripted student and the mock pod.

    cd server
    uv run python -m bench.scenarios                       # every fault in every lab, 3 runs each
    uv run python -m bench.scenarios --fault led_reversed --runs 1 -v
    uv run python -m bench.scenarios --model claude-sonnet-5-5   # model comparison (#22)

Each run: the mock pod's voltage model (#9) has the fault staged, and the probe monitor (#21) watches it on a
simulated clock. Claude is real (ANTHROPIC_API_KEY). The scripted student:
- opens with the fault's symptom from lab.yaml
- plugs a probe wherever `ask_for_probe` points (pull it out, then push it in, as a person would)
- covers the light sensor or shines a light on it when Bench says so (Lab 2)
- fixes the fault once Bench points at it: record_diagnosis with the right fault at hint level 3 or 4
- answers a question about what's on the board ("which row is the long leg in?") truthfully, from the fault's
  how_to_stage (a claude-haiku-5-5 call; questions that ask it to reason get a canned line instead)
- otherwise says the next canned line, ending with asking for the answer twice
Between turns the pod runs SETTLE_S of simulated time. If the monitor reports something, that's the next
turn, exactly as the server would deliver it.

Rules checked on every run:
  1. measure first: no fault named (record_diagnosis, or in words) before a probe reading
  2. no fix early: no reply gives the fix while the hint level is below 3 (graded by claude-haiku-5-5)
  3. confirm the fix: resolved=true only after the student fixed it, and after a new measurement
  4. short replies: at most 2 sentences plus at most 1 question (3-word interjections like "Nice work!" are free)
A run passes if all four hold, the fix was confirmed, and no turn failed. A scenario passes if at least 2 of
3 runs pass. Logs and transcripts go to recordings/scenarios/<time>/ (`bench.metrics` reads the logs).
"""

import argparse
import asyncio
import importlib.util
import json
import logging
import os
import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import bus as ev
from .agent import GLITCH_LINE, SILENT, Agent
from .hub import Bench
from .labs import load_labs
from .main import LABS_DIR
from .metrics import _table
from .monitor import Monitor
from .protocol import PROBES
from .recorder import RECORD_DIR, Recorder

log = logging.getLogger(__name__)

_spec = importlib.util.spec_from_file_location("mock_pod", Path(__file__).resolve().parents[1] / "tools" / "mock_pod.py")
mock_pod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mock_pod)
mock_pod.say = lambda msg: None  # the mock narrates every command; not here

GRADER_MODEL = "claude-haiku-5-5"
SETTLE_S = 2.0      # simulated seconds after the student does something, for the monitor to react
UNPLUG_S = 0.4      # a probe is out of the board this long while the student moves it
MAX_TURNS = 14
INTERJECTION_WORDS = 3  # rule 4 ignores "sentences" this short
MAX_ANSWERS = 4     # questions about the board the student answers in a run (the rest get a canned line)
NAMES = {"Y": "yellow", "B": "blue", "G": "green", "W": "white"}

STUCK_LINES = [
    "Hmm, I'm not sure what to look for.",
    "I still don't see what's wrong.",
    "Can you just tell me what's wrong?",
    "Please, just tell me the answer.",
    "I really don't get it. What do I change?",
]
AFTER_FIX_LINES = ["Okay, I think I fixed it. Can you check?", "Did that work?", "Is it right now?"]
_UNCOVER = re.compile(r"\b(uncover|take your (hand|finger)|move your (hand|finger)|let the light)\b", re.I)
_COVER = re.compile(r"\bcover", re.I)
_SHINE = re.compile(r"\b(flashlight|shine|phone'?s? light|torch)\b", re.I)


# ---------- one run ----------

@dataclass
class Step:
    """One agent turn and what led to it."""
    source: str                     # "student" or "event"
    said: str                       # the student's words, or the monitor's event text
    actions: list[str]              # what the student did on the board just before (mock pod commands)
    reply: str | None = None        # what Bench said (None = silent)
    tools: list[dict[str, Any]] = field(default_factory=list)
    ms: int = 0                     # the whole turn, wall clock
    first_text_ms: int | None = None  # turn start -> Claude's first text
    level: int = 0                  # highest hint level recorded so far, this turn included (for the grader)
    measured: bool = False          # a probe reading had come in before this reply


@dataclass
class Run:
    lab: str
    fault: str
    n: int
    model: str
    steps: list[Step] = field(default_factory=list)
    log_path: Path | None = None
    crashed: str | None = None
    rules: dict[str, list[str]] = field(default_factory=dict)  # rule -> what broke it (empty = held)
    resolved: bool = False
    grades: list[dict] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.crashed is None and self.resolved and not any(self.rules.values())


class Student:
    """The scripted student, plus the board (the mock pod's model; the monitor runs on `t`)."""

    def __init__(self, lab: dict, fault: dict, rng_seed: int, client=None) -> None:
        self.lab, self.fault, self.client = lab, fault, client
        self.pod = mock_pod.MockPod(LABS_DIR, None, rng_seed)
        os.close(self.pod.master)
        os.close(self.pod.slave)
        self.pod.load_lab(lab["id"], fault["id"])
        self.t = 0.0
        self.fixed = False
        self.stuck = 0
        self.after_fix = 0
        self.answered = 0

    def opener(self) -> str:
        symptom = self.fault["symptom"].strip()
        if not symptom[1:2].isupper():  # "LED stays dark" keeps its capitals
            symptom = symptom[0].lower() + symptom[1:]
        return f"Hi! I built the circuit from the manual, but {symptom}"

    def act(self, step: Step) -> list[str]:
        """Do what Bench just asked on the board. Returns the mock pod commands, in order."""
        cmds = []
        diags = [t["input"] for t in step.tools if t["name"] == "record_diagnosis" and not t["error"]]
        if not self.fixed and any(d.get("fault_id") == self.fault["id"] and d.get("hint_level", 0) >= 3 for d in diags):
            cmds.append("fix")
            self.fixed = True
        for t in step.tools:
            if t["name"] == "ask_for_probe" and not t["error"]:
                p, at = t["input"]["probe"], t["input"]["at"]
                cmds += [f"unplug {p}", f"sleep {UNPLUG_S}", f"{p} {at}"]
        reply = step.reply or ""
        if _UNCOVER.search(reply):
            cmds.append("light 0.5")
        elif _COVER.search(reply):
            cmds.append("light 0")
        elif _SHINE.search(reply):
            cmds.append("light 1")
        return cmds

    async def answer(self, question: str) -> str | None:
        """Answer a question about what's on the board, from what the student can see. None = can't by looking."""
        if self.fixed:
            board = "Your board now matches the manual exactly, and the circuit works."
        else:
            board = (f"Your board matches the manual except for this, which you don't know is a mistake: "
                     f"{self.fault['how_to_stage']} What you notice: {self.fault['symptom']}")
        readings = ", ".join(f"{NAMES[p]} probe in {h}: {self.pod.reading(p, mock_pod.VCC_MV)[0] / 1000:.2f} V"
                             for p, h in self.pod.probes.items() if h) or "no probes plugged in"
        parts = json.dumps(self.lab.get("parts", []), ensure_ascii=False)
        prompt = (
            f"You are a student in an intro electronics lab ({self.lab.get('title')}), talking to your TA. The "
            f"manual's parts and holes: {parts}\n{board}\nYour screen shows: {readings}.\n\n"
            f"The TA just said: \"{question}\"\n\n"
            "If the TA asked about something you can see or check on your board or screen (which leg is longer, which "
            "row a leg or wire is in, the resistor's color bands, whether the LED is lit, what a probe reads), answer "
            "in one short, casual sentence, truthfully, the way a beginner would. Don't guess at the cause and don't "
            "mention the manual's hole names unless asked. If the question asks you to reason, explain or diagnose "
            "rather than look, reply with exactly PASS."
        )
        resp = await self.client.messages.create(
            model=GRADER_MODEL, max_tokens=1000, messages=[{"role": "user", "content": prompt}],
            output_config={"effort": "low"},
        )
        text = " ".join(b.text for b in resp.content if b.type == "text").strip()
        return None if not text or text.upper().startswith("PASS") else text

    async def say_next(self, step: Step, did: list[str]) -> str | None:
        """What the student says when the monitor had nothing to report. None = out of lines."""
        reply = step.reply or ""
        if "fix" in did:
            return AFTER_FIX_LINES[0]
        plugged = [c for c in did if c.split()[0] in PROBES]
        if plugged:
            p, at = plugged[-1].split()
            row = re.match(r"\d+", at)
            return f"Okay, the {NAMES[p]} probe is in {'row ' + row.group() if row else at}."
        if any(c.startswith("light") for c in did):
            return {"light 0": "Okay, I'm covering it.", "light 1": "Okay, I'm shining my phone light on it.",
                    "light 0.5": "Okay, I took my hand away."}[did[-1]]
        if "?" in reply and self.client and self.answered < MAX_ANSWERS:
            line = await self.answer(reply)
            if line:
                self.answered += 1
                return line
        if self.fixed:
            self.after_fix += 1
            return AFTER_FIX_LINES[self.after_fix] if self.after_fix < len(AFTER_FIX_LINES) else None
        line = STUCK_LINES[self.stuck] if self.stuck < len(STUCK_LINES) else None
        self.stuck += 1
        return line


async def run_one(lab, fault: dict, n: int, *, client, model: str, effort: str, out_dir: Path, grade: bool,
                  verbose: bool) -> Run:
    run = Run(lab.id, fault["id"], n, model)
    bench = Bench({lab.id: lab})
    bench.session.lab_id = lab.id

    async def quiet(msg):
        pass

    bench.hub.broadcast = bench.session.broadcast = quiet
    recorder = Recorder(out_dir)
    marks: list[tuple[float, str]] = []

    def record(kind, **fields):
        recorder(kind, **fields)
        marks.append((time.monotonic(), kind))

    bench.session.record = record
    recorder.start(f"{lab.id}-{fault['id']}-{n}")
    student = Student(lab.data, fault, rng_seed=n, client=client if grade else None)
    monitor = Monitor(bench, clock=lambda: student.t)
    events = bench.bus.subscribe()
    agent = Agent(bench, client=client, model=model, effort=effort, pod_connected=lambda: True)
    step: Step | None = None

    def on_tool(name, args, result, is_error):
        step.tools.append({"name": name, "input": args, "error": is_error,
                           "result": result if isinstance(result, str) else "(image)"})

    agent.on_tool_call = on_tool

    def settle(seconds: float, cmds: list[str] = ()) -> str | None:
        """Run the board: commands (with `sleep`s) then `seconds` more. Returns the monitor's news, if any."""
        def tick(dt):
            for _ in range(round(dt / mock_pod.TICK_S)):
                student.t += mock_pod.TICK_S
                r = [student.pod.reading(p, mock_pod.VCC_MV) for p in PROBES]
                sample = {"mv": [x[0] for x in r], "lo": [x[1] for x in r], "hi": [x[2] for x in r],
                          "vcc": mock_pod.VCC_MV, "btn": 0}
                bench.session.probes, bench.session.probes_at = sample, time.monotonic()
                monitor.on_sample(sample)
        for c in cmds:
            if c.startswith("sleep "):
                tick(float(c.split()[1]))
            else:
                student.pod.command(c)
        tick(seconds)
        news = []
        while not events.empty():
            e = events.get_nowait()
            if e.kind == ev.MONITOR:
                news.append(str(e.data))
        return " ".join(news) or None

    try:
        settle(1.0)  # the board has been sitting there with the probes in
        source, said, did = "student", student.opener(), []
        for _ in range(MAX_TURNS):
            step = Step(source, said, did)
            run.steps.append(step)
            t0 = time.monotonic()
            del marks[:]
            if source == "student":
                await bench.session.say("student", said)
                step.reply = await agent.turn(said)
            else:
                step.reply = await agent.turn(event=said)
            step.ms = round((time.monotonic() - t0) * 1000)
            first = next((t for t, k in marks if k == "first_text"), None)
            step.first_text_ms = round((first - t0) * 1000) if first else None
            if verbose:
                print(_step_text(run, step), file=sys.stderr)
            if step.reply == GLITCH_LINE:
                run.crashed = "a turn failed (API error or timeout)"
                break
            if any(t["name"] == "record_diagnosis" and t["input"].get("resolved") and not t["error"]
                   for t in step.tools) and student.fixed:
                break
            did = student.act(step)
            news = settle(SETTLE_S, did)
            if news:
                source, said = "event", news
                continue
            line = await student.say_next(step, did)
            if line is None:
                break
            source, said = "student", line
    except Exception as e:
        log.exception("scenario %s/%s #%d crashed", lab.id, fault["id"], n)
        run.crashed = f"{type(e).__name__}: {e}"
    finally:
        run.log_path = recorder.path
        recorder.close()

    check(run, fault)
    if grade and run.steps:
        try:
            await grade_run(run, lab.data, fault, client)
        except Exception as e:
            log.warning("grader failed: %r", e)
            run.rules.setdefault("2 no fix early", []).append(f"grader failed: {type(e).__name__}")
    (out_dir / f"{lab.id}-{fault['id']}-{n}.txt").write_text(transcript(run))
    return run


# ---------- the rules ----------

RULES = ("1 measure first", "2 no fix early", "3 confirm the fix", "4 short replies")


def sentences(text: str) -> tuple[int, int]:
    """(statements, questions) in a reply. "1.9 volts" isn't a sentence end: one needs a space after it.
    Short acknowledgements ("Okay.", "Nice work!", "That's fine.") don't count: they're interjections."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p.strip()]
    questions = sum(1 for p in parts if p.endswith("?"))
    statements = sum(1 for p in parts if not p.endswith("?") and len(p.split()) > INTERJECTION_WORDS)
    return statements, questions


def check(run: Run, fault: dict) -> None:
    """Rules 1, 3 and 4 from the tool calls and the text. Rule 2 needs the grader (grade_run)."""
    rules = {r: [] for r in RULES}
    measured = fixed = measured_since_fix = False
    level = 0
    for i, s in enumerate(run.steps, 1):
        if "fix" in s.actions:
            fixed, measured_since_fix = True, False
        if s.source == "event":
            measured = True
            measured_since_fix = measured_since_fix or fixed
        for t in s.tools:
            if t["error"]:
                continue
            if t["name"] == "read_probes":
                measured = True
                measured_since_fix = measured_since_fix or fixed
            elif t["name"] == "record_diagnosis":
                d = t["input"]
                if d.get("fault_id") not in (None, "unknown") and not measured:
                    rules["1 measure first"].append(f"turn {i}: diagnosed {d['fault_id']} before any probe reading")
                level = max(level, d.get("hint_level") or 0)
                if d.get("resolved"):
                    if not fixed:
                        rules["3 confirm the fix"].append(f"turn {i}: resolved before the student fixed anything")
                    elif not measured_since_fix:
                        rules["3 confirm the fix"].append(f"turn {i}: resolved without measuring after the fix")
                    else:
                        run.resolved = True
        s.level, s.measured = level, measured
        if s.reply and s.reply.strip() != SILENT:
            stmts, qs = sentences(s.reply)
            if stmts > 2 or qs > 1:
                rules["4 short replies"].append(f"turn {i}: {stmts} sentences + {qs} questions")
    if not run.resolved and not rules["3 confirm the fix"]:
        why = "the student fixed it, but Bench never confirmed it" if fixed else \
            f"Bench never pointed at {fault['id']} (hint ≥ 3), so the student never fixed it"
        rules["3 confirm the fix"].append(why)
    run.rules = rules


_GRADE_SCHEMA = {
    "type": "object",
    "properties": {"replies": {"type": "array", "items": {
        "type": "object",
        "properties": {"n": {"type": "integer"}, "names_fault": {"type": "boolean"},
                       "gives_fix": {"type": "boolean"}, "why": {"type": "string"}},
        "required": ["n", "names_fault", "gives_fix", "why"], "additionalProperties": False,
    }}},
    "required": ["replies"], "additionalProperties": False,
}


async def grade_run(run: Run, lab: dict, fault: dict, client) -> None:
    """Rule 2 (and the wording half of rule 1): a small claude-haiku-5-5 call over every reply in the run."""
    replies = [(i, s) for i, s in enumerate(run.steps, 1) if s.reply and s.reply.strip() != SILENT]
    if not replies:
        return
    fix_hint = next((h for h in fault.get("hints", []) if h.startswith("L4")), "")
    numbered = "\n".join(f"{i}. {s.reply}" for i, s in replies)
    prompt = (
        f"A lab TA is helping a student debug a breadboard circuit ({lab.get('title')}). The actual fault is:\n"
        f"{fault['name']}: {fault['root_cause']}\nThe fix: {fix_hint.removeprefix('L4 fix:').strip()}\n\n"
        "For each numbered TA reply below, decide:\n"
        "- names_fault: does the reply state the specific fault as a conclusion (e.g. \"your LED is in backwards\", "
        "\"that's the wrong resistor\")? Asking the student to check something, or naming a general area to look at, "
        "is not naming the fault.\n"
        "- gives_fix: does the reply tell the student what exactly to change to fix it (e.g. \"flip the LED around\", "
        "\"swap in the 220 ohm resistor\")? Pointing at where to look, or asking a question, is not giving the fix. "
        "Telling the student where to put a probe to take a measurement is not giving the fix either, unless the "
        "reply says the probe's position is what's wrong.\n"
        "Judge each reply on its own words. Give a few words of why.\n\n" + numbered
    )
    resp = await client.messages.create(
        model=GRADER_MODEL, max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": _GRADE_SCHEMA}},
    )
    data = json.loads(next(b.text for b in resp.content if b.type == "text"))
    by_n = {r["n"]: r for r in data["replies"]}
    for i, s in replies:
        g = by_n.get(i)
        if g is None:
            continue
        run.grades.append({"turn": i, **g})
        if g["gives_fix"] and s.level < 3:
            run.rules["2 no fix early"].append(f"turn {i}: gave the fix at hint level {s.level or 'none'} ({g['why']})")
        if g["names_fault"] and not s.measured:
            run.rules["1 measure first"].append(f"turn {i}: named the fault before any probe reading ({g['why']})")


# ---------- output ----------

def _step_text(run: Run, s: Step) -> str:
    i = run.steps.index(s) + 1
    lines = [f"--- turn {i} ({s.ms} ms, first text {s.first_text_ms} ms)"]
    if s.actions:
        lines.append(f"    [board] {', '.join(c for c in s.actions if not c.startswith('sleep'))}")
    lines.append(f"{'student' if s.source == 'student' else '[event]'}> {s.said}")
    for t in s.tools:
        mark = "✗" if t["error"] else "·"
        lines.append(f"  {mark} {t['name']} {json.dumps(t['input'], ensure_ascii=False)}")
        if t["error"] or t["name"] == "read_probes":
            lines.append(f"      → {t['result'][:240]}")
    lines.append(f"bench> {s.reply if s.reply is not None else '<silent>'}")
    return "\n".join(lines)


def transcript(run: Run) -> str:
    head = f"{run.lab} / {run.fault} / run {run.n} / {run.model}: {'PASS' if run.passed else 'FAIL'}"
    body = [_step_text(run, s) for s in run.steps]
    broken = [f"  rule {r}: {why}" for r, whys in run.rules.items() for why in whys]
    if run.crashed:
        broken.insert(0, f"  crashed: {run.crashed}")
    grades = [f"  turn {g['turn']}: names_fault={g['names_fault']} gives_fix={g['gives_fix']} ({g['why']})"
              for g in run.grades]
    return "\n".join([head, *body, "", "broken:", *(broken or ["  nothing"]), "", "grader:", *grades]) + "\n"


def summary(runs: list[Run]) -> tuple[str, bool]:
    by: dict[tuple[str, str], list[Run]] = {}
    for r in runs:
        by.setdefault((r.lab, r.fault), []).append(r)
    rows, ok = [], True
    for (lab, fault), rs in by.items():
        passed = sum(r.passed for r in rs)
        need = min(2, len(rs))
        ok &= passed >= need
        cells = [f"{sum(not r.rules[rule] for r in rs)}/{len(rs)}" for rule in RULES]
        turns = statistics.median(len(r.steps) for r in rs)
        rows.append([lab, fault, f"{passed}/{len(rs)} {'✓' if passed >= need else '✗'}", *cells,
                     f"{sum(r.resolved for r in rs)}/{len(rs)}", f"{turns:g}"])
    table = _table(["lab", "fault", "pass", *RULES, "fix confirmed", "turns"], rows)
    steps = [s for r in runs for s in r.steps]
    first = [s.first_text_ms / 1000 for s in steps if s.first_text_ms is not None]
    whole = [s.ms / 1000 for s in steps if s.reply and s.reply.strip() != SILENT]
    lat = (f"\n\nTurn latency over {len(steps)} turns (median / p90, s): start → first Claude text "
           f"{_med_p90(first)} · whole turn (all tool rounds) {_med_p90(whole)}")
    return table + lat, ok


def _med_p90(v: list[float]) -> str:
    if not v:
        return "–"
    v = sorted(v)
    return f"{statistics.median(v):.2f} / {v[min(len(v) - 1, round(0.9 * (len(v) - 1)))]:.2f}"


# ---------- main ----------

async def run_all(args) -> int:
    import anthropic

    labs = load_labs(LABS_DIR)
    jobs = []
    for lab_id in ([args.lab] if args.lab else sorted(labs)):
        lab = labs[lab_id]
        for fault in lab.data.get("faults", []):
            if args.fault and fault["id"] not in args.fault:
                continue
            jobs += [(lab, fault, n) for n in range(1, args.runs + 1)]
    if not jobs:
        print("no scenarios match")
        return 2
    out_dir = args.out or RECORD_DIR / "scenarios" / time.strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    client = anthropic.AsyncAnthropic(max_retries=2)
    model = args.model or os.environ.get("BENCH_MODEL") or "claude-opus-5-5"
    print(f"{len(jobs)} runs · model {model} (effort {args.effort}) · grader + student {GRADER_MODEL if args.grade else 'off'}"
          f" · logs in {out_dir}", file=sys.stderr)
    sem = asyncio.Semaphore(args.concurrency)

    async def one(lab, fault, n):
        async with sem:
            r = await run_one(lab, fault, n, client=client, model=model, effort=args.effort, out_dir=out_dir,
                              grade=args.grade, verbose=args.verbose)
            print(f"  {r.lab}/{r.fault} #{r.n}: {'pass' if r.passed else 'FAIL'} in {len(r.steps)} turns", file=sys.stderr)
            return r

    runs = await asyncio.gather(*(one(*j) for j in jobs))
    table, ok = summary(runs)
    print(table)
    failed = [r for r in runs if not r.passed]
    if failed:
        print("\nWhat broke:")
        for r in failed:
            whys = ([f"crashed: {r.crashed}"] if r.crashed else []) + [w for ws in r.rules.values() for w in ws]
            print(f"  {r.lab}/{r.fault} #{r.n}: " + "; ".join(whys))
    (out_dir / "summary.md").write_text(f"model {model}, effort {args.effort}\n\n{table}\n")
    (out_dir / "runs.json").write_text(json.dumps([{
        "lab": r.lab, "fault": r.fault, "n": r.n, "model": r.model, "passed": r.passed, "resolved": r.resolved,
        "crashed": r.crashed, "rules": r.rules, "turns": len(r.steps), "log": str(r.log_path),
        "steps": [{"source": s.source, "said": s.said, "reply": s.reply, "ms": s.ms, "first_text_ms": s.first_text_ms,
                   "tools": [{k: t[k] for k in ("name", "input", "error")} for t in s.tools]} for s in r.steps],
    } for r in runs], indent=1, ensure_ascii=False))
    return 0 if ok else 1


def main() -> None:
    p = argparse.ArgumentParser(prog="bench.scenarios", description="Run the agent against every lab fault.")
    p.add_argument("--lab", default=None, help="only this lab")
    p.add_argument("--fault", action="append", help="only this fault (repeatable)")
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--model", default=None, help="default: BENCH_MODEL or claude-opus-5-5")
    p.add_argument("--effort", default="low")
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--no-haiku", dest="grade", action="store_false",
                   help="no claude-haiku-5-5 calls: skip the rule-2 grader, and the student only says canned lines")
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("-v", "--verbose", action="store_true", help="print every turn as it happens")
    args = p.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    sys.exit(asyncio.run(run_all(args)))


if __name__ == "__main__":
    main()
