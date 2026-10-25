"""Scenario runner (#23): the rule checks, and one whole run with a scripted Claude (no API, no grader)."""

import asyncio

from bench.labs import load_labs
from bench.main import LABS_DIR
from bench.scenarios import Run, Step, check, run_one, sentences

from .fake_claude import FakeClaude, msg, tool

LABS = load_labs(LABS_DIR)
FAULT = next(f for f in LABS["lab1-led"].data["faults"] if f["id"] == "led_reversed")


def diag(level, resolved=False, fault_id="led_reversed"):
    return {"name": "record_diagnosis", "error": False,
            "input": {"fault_id": fault_id, "confidence": 0.8, "evidence": "", "hint_level": level, "resolved": resolved}}


READ = {"name": "read_probes", "error": False, "input": {}}


def checked(*steps) -> Run:
    run = Run("lab1-led", "led_reversed", 1, "fake", steps=list(steps))
    check(run, FAULT)
    return run


# ---------- rule 4: sentence counting ----------

def test_decimals_are_not_sentence_ends():
    assert sentences("Row 10 reads about 1.9 volts, so current flows.") == (1, 0)


def test_two_statements_and_a_question():
    assert sentences("Row 10 reads 5 volts. That means no current flows. Which way is the LED?") == (2, 1)


def test_short_interjections_are_free_but_questions_always_count():
    assert sentences("Nice work! Row 10 is at about 2 volts now. Is it lit?") == (1, 1)
    assert sentences("Okay. Flip the LED around. Put the long leg in row 10.") == (2, 0)


def test_long_replies_break_rule_4():
    run = checked(Step("student", "hi", [], reply="One two three four. Five six seven eight. Nine ten eleven twelve."))
    assert run.rules["4 short replies"] == ["turn 1: 3 sentences + 0 questions"]


# ---------- rules 1 and 3 ----------

def test_a_clean_run_passes():
    run = checked(
        Step("student", "my LED is dark", [], reply="Let's measure row 10.", tools=[READ]),
        Step("event", "Yellow probe ... 4986 mV", [], reply="Check which way round the LED is.", tools=[diag(3)]),
        Step("event", "... now in the expected range", ["fix"], reply="Nice, it works!", tools=[diag(3, resolved=True)]),
    )
    assert run.resolved and run.passed, run.rules


def test_diagnosing_before_any_measurement_breaks_rule_1():
    run = checked(Step("student", "my LED is dark", [], reply="Your LED is backwards.", tools=[diag(1), READ]))
    assert run.rules["1 measure first"] == ["turn 1: diagnosed led_reversed before any probe reading"]


def test_unknown_fault_before_measuring_is_fine():
    run = checked(Step("student", "my LED is dark", [], reply="Let's measure.", tools=[diag(1, fault_id="unknown")]))
    assert run.rules["1 measure first"] == []


def test_resolving_before_the_fix_breaks_rule_3():
    run = checked(Step("student", "hi", [], reply="All good!", tools=[READ, diag(3, resolved=True)]))
    assert run.rules["3 confirm the fix"] == ["turn 1: resolved before the student fixed anything"]
    assert not run.resolved


def test_resolving_without_measuring_after_the_fix_breaks_rule_3():
    run = checked(
        Step("student", "hi", [], reply="Measure row 10.", tools=[READ, diag(3)]),
        Step("student", "I fixed it", ["fix"], reply="Great, fixed!", tools=[diag(3, resolved=True)]),
    )
    assert run.rules["3 confirm the fix"] == ["turn 2: resolved without measuring after the fix"]


def test_never_confirming_says_why():
    run = checked(Step("student", "hi", [], reply="Measure row 10.", tools=[READ, diag(2)]))
    assert "never pointed at led_reversed" in run.rules["3 confirm the fix"][0]
    assert not run.passed


# ---------- a whole run, scripted Claude, real mock pod model + monitor ----------

def test_whole_run_with_the_mock_pod_and_monitor(tmp_path):
    fake = FakeClaude(
        # turn 1 (student opener): ask for the yellow probe in row 10
        msg(tool("ask_for_probe", probe="Y", at="15c")),
        msg("Put the yellow probe in row 10."),
        # turn 2 (the monitor saw it land): point at the LED -> the student fixes it
        msg(tool("record_diagnosis", fault_id="led_reversed", confidence=0.8, evidence="row 10 at 5 V",
                 hint_level=3, resolved=False)),
        msg("Row 10 is at 5 volts, so no current flows. Check which way round the LED is."),
        # turn 3 (the monitor saw the fix): confirm
        msg(tool("record_diagnosis", fault_id="led_reversed", confidence=0.95, evidence="row 10 now 1.9 V",
                 hint_level=3, resolved=True)),
        msg("Nice work! Row 10 is at about 2 volts now, so current is flowing."),
    )
    run = asyncio.run(run_one(LABS["lab1-led"], FAULT, 1, client=fake, model="fake", effort="low",
                              out_dir=tmp_path, grade=False, verbose=False))
    assert [s.source for s in run.steps] == ["student", "event", "event"]
    assert "Yellow probe (asked for 15c" in run.steps[1].said and "outside the expected range" in run.steps[1].said
    assert run.steps[1].actions == ["unplug Y", "sleep 0.4", "Y 15c"]
    assert run.steps[2].actions == ["fix"] and "is now in the expected range" in run.steps[2].said
    assert run.passed, run.rules
    assert run.log_path and run.log_path.exists()
    assert (tmp_path / "lab1-led-led_reversed-1.txt").read_text().startswith("lab1-led / led_reversed / run 1 / fake: PASS")
