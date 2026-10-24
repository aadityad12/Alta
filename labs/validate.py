# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Check every labs/<lab_id>/lab.yaml and its scenarios/ against the #2 contract.

    uv run labs/validate.py            # all labs
    uv run labs/validate.py lab1-led   # one lab

Beyond "it parses", this rebuilds the circuit's connectivity from the parts (wires
join the strips/rails they touch) and checks the nets agree with it. That catches
a part placed in the wrong row before it reaches the mock pod, manuals or boards.
Exits 1 on any error.
"""

import re
import sys
from pathlib import Path

import yaml

LABS_DIR = Path(__file__).resolve().parent
PROBES = ("Y", "B", "G", "W")
RAILS = {"rail:a+", "rail:a-", "rail:j+", "rail:j-"}
HOLE_RE = re.compile(r"^([1-9]|[1-5][0-9]|6[0-3])([a-j])$")
STRIP_RE = re.compile(r"^([1-9]|[1-5][0-9]|6[0-3]):(a-e|f-j)$")
HINT_PREFIXES = ("L1 nudge:", "L2 question:", "L3 point:", "L4 fix:")
LIGHT_MODEL_TOL_MV = 150  # the mock's room-light value must match lab.yaml this closely
LAB_KEYS = {"id", "title", "supply_mv", "parts", "nets", "steps", "faults", "verified"}


def node_of(s: str) -> str | None:
    """Map a hole, strip or rail string to its electrical node (strip or rail)."""
    if s in RAILS:
        return s
    if m := HOLE_RE.match(s):
        row, col = m.groups()
        return f"{row}:{'a-e' if col <= 'e' else 'f-j'}"
    if STRIP_RE.match(s):
        return s
    return None


class Groups:
    """Union-find over nodes."""

    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str):
        self.parent[self.find(a)] = self.find(b)


def check_lab(lab_dir: Path) -> list[str]:
    errs: list[str] = []
    err = errs.append

    try:
        lab = yaml.safe_load((lab_dir / "lab.yaml").read_text())
    except Exception as e:  # noqa: BLE001
        return [f"lab.yaml does not load: {e}"]

    if missing := LAB_KEYS - lab.keys():
        err(f"missing keys: {sorted(missing)}")
        return errs
    if lab["id"] != lab_dir.name:
        err(f"id {lab['id']!r} != folder name {lab_dir.name!r}")
    if not isinstance(lab["verified"], bool):
        err("verified must be true/false")
    if not isinstance(lab["supply_mv"], int):
        err("supply_mv must be an integer")

    # Parts: valid pins, no two pins in the same hole, wires join nodes.
    groups = Groups()
    used_holes: dict[str, str] = {}
    part_nodes: set[str] = set()
    refs = [p.get("ref") for p in lab["parts"]]
    if len(refs) != len(set(refs)):
        err(f"duplicate part refs: {refs}")
    for p in lab["parts"]:
        pins = p.get("pins") or {}
        if not p.get("kind") or not pins:
            err(f"{p.get('ref')}: needs kind and pins")
            continue
        nodes = []
        for pin, at in pins.items():
            n = node_of(at)
            if n is None or STRIP_RE.match(at):
                err(f"{p['ref']}.{pin}: {at!r} is not a hole or rail")
                continue
            if at not in RAILS:
                if at in used_holes:
                    err(f"{p['ref']}.{pin} and {used_holes[at]} both in hole {at}")
                used_holes[at] = f"{p['ref']}.{pin}"
            nodes.append(n)
            part_nodes.add(n)
        if p["kind"] == "wire" and len(nodes) == 2:
            groups.union(*nodes)
        if len(set(nodes)) < len(nodes) and p["kind"] != "wire":
            err(f"{p['ref']}: two pins on the same strip, so it's shorted out")

    # Nets: valid holes, no overlap, internally connected, covers every part pin.
    nets = {n["id"]: n for n in lab["nets"]}
    if len(nets) != len(lab["nets"]):
        err("duplicate net ids")
    node_net: dict[str, str] = {}
    for net in lab["nets"]:
        for k in ("id", "label", "holes", "expected_mv", "tol_mv"):
            if k not in net:
                err(f"net {net.get('id')}: missing {k}")
        if not all(isinstance(net.get(k), int) for k in ("expected_mv", "tol_mv")):
            err(f"net {net.get('id')}: expected_mv/tol_mv must be integers")
        roots = set()
        for h in net.get("holes", []):
            n = node_of(h)
            if n is None:
                err(f"net {net['id']}: bad hole {h!r}")
                continue
            if n in node_net and node_net[n] != net["id"]:
                err(f"{h} is in both {node_net[n]} and {net['id']}")
            node_net[n] = net["id"]
            roots.add(groups.find(n))
        if len(roots) > 1:
            err(f"net {net['id']}: its holes aren't wired together: {net['holes']}")
    for n in sorted(part_nodes - node_net.keys()):
        err(f"{n} has a part pin but isn't in any net")
    # Nets that are wired together (split only for fault modelling) must agree.
    by_root: dict[str, list[dict]] = {}
    for net in lab["nets"]:
        if net.get("holes") and (n := node_of(net["holes"][0])):
            by_root.setdefault(groups.find(n), []).append(net)
    for same in by_root.values():
        mvs = [n["expected_mv"] for n in same]
        if max(mvs) - min(mvs) > min(n["tol_mv"] for n in same):
            err(f"nets {[n['id'] for n in same]} are wired together but expect {mvs}")

    # Steps.
    ns = [s.get("n") for s in lab["steps"]]
    if ns != list(range(1, len(ns) + 1)):
        err(f"steps must be numbered 1..N, got {ns}")
    for s in lab["steps"]:
        if not s.get("title"):
            err(f"step {s.get('n')}: missing title")
        for nid in s.get("nets", []):
            if nid not in nets:
                err(f"step {s['n']}: unknown net {nid}")

    # Faults.
    faults = {f["id"]: f for f in lab["faults"]}
    if len(faults) != len(lab["faults"]):
        err("duplicate fault ids")
    for f in lab["faults"]:
        fid = f.get("id")
        for k in ("name", "how_to_stage", "symptom", "readings", "root_cause", "hints"):
            if not f.get(k):
                err(f"fault {fid}: missing {k}")
        r = f.get("readings") or {}
        if set(r) != set(nets):
            err(f"fault {fid}: readings must cover every net exactly, got {sorted(r)}")
        if not all(isinstance(v, int) for v in r.values()):
            err(f"fault {fid}: readings must be integers (mV)")
        hints = f.get("hints") or []
        if len(hints) != 4 or not all(h.startswith(p) for h, p in zip(hints, HINT_PREFIXES)):
            err(f"fault {fid}: needs exactly 4 hints, prefixed {HINT_PREFIXES}")

    # Scenarios: one per fault plus normal.yaml, all consistent with the lab.
    scen_dir = lab_dir / "scenarios"
    expected_files = {"normal"} | set(faults)
    found = {p.stem for p in scen_dir.glob("*.yaml")}
    if missing := expected_files - found:
        err(f"missing scenarios: {sorted(missing)}")
    for path in sorted(scen_dir.glob("*.yaml")):
        errs += [f"scenarios/{path.name}: {e}" for e in check_scenario(path, lab, nets, faults, node_net)]

    return errs


def light_mv(model: dict, supply_mv: int, light: float) -> int:
    """Mock-pod photoresistor model. light: 0 = covered, 0.5 = room, 1 = flashlight.
    Sensor resistance is interpolated on a log scale between those three points."""
    r = model["sensor_ohm"]
    lo, hi, t = (r["dark"], r["room"], light * 2) if light <= 0.5 else (r["room"], r["bright"], light * 2 - 1)
    sensor = lo * (hi / lo) ** t
    fixed = model["fixed_ohm"]
    bottom, top = (fixed, sensor) if model["sensor_on"] == "top" else (sensor, fixed)
    return round(supply_mv * bottom / (bottom + top))


def check_scenario(path: Path, lab: dict, nets: dict, faults: dict, node_net: dict) -> list[str]:
    errs: list[str] = []
    err = errs.append
    try:
        s = yaml.safe_load(path.read_text())
    except Exception as e:  # noqa: BLE001
        return [f"does not load: {e}"]
    if s.get("lab") != lab["id"]:
        err(f"lab {s.get('lab')!r} != {lab['id']!r}")
    fid = s.get("fault")
    if fid is not None and fid not in faults:
        err(f"unknown fault {fid!r}")
    if path.stem != (fid or "normal"):
        err(f"file name should be {(fid or 'normal')}.yaml")
    for nid, o in (s.get("nets") or {}).items():
        if nid not in nets:
            err(f"nets: unknown net {nid}")
        if set(o) - {"mv", "noise_mv"}:
            err(f"nets.{nid}: only mv / noise_mv allowed")
    for h, o in (s.get("holes") or {}).items():
        n = node_of(h)
        if n is None:
            err(f"holes: bad hole {h!r}")
        elif n in node_net:
            err(f"holes: {h} is in net {node_net[n]}; override it under nets: instead")
        if "mv" not in o:
            err(f"holes.{h}: needs mv")
    for probe, at in (s.get("probes") or {}).items():
        if probe not in PROBES:
            err(f"probes: unknown probe {probe!r}")
        if node_of(at) is None:
            err(f"probes.{probe}: bad hole {at!r}")
    if m := s.get("light_model"):
        if m.get("net") not in nets:
            err(f"light_model: unknown net {m.get('net')}")
        else:
            want = faults[fid]["readings"][m["net"]] if fid in faults else nets[m["net"]]["expected_mv"]
            room = light_mv(m, lab["supply_mv"], 0.5)
            if abs(room - want) > LIGHT_MODEL_TOL_MV:
                err(f"light_model gives {room} mV in room light, lab.yaml says {want}")
    return errs


def main(argv: list[str]) -> int:
    dirs = [LABS_DIR / a for a in argv] if argv else sorted(p.parent for p in LABS_DIR.glob("*/lab.yaml"))
    bad = 0
    for d in dirs:
        errs = check_lab(d) if (d / "lab.yaml").exists() else [f"no lab.yaml in {d}"]
        if errs:
            bad += 1
            print(f"✗ {d.name}")
            for e in errs:
                print(f"    {e}")
        else:
            lab = yaml.safe_load((d / "lab.yaml").read_text())
            n_scen = len(list((d / "scenarios").glob("*.yaml")))
            print(f"✓ {d.name}: {len(lab['parts'])} parts, {len(lab['nets'])} nets, "
                  f"{len(lab['steps'])} steps, {len(lab['faults'])} faults, {n_scen} scenarios"
                  f"{'' if lab['verified'] else '  (not verified on hardware yet)'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
