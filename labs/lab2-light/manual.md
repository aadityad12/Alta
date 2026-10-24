# Lab 2 · Light sensor

## Objective

In this lab you'll build a light sensor on a breadboard: a photoresistor and a 10 kΩ resistor connected in series between 5 V and ground. This arrangement is called a voltage divider. You'll measure its output voltage in different lighting and use your readings to see how a changing resistance changes the voltage.

**Time:** about 15 minutes

## Parts and Equipment

| Ref | Component | Value | How to identify it |
|---|---|---|---|
| W1 | Jumper wire | — | Red |
| LDR1 | Photoresistor | Changes with light | Small disc with a squiggly line on top. It has no + or − side. |
| R1 | Resistor | 10 kΩ | Color bands: brown, black, orange |
| W2 | Jumper wire | — | Black |

**Equipment:** 830-point breadboard (you'll use rows 25–35), the Bench probe pod, and a phone flashlight. The pod supplies 5 V through its red and black wires and measures voltage with its colored probes.

A quick breadboard reminder: the five holes in each row-half (a–e or f–j) are connected to each other. The long power rails along the edge usually run the full length of the board, but some breadboards split each rail in the middle. If yours has a gap in the red or blue line, or you're not sure, check with your instructor or probe both ends of the rail before you start.

## Short Theory

**Photoresistor.** A photoresistor (also called a light-dependent resistor, or LDR) is a resistor whose resistance depends on light. More light means lower resistance. In the dark, its resistance becomes much higher.

**Series circuit.** The photoresistor and the 10 kΩ resistor are in series, so the same current flows through both. By Ohm's law (V = I × R), the part with more resistance has more voltage across it. The two voltages add up to the 5 V supply.

**Voltage divider.** The output is the point between the two parts (row 30). Its voltage depends on how the 5 V is shared:

V_out = 5 V × R1 / (R1 + R_photo)

When light hits the photoresistor, R_photo drops, so it takes a smaller share of the 5 V and V_out goes **up**. When you cover it, R_photo rises, it takes a bigger share, and V_out goes **down**.

**Example (theoretical estimates):** typical photoresistor values are assumed here, so these aren't exact.

| Lighting | R_photo (assumed) | V_out = 5 V × 10 kΩ / (10 kΩ + R_photo) |
|---|---|---|
| Phone flashlight | ≈ 300 Ω | ≈ 4.9 V |
| Room light | ≈ 4 kΩ | ≈ 3.6 V |
| Covered with a finger | ≈ 200 kΩ | ≈ 0.2 V |

These numbers are only estimates, not measured results. Your actual readings will depend on your particular photoresistor (they vary quite a bit from part to part) and on the lighting around you. What matters is the pattern: brighter light should give a higher output, and darkness a lower one.

## Circuit Diagram

Make these connections:

| Ref | From | To |
|---|---|---|
| W1 | + rail (5 V) | 26a |
| LDR1 | 26c | 30c |
| R1 | 30d | 34d |
| W2 | 34a | − rail (ground) |

Current path:

```
+5 V rail ──W1── row 26 ──LDR1 (photoresistor)── row 30 (output) ──R1 (10 kΩ)── row 34 ──W2── ground rail
```

## Experimental Procedure

Before you start, make sure the pod's **red** wire is in the **+ rail** next to column a, and its **black** wire is in the **− rail** next to it.

## Step 1 — Power the rails

1. Connect the red jumper wire **W1** from the **+ rail** to hole **26a**.

**Check:** Probe row 26. It should read about **5 V**.

## Step 2 — Add the photoresistor

1. Insert the photoresistor **LDR1** from **26c** to **30c**. It can go in either way round.

**Check:** Row 26 should still read about **5 V**.

## Step 3 — Add the 10 kΩ to ground

1. Insert the 10 kΩ resistor **R1** from **30d** to **34d**.
2. Connect the black jumper wire **W2** from **34a** to the **− rail**.

**Check:** Row 34 should read about **0 V**. Row 30 (the output) should read somewhere between 0 and 5 V. The exact value depends on the light in the room.

## Step 4 — Cover the sensor and watch the output

1. Keep a probe on **row 30**.
2. Cover the photoresistor with your finger, then uncover it.
3. Shine a phone flashlight on it.

**Check:** Covering the sensor should make the output **go down**. The flashlight should make it **go up**.

## Measurements and Observations

Probe each point and record your readings. The expected values are theoretical estimates, not measured results. Don't worry if your numbers are different. Your photoresistor and lighting will change them.

| Lighting | Probe point | Expected (estimate) | Measured |
|---|---|---|---|
| Any | Row 26 (supply) | about 5.0 V | |
| Any | Row 34 (ground) | about 0 V | |
| Room light | Row 30 (output) | about 3.5 V | |
| Covered with a finger | Row 30 (output) | below about 1 V | |
| Phone flashlight | Row 30 (output) | close to 5 V | |

Use your measured values to answer:

1. When you covered the sensor, did the output go up or down? Explain why, using the photoresistor's resistance. __________
2. In which lighting condition was the photoresistor's resistance the highest? __________
3. In room light, what is the voltage across the photoresistor (row 26 − row 30) and across the 10 kΩ resistor (row 30 − row 34)? Do they add up to about 5 V? __________
4. In room light, which part had more voltage across it? What does that tell you about which one had more resistance? __________

## What You Learned

- A **photoresistor's resistance changes with light**: lower in bright light, higher in the dark.
- Two resistances in series form a **voltage divider** that shares the supply voltage between them.
- The part with **more resistance** has **more voltage** across it (Ohm's law, V = IR).
- The voltages across parts in series **add up to the supply voltage**.
- In this circuit, covering the sensor raises its resistance, so the output voltage goes **down**.
