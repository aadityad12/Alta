# Lab 1 · Light an LED

## Objective

In this lab you'll build a basic LED circuit on a breadboard: a 5 V supply, a 220 Ω resistor and a red LED connected in series. Along the way you'll measure the voltage at each point in the circuit and use those readings to see how voltage, current and resistance are related.

**Time:** about 15 minutes

## Parts and Equipment

| Ref | Component | Value | How to identify it |
|---|---|---|---|
| W1 | Jumper wire | — | Red |
| R1 | Resistor | 220 Ω | Color bands: red, red, brown |
| D1 | LED | Red | Two legs. The **longer leg** is the anode (+); the shorter leg is the cathode (−). |
| W2 | Jumper wire | — | Black |

**Equipment:** 830-point breadboard (you'll use rows 5–20) and the ALTA probe pod. The pod supplies 5 V through its red and black wires and measures voltage with its colored probes.

A quick breadboard reminder: the five holes in each row-half (a–e or f–j) are connected to each other. The long rails along the edge are connected along their whole length.

## Short Theory

**Complete circuit.** Current only flows when there is a closed path, from the + side of the supply, through the parts, and back to ground (−). If the path is broken anywhere, no current flows anywhere in the loop.

**LED.** An LED (light-emitting diode) lets current through in one direction only, from the anode (+) to the cathode (−). Put in backwards, it blocks the current and stays dark. When a red LED is conducting, it has a nearly constant voltage of about 2 V across it.

**Resistor.** Without something to limit it, the current through the LED would be large enough to damage it. The resistor sets the current to a safe level.

**Ohm's law.** The voltage across a resistor equals the current through it times its resistance:

V = I × R

**Series voltages.** In a single loop, the same current flows through every part, and the voltages across the parts add up to the supply voltage:

V_supply = V_resistor + V_LED

**Example (theoretical estimates):**

| Quantity | Value |
|---|---|
| Supply voltage | 5.0 V |
| Voltage across the LED | ≈ 2.0 V |
| Voltage across the resistor | 5.0 V − 2.0 V ≈ 3.0 V |
| Current | I = 3.1 V / 220 Ω ≈ 0.014 A = 14 mA |

These numbers were measured on our demo board. Your parts may read a little differently.

## Circuit Diagram

The full schematic appears in the schematic panel. The connections are:

| Ref | From | To |
|---|---|---|
| W1 | + rail (5 V) | 5a |
| R1 | 5c | 15c |
| D1 | 15e (anode, long leg) | 20e (cathode, short leg) |
| W2 | 20a | − rail (ground) |

Current path:

```
+5 V rail ──W1── row 5 ──R1 (220 Ω)── row 15 ──D1 (anode → cathode)── row 20 ──W2── ground rail
```

## Experimental Procedure

Before you start, plug the pod's **red** wire into the **+ rail** next to column a, and its **black** wire into the **− rail** next to it.

## Step 1 — Power the rails

1. Connect the red jumper wire **W1** from the **+ rail** to hole **5a**.

**Check:** Probe row 5. It should read about **5 V**.

## Step 2 — Add the resistor

1. Insert the 220 Ω resistor **R1** from **5c** to **15c**. A resistor can go in either way round.

**Check:** Row 5 should still read about **5 V**.

## Step 3 — Add the LED

1. Insert the LED's **long leg** (anode) into **15e**.
2. Insert the **short leg** (cathode) into **20e**.

**Check:** The LED should stay **off**. That's expected: row 20 isn't connected to ground yet, so the circuit isn't complete and no current can flow.

## Step 4 — Connect to ground

1. Connect the black jumper wire **W2** from **20a** to the **− rail**.

**Check:** The LED should light up. Row 15 should read about **2.0 V**, and row 20 about **0 V**.

## Measurements and Observations

With the LED lit, probe each row and record your readings. The expected values were measured on our demo board.

| Probe point | Part of the circuit | Expected (approx.) | Measured |
|---|---|---|---|
| Row 5 | Supply (5 V) | 5.0 V | |
| Row 15 | LED anode | 2.0 V | |
| Row 20 | LED cathode | 0 V | |

Use your measured values to answer:

1. What is the voltage across the resistor? (row 5 − row 15) __________
2. What is the voltage across the LED? (row 15 − row 20) __________
3. Add your two answers. Is the total close to the supply voltage (row 5)? __________
4. Use Ohm's law and your answer to question 1 to estimate the current: I = V_resistor / 220 Ω = __________
5. In Step 3, the LED was off. What would row 15 read with no current flowing, and why? __________

## What You Learned

- Current only flows through a **complete circuit**.
- An LED conducts in **one direction only**, from anode (long leg) to cathode (short leg).
- A **resistor limits the current** to protect the LED.
- **Ohm's law**, V = IR, relates the voltage across a resistor to the current through it.
- In a series circuit, the **voltage drops add up to the supply voltage**: about 3.0 V across the resistor plus about 2.0 V across the LED gives 5 V.
