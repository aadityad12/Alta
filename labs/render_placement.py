# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Draw both labs' breadboard placement + net/fault tables from lab.yaml.

    uv run labs/render_placement.py   # writes docs/visuals/lab-placement-v1.html

Re-run after editing any lab.yaml (e.g. after the hardware verify pass in #4).
"""
import html, re
from pathlib import Path

import yaml

root = Path(__file__).resolve().parent.parent
labs = [yaml.safe_load((root/f"labs/{l}/lab.yaml").read_text()) for l in ("lab1-led","lab2-light")]
P=16; X0=60; ROWS=40
cols="abcdefghij"
def cy(c):  # y of column letter
    i=cols.index(c); return 70+i*P+(26 if i>=5 else 0)
RAIL_Y={"rail:a+":24,"rail:a-":42,"rail:j+":70+9*P+26+30,"rail:j-":70+9*P+26+48}
def rx(r): return X0+(r-1)*P
def pos(at, other=None):
    if at in RAIL_Y:
        r=int(re.match(r"\d+",other).group()) if other else 1
        return rx(r), RAIL_Y[at]
    m=re.match(r"(\d+)([a-j])",at); return rx(int(m[1])), cy(m[2])
W=X0+ROWS*P+30; H=RAIL_Y["rail:j-"]+40
s=[f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Breadboard placement for Lab 1 and Lab 2">']
s.append(f'<defs><pattern id="hole" x="{X0-8}" y="0" width="{P}" height="{P}" patternUnits="userSpaceOnUse"><rect x="5.5" y="5.5" width="5" height="5" fill="#9a9384"/></pattern></defs>')
s.append(f'<rect x="{X0-22}" y="8" width="{ROWS*P+28}" height="{H-16}" rx="8" fill="#f4f1ea" stroke="#d6d0c4"/>')
s.append(f'<rect x="{X0-22}" y="{cy("e")+7}" width="{ROWS*P+28}" height="12" fill="#e6e0d4"/>')
for name,y in RAIL_Y.items():
    col="#d33" if name.endswith("+") else "#246"
    s.append(f'<line x1="{X0-14}" x2="{X0+(ROWS-1)*P+8}" y1="{y-8}" y2="{y-8}" stroke="{col}" stroke-width="1.5" opacity=".7"/>')
    s.append(f'<rect x="{rx(1)-8}" y="{y-8}" width="{ROWS*P}" height="{P}" fill="url(#hole)"/>')
    s.append(f'<text x="{X0-30}" y="{y+4}" font-size="9" text-anchor="end" fill="#555">{name[5:]}</text>')
s.append(f'<text x="{X0-30}" y="{RAIL_Y["rail:a+"]-14}" font-size="9" text-anchor="end" fill="#555">rail a</text>')
for c in cols:
    s.append(f'<text x="{X0-14}" y="{cy(c)+3}" font-size="9" text-anchor="middle" fill="#777">{c}</text>')
    s.append(f'<rect x="{rx(1)-8}" y="{cy(c)-8}" width="{ROWS*P}" height="{P}" fill="url(#hole)"/>')
for r in range(1,ROWS+1):
    if r==1 or r%5==0: s.append(f'<text x="{rx(r)}" y="{cy("a")-9}" font-size="8.5" text-anchor="middle" fill="#777">{r}</text>')
# lab zones
for lab,(a,b) in zip(labs,[(5,15),(25,35)]):
    s.append(f'<rect x="{rx(a)-7}" y="{cy("a")-20}" width="{(b-a)*P+14}" height="{cy("e")-cy("a")+28}" rx="5" fill="none" stroke="#2f81f7" stroke-dasharray="4 3"/>')
    s.append(f'<text x="{rx(a)-5}" y="{H-12}" font-size="11" font-weight="600" fill="#2f81f7">{html.escape(lab["title"])} · rows {a}–{b}</text>')
WIRE={"red":"#e03131","black":"#222"}
for lab in labs:
    for p in lab["parts"]:
        pins=list(p["pins"].values()); keys=list(p["pins"].keys())
        a=pos(pins[0],pins[1]); b=pos(pins[1],pins[0])
        if p["kind"]=="wire":
            s.append(f'<path d="M{a[0]},{a[1]} C{a[0]},{(a[1]+b[1])/2} {b[0]},{(a[1]+b[1])/2} {b[0]},{b[1]}" fill="none" stroke="{WIRE[p["color"]]}" stroke-width="3.5" stroke-linecap="round"/>')
            lx,ly=(a[0]+b[0])/2+8,(a[1]+b[1])/2
        else:
            s.append(f'<line x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}" stroke="#888" stroke-width="1.6"/>')
            mx,my=(a[0]+b[0])/2,(a[1]+b[1])/2
            if p["kind"]=="resistor":
                bands={220:["#d22","#d22","#7a4a1c"],10000:["#7a4a1c","#111","#f08c00"]}[p["value_ohm"]]
                s.append(f'<rect x="{mx-15}" y="{my-5}" width="30" height="10" rx="4" fill="#e9c98b" stroke="#a8874d"/>')
                for i,bc in enumerate(bands): s.append(f'<rect x="{mx-9+i*6}" y="{my-5}" width="3" height="10" fill="{bc}"/>')
            elif p["kind"]=="led":
                s.append(f'<circle cx="{a[0]}" cy="{a[1]-13}" r="7" fill="#ff6b6b" stroke="#c92a2a"/><line x1="{a[0]}" y1="{a[1]-6}" x2="{a[0]}" y2="{a[1]}" stroke="#888" stroke-width="1.6"/>')
                s.append(f'<path d="M{a[0]+4},{a[1]-13} Q{(a[0]+b[0])/2},{a[1]-22} {b[0]},{b[1]}" fill="none" stroke="#888" stroke-width="1.6"/>')
                s.append(f'<text x="{a[0]-10}" y="{a[1]-2}" font-size="9" font-weight="700" fill="#c92a2a">+</text>')
            elif p["kind"]=="photoresistor":
                s.append(f'<circle cx="{mx}" cy="{my}" r="8" fill="#f5e6b8" stroke="#a8874d"/><path d="M{mx-5},{my-2} h2 v4 h2 v-4 h2 v4 h2 v-4 h2" fill="none" stroke="#a33" stroke-width="1"/>')
            lx,ly=mx+12,my-10 if p["kind"]!="led" else a[1]-22
            if p["kind"]=="led": lx=a[0]+10
        s.append(f'<text x="{lx}" y="{ly}" font-size="10" font-weight="700" fill="#333">{p["ref"]}</text>')
s.append('</svg>')
svg="\n".join(s)
def esc(x): return html.escape(str(x))
def ohm(v): return f"{v//1000} kΩ" if v>=1000 else f"{v} Ω"
rows=[]
for lab in labs:
    netrows="".join(f'<tr><td class="mono">{esc(n["id"])}</td><td>{esc(n["label"])}</td><td class="mono">{esc(", ".join(n["holes"]))}</td><td class="num">{n["expected_mv"]} ± {n["tol_mv"]} mV</td></tr>' for n in lab["nets"])
    parts="".join(f'<tr><td class="mono">{esc(p["ref"])}</td><td>{esc(p["kind"])}{" "+ohm(p["value_ohm"]) if "value_ohm" in p else ""}{" ("+p["color"]+")" if "color" in p else ""}</td><td class="mono" colspan="2">{esc(" · ".join(f"{k}: {v}" for k,v in p["pins"].items()))}</td></tr>' for p in lab["parts"])
    faults="".join(f'<tr><td class="mono">{esc(f["id"])}</td><td>{esc(f["how_to_stage"])}</td><td>{esc(f["symptom"])}</td><td class="mono">{esc(", ".join(f"{k} {v}" for k,v in f["readings"].items()))}</td></tr>' for f in lab["faults"])
    rows.append(f'''<section><h3>{esc(lab["title"])} <span class="pill">verified: {str(lab["verified"]).lower()}</span></h3>
<table><thead><tr><th>Ref</th><th>Part</th><th colspan="2">Holes</th></tr></thead><tbody>{parts}</tbody></table>
<table><thead><tr><th>Net</th><th>Label</th><th>Holes</th><th>Expected</th></tr></thead><tbody>{netrows}</tbody></table>
<table><thead><tr><th>Fault</th><th>How to stage</th><th>Symptom</th><th>Readings (mV)</th></tr></thead><tbody>{faults}</tbody></table></section>''')
page=f'''<!doctype html><html><head><meta charset="utf-8"><title>ALTA · lab board placement</title><style>
:root{{--background:#0d1117;--foreground:#e6edf3;--muted-foreground:#8b949e;--card:#161b22;--border:#30363d;--accent:#2f81f7;--warning:#d29922;--font-sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;--font-mono:ui-monospace,SFMono-Regular,Menlo,monospace;--radius:8px}}
html{{background:var(--background)}}body{{margin:0 auto;padding:24px;max-width:980px;font-family:var(--font-sans);color:var(--foreground)}}
h2{{font-size:17px;margin:0 0 4px}}h3{{font-size:15px;margin:22px 0 8px;display:flex;gap:8px;align-items:center}}
.sub{{color:var(--muted-foreground);font-size:13px;line-height:1.45;margin:0 0 12px}}
.board{{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:10px}}
table{{border-collapse:collapse;width:100%;font-size:12.5px;margin-bottom:10px}}th{{text-align:left;font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted-foreground);padding:6px 8px;border-bottom:1px solid var(--border)}}
td{{padding:6px 8px;border-bottom:1px solid var(--border);vertical-align:top}}.mono{{font-family:var(--font-mono);font-size:11.5px}}.num{{font-variant-numeric:tabular-nums;white-space:nowrap}}
.pill{{font-size:11px;padding:1px 7px;border-radius:9px;background:color-mix(in srgb,var(--warning) 20%,transparent);color:var(--warning);font-weight:600}}
</style></head><body>
<h2>Lab board placement (one 830-point board, both labs)</h2>
<p class="sub">Generated from <code>labs/*/lab.yaml</code>, so these are the exact holes the mock pod, agent, manuals and overlays use. Power comes from the pod's red (5 V) and black (GND) wires onto the rails next to column a. Every value here is a draft until it's measured on the real board.</p>
<div class="board">{svg}</div>
{"".join(rows)}
</body></html>'''
(root/"docs/visuals/lab-placement-v1.html").write_text(page)
print("ok")
