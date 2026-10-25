# labs/

One folder per lab: `labs/<lab_id>/` with `lab.yaml`, `manual.md`, `schematic.svg`, `scenarios/`. Schema in docs/CONTRACTS.md §6.

ALTA's answer keys:

| file | what | owner |
|---|---|---|
| `lab.yaml` | parts + exact holes, nets + expected voltages, manual steps, fault catalog + hint ladders. Schema: `docs/CONTRACTS.md` §6 | Engineer A (#4) |
| `scenarios/*.yaml` | mock-pod scenarios: `normal.yaml` + one per fault (format below) | Engineer A (#4, #9) |
| `manual.md`, `schematic.svg` | student manual + schematic. Step numbers must match `steps`, and SVG element ids must match net ids | Designer 2 (#35) |

Check everything after any edit:

```sh
uv run labs/validate.py
```

It loads every YAML file and rebuilds the circuit's connectivity from the parts (wires join the strips and rails they touch). Then it checks:
- every net's holes really are wired together, and every part pin is in some net
- two parts never share a hole
- fault `readings` cover every net, and every fault has the 4-level hint ladder
- every fault has a scenario, and each scenario's light model matches `lab.yaml`

## Placement (one 830-point board serves both labs)

Diagram: `docs/visuals/lab-placement-v1.html`. Regenerate it after editing a lab with `uv run labs/render_placement.py`.

Power comes from the pod's red/black wires onto the rails next to column **a** (`rail:a+` = 5 V, `rail:a-` = GND).

**Lab 1 · LED** (rows 5–15)
| ref | part | holes |
|---|---|---|
| W1 | red wire | `rail:a+` → `5a` |
| R1 | 220 Ω (red-red-brown) | `5c` → `10c` |
| D1 | red LED | anode (long leg) `10e`, cathode `15e` |
| W2 | black wire | `15a` → `rail:a-` |

Probe points: row 5 = 5 V · row 10 = LED anode ≈ 2.0 V · row 15 = LED cathode ≈ 0 V

**Lab 2 · Light sensor** (rows 25–35)
| ref | part | holes |
|---|---|---|
| W1 | red wire | `rail:a+` → `26a` |
| LDR1 | photoresistor | `26c` → `30c` |
| R1 | 10 kΩ (brown-black-orange) | `30d` → `34d` |
| W2 | black wire | `34a` → `rail:a-` |

Probe points: row 26 = 5 V · row 30 = output (room ≈ 3.5 V, covered < 1 V, flashlight ≈ 4.8 V) · row 34 = GND

All values are drafts until measured on the real board (#4 verify step, then `verified: true`). Measure them with `uv run labs/measure.py lab1-led` (or `lab2-light`): plug in one probe per net once, stage each state when asked, and it saves `labs/<lab>/measured.yaml` plus a table for #4.

## Scenario format (`scenarios/<fault_id>.yaml`, or `normal.yaml`)

The mock pod (#9) loads a lab plus one scenario. This format belongs to the mock, not the #2 contract.

```yaml
lab: lab1-led              # must match lab.yaml id
fault: led_reversed        # a fault id from lab.yaml, or null for the correct circuit
nets:                      # optional: per-net overrides applied after the fault's readings
  n_led_cathode: {noise_mv: 1000}    # mv and/or noise_mv (default noise ±5 mV)
holes:                     # optional: holes/strips that are in NO net but read something with this fault
  "11:a-e": {mv: 100, noise_mv: 100}
light_model:               # optional (Lab 2): how the `light 0..1` command moves a net
  net: n_out
  sensor_on: top           # top = between 5 V and the net, bottom = between the net and GND
  fixed_ohm: 10000         # the other resistor in the divider
  sensor_ohm: {dark: 200000, room: 4000, bright: 300}
probes: {Y: "10c"}         # optional: where the probes start
```

**How the mock works out a probe's voltage:** look at the strip the probe is plugged into.
1. If it's in a net, start from `expected_mv`. Replace it with the fault's `readings[net]` if a fault is active. If `light_model.net` is this net, use the light model instead. Then apply `nets` overrides.
2. If it's listed under `holes`, use that.
3. Otherwise it's floating: random noise.

**Light model:** `light` 0 = covered, 0.5 = room, 1 = flashlight. Sensor resistance is interpolated on a log scale between `dark` → `room` → `bright`, and the divider gives `supply_mv × R_bottom / (R_bottom + R_top)`. `light_model: null` means the net ignores light, e.g. a probe in the wrong row. Reference implementation: `light_mv()` in `validate.py`.
