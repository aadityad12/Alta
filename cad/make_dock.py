# /// script
# requires-python = ">=3.11"
# dependencies = ["manifold3d==3.5.4", "trimesh==5.2.0", "matplotlib>=3.9,<4"]
# ///
"""Generate the open-top Bench pod dock, in millimeters. Run with uv run.

The default mini profile uses a conservative ruler-photo envelope and tape mount.
The legacy large profile remains available as an explicitly named DRAFT.
The USB edge is the left edge of the Uno.
"""

import argparse
import json
from pathlib import Path

import manifold3d as m
import trimesh


def box(x, y, z, dx, dy, dz):
    return m.Manifold.cube((dx, dy, dz)).translate((x, y, z))


def make_mini(args):
    """Open mount accommodates source variants without matching their holes/tabs."""
    length, width, height = args.breadboard
    if not (40 <= length <= 52 and 30 <= width <= 40 and 6 <= height <= 13):
        raise ValueError("Mini profile accepts L 40–52, W 30–40, H 6–13 mm.")
    base, wall = 2.4, 2.0
    outer_l, outer_w = 144., 86.
    ux, uy = 6., 19.
    mount = (84., 20., 56., 44.)
    bx = mount[0] + (mount[2] - length) / 2
    by = mount[1] + (mount[3] - width) / 2
    solids = [box(0, 0, 0, outer_l, outer_w, base)]
    # Rim leaves the whole USB/barrel-jack end open. No lid or connector apertures.
    solids += [box(0, 0, base - .1, outer_l, wall, 3.1),
               box(0, outer_w - wall, base - .1, outer_l, wall, 6.1),
               box(outer_l - wall, wall, base - .1, wall, outer_w - 2 * wall, 6.1)]
    # Runners and foam tape support the Uno without locating pegs or screw holes.
    for x in (ux + 21, ux + 53):
        solids.append(box(x, uy + 5, base - .1, 7., 43.4, 5.1))
    # A low outline marks the roomy mini-board mounting area; it is not a snap fit.
    mx, my, ml, mw = mount
    for x, y, dx, dy in [(mx, my, ml, .6), (mx, my + mw - .6, ml, .6),
                          (mx, my, .6, mw), (mx + ml - .6, my, .6, mw)]:
        solids.append(box(x, y, base - .1, dx, dy, .5))
    # Raised channel labels, with independent routing slots near the front edge.
    label_x, label_y = 84., 8.
    for i, letter in enumerate("YBGW"):
        for row, cells in enumerate(LETTERS[letter]):
            for col, filled in enumerate(cells):
                if filled == "1":
                    solids.append(box(label_x + i * 15 + col, label_y + 6 - row,
                                      base - .1, 1.05, 1.05, .9))
    dock = m.Manifold.batch_boolean(solids, m.OpType.Add)
    cuts = []
    for x in (ux + 15, ux + 55):
        for y in (uy - 4, uy + 55):
            cuts.append(box(x, y, -1, 8, 2, base + 2))
    for x in (89, 122):
        for y in (17, 67):
            cuts.append(box(x, y, -1, 8, 2, base + 2))
    for i in range(4):
        cuts.append(box(label_x + i * 15, 4, -1, 5, 2, base + 2))
    dock = m.Manifold.batch_boolean([dock, *cuts], m.OpType.Subtract)
    raw = dock.to_mesh()
    mesh = trimesh.Trimesh(vertices=raw.vert_properties[:, :3], faces=raw.tri_verts,
                           process=True)
    bodies = len(dock.decompose())
    downward = mesh.triangles[mesh.face_normals[:, 2] < -.5]
    if not mesh.is_watertight or not mesh.is_volume or bodies != 1:
        raise RuntimeError("Refusing to export: expected one closed positive-volume body.")
    if abs(mesh.bounds[0, 2]) > 1e-5 or downward[:, :, 2].max() > 1e-5:
        raise RuntimeError("Refusing to export: base/unsupported underside check failed.")
    if max(mesh.extents[:2]) + 12 > 256:
        raise RuntimeError("P1S bed allowance exceeded.")
    return mesh, {
        "status": "RULER-PHOTO-SIZED — conservative envelope; physical fit untested; tape mount",
        "profile": "mini-170",
        "units": "mm",
        "breadboard_lwh": [length, width, height],
        "breadboard_dimensions_are_measured": False,
        "dimension_basis": "User ruler photos: approximately 47–48 × 37 × 10 mm; rounded-up design envelope",
        "dimensions_are_design_envelope": True,
        "breadboard_source_range_lwh": [[45., 47.], [35., 35.6], [8.5, 10.]],
        "breadboard_mount_xywh": list(mount),
        "breadboard_clear_mount_lw": [54.8, 42.8],
        "breadboard_origin_xy": [bx, by],
        "uno_lw_assumed": [68.6, 53.4],
        "uno_origin_xy": [ux, uy],
        "uno_underside_clearance_between_runners": 5.,
        "retention": "foam tape on Uno runners; removable mounting tape under mini breadboard",
        "outer_lwh": [round(float(v), 3) for v in mesh.extents],
        "base_thickness": base,
        "rear_wall_above_base": 6.,
        "solid_volume_cm3": round(mesh.volume / 1000, 2),
        "watertight": bool(mesh.is_watertight),
        "positive_volume": bool(mesh.is_volume),
        "connected_bodies": bodies,
        "unsupported_downward_faces_above_base": 0,
        "triangles": len(mesh.faces),
        "slicer_time": "NOT YET MEASURED; must be <= 2.5 hours in Bambu Studio",
        "sources": ["https://www.makerfabs.com/mini-bread-board-4-5x3-5cm.html",
                    "https://www.sparkfun.com/breadboard-mini-modular-white.html",
                    "https://busboard.com/BB170",
                    "https://store.arduino.cc/products/arduino-uno-rev3"],
    }


# 1 mm square strokes; no font installation required, no floating islands.
LETTERS = {
    "Y": ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "G": ["01111", "10000", "10000", "10111", "10001", "10001", "01111"],
    "W": ["10001", "10001", "10001", "10101", "10101", "11011", "10001"],
}


def make(args):
    length, width, height = args.breadboard
    if not (130 <= length <= 210 and 40 <= width <= 85 and 5 <= height <= 20):
        raise ValueError("Expected an 830-point breadboard: L 130–210, W 40–85, H 5–20 mm.")
    base, wall, clearance = 2.4, 2.0, 1.0  # clearance on EACH side
    ux, uy = 9.0, width + 15.0
    uno_l, uno_w = 68.6, 53.3
    outer_l = max(length + 2 * (wall + clearance), 166.0)
    outer_w = uy + uno_w + 3.0 + wall
    if outer_l + 12 > 256 or outer_w + 12 > 256:
        raise ValueError("Does not fit the 256 mm P1S bed with a 6 mm brim allowance.")
    # Sidewalls stay below the breadboard's top; its button and LED remain exposed.
    low = min(4.0, height - 2.0)
    high = 15.0
    solids = [box(0, 0, 0, outer_l, outer_w, base)]
    solids += [
        box(0, 0, base - .1, outer_l, wall, low + .1),
        box(0, wall, base - .1, wall, width + 2 * clearance, low + .1),
        box(outer_l - wall, wall, base - .1, wall, width + 2 * clearance, low + .1),
        # Low divider retains breadboard without blocking jumper wires.
        box(0, width + 2 * clearance + wall, base - .1, outer_l, wall, low + .1),
        box(0, outer_w - wall, base - .1, outer_l, wall, high + .1),
        box(outer_l - wall, width + 2 * clearance + 2 * wall,
            base - .1, wall, outer_w - width - 2 * clearance - 3 * wall, high + .1),
    ]
    # Entire left end of Uno bay is open: USB-B and barrel jack can overhang.
    # Tape-supported runners avoid relying on unmeasured clone mounting holes.
    runners = [(ux + 20, uy + 2, 7, uno_w - 4), (ux + 52, uy + 2, 7, uno_w - 4)]
    for x, y, dx, dy in runners:
        solids.append(box(x, y, base - .1, dx, dy, 5.1))
    # Raised letters in the free area to the right of the Uno.
    label_x = ux + uno_l + 14
    label_y = uy + 18
    for i, letter in enumerate("YBGW"):
        for row, cells in enumerate(LETTERS[letter]):
            for col, filled in enumerate(cells):
                if filled == "1":
                    solids.append(box(label_x + i * 17 + col, label_y + 6 - row,
                                      base - .1, 1.05, 1.05, .9))
    dock = m.Manifold.batch_boolean(solids, m.OpType.Add)
    cuts = []
    # Vertical slots accept tape/zip ties; their roofs need no support.
    # Board retention uses tape over its non-connector edges, never its pin headers.
    for x, y in [(ux + 12, uy - 3), (ux + 12, uy + uno_w + .5),
                 (ux + 54, uy - 3), (ux + 54, uy + uno_w + .5)]:
        cuts.append(box(x, y, -1, 8, 2, base + 2))
    # Open-top cable notches aligned with the channel labels.
    for i in range(4):
        cuts.append(box(label_x + i * 17, outer_w - wall - .1, base + 5,
                        5, wall + .2, high + 1))
    dock = m.Manifold.batch_boolean([dock, *cuts], m.OpType.Subtract)
    raw = dock.to_mesh()
    mesh = trimesh.Trimesh(vertices=raw.vert_properties[:, :3], faces=raw.tri_verts,
                           process=True)
    bodies = len(dock.decompose())
    if not mesh.is_watertight or not mesh.is_volume or bodies != 1:
        raise RuntimeError("Refusing to export: mesh is not one closed positive-volume body.")
    if abs(mesh.bounds[0, 2]) > 1e-5:
        raise RuntimeError("Refusing to export: base is not on Z=0.")
    return mesh, {
        "status": "MEASURED — still requires fit check and slicing" if args.measured else
                  "DRAFT — assumed dimensions; do not submit for printing",
        "units": "mm",
        "breadboard_lwh": [length, width, height],
        "breadboard_pocket_lw": [outer_l - 2 * wall, width + 2 * clearance],
        "breadboard_origin_xy": [wall + clearance, wall + clearance],
        "uno_lw_assumed": [uno_l, uno_w],
        "uno_origin_xy": [ux, uy],
        "uno_underside_clearance": 5.0,
        "retention": "foam mounting tape on Uno runners; removable tape under breadboard",
        "outer_lwh": [round(float(v), 3) for v in mesh.extents],
        "base_thickness": base,
        "breadboard_wall_above_base": low,
        "rear_wall_above_base": high,
        "solid_volume_cm3": round(mesh.volume / 1000, 2),
        "watertight": bool(mesh.is_watertight),
        "positive_volume": bool(mesh.is_volume),
        "connected_bodies": bodies,
        "triangles": len(mesh.faces),
        "slicer_time": "NOT YET MEASURED; must be <= 2.5 hours in Bambu Studio",
    }


def preview(mesh, output, data):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection

    fig = plt.figure(figsize=(9, 7.5), facecolor="#f6f5f1")
    ext = mesh.extents
    top = fig.add_subplot(111)
    top.set_facecolor("#f6f5f1")
    faces = mesh.triangles[mesh.face_normals[:, 2] > .5]
    faces = sorted(faces, key=lambda f: f[:, 2].mean())
    for face in faces:
        z = face[:, 2].mean()
        color = "#d5e4e1" if z < 3 else "#527f7d"
        if 3 < z < 4:
            color = "#203e40"  # raised lettering, highlighted for legibility
        top.add_collection(PolyCollection([face[:, :2]], facecolor=color,
                                         edgecolor=color, linewidth=.1,
                                         antialiased=False))
    top.set(xlim=(-3, ext[0] + 3), ylim=(-3, ext[1] + 3), aspect="equal")
    top.set_axis_off()
    ux, uy = data["uno_origin_xy"]
    bx, by = data["breadboard_origin_xy"]
    from matplotlib.patches import Rectangle
    top.add_patch(Rectangle((ux, uy), 68.6, 53.4, fill=False,
                            edgecolor="#203e40", linestyle="--", linewidth=1))
    bl, bw, _ = data["breadboard_lwh"]
    top.add_patch(Rectangle((bx, by), bl, bw, fill=False,
                            edgecolor="#203e40", linestyle="--", linewidth=1))
    top.text(ux + 8, uy + 25, "UNO R3", fontsize=11, color="#203e40")
    top.text(bx + 3, by + bw / 2, "MINI 170" if data.get("profile") == "mini-170"
             else "POD BREADBOARD", fontsize=10, color="#203e40")
    top.text(ux, uy + 12, "← USB", fontsize=10, color="#203e40")
    fig.subplots_adjust(left=.04, right=.96, top=.88, bottom=.12)
    fig.text(.05, .94, output.stem.replace("_", " "), fontsize=18, color="#243638")
    fig.text(.05, .89, "Ruler-photo envelope · loose tape mount · open USB end"
             if data.get("profile") == "mini-170" else "Draft · assumed dimensions",
             fontsize=11, color="#243638")
    fig.text(.05, .05, f"STL top view · {ext[0]:.1f} × {ext[1]:.1f} × {ext[2]:.1f} mm"
             " · single-color print", fontsize=11, color="#243638")
    fig.savefig(output.with_suffix(".png"), dpi=140)
    plt.close(fig)


def fit_sheet(data, output):
    length, width, _ = data["breadboard_lwh"]
    bx, by = data["breadboard_origin_xy"]
    ux, uy = data["uno_origin_xy"]
    uno_l, uno_w = data["uno_lw_assumed"]
    lx, ly, _ = data["outer_lwh"]
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{lx}mm" height="{ly + 25}mm"
        viewBox="0 0 {lx} {ly + 25}">
      <rect width="100%" height="100%" fill="white"/>
      <g fill="none" stroke="black" stroke-width=".3">
        <rect x=".2" y=".2" width="{lx - .4}" height="{ly - .4}"/>
        <rect x="{bx}" y="{by}" width="{length}" height="{width}"/>
        <rect x="{ux}" y="{uy}" width="{uno_l}" height="{uno_w}"/>
        <path d="M5 {ly + 15}h100m-100 -2v4m100 -4v4"/>
      </g>
      <g font-family="sans-serif" font-size="3" fill="black">
        <text x="{bx + 3}" y="{by + 6}">Breadboard {length:g} × {width:g} mm</text>
        <text x="{ux + 3}" y="{uy + 8}">Uno R3 {uno_l} × {uno_w} mm</text>
        <text x="{ux + 3}" y="{uy + 14}">USB / barrel jack toward LEFT</text>
        <text x="5" y="{ly + 8}">REFERENCE ONLY · Print at 100%, never “fit to page”.</text>
        <text x="5" y="{ly + 22}">This scale bar must measure exactly 100 mm.</text>
      </g>
    </svg>'''
    output.with_name(output.stem + "_fit.svg").write_text(svg)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("mini", "large"), default="mini")
    parser.add_argument("--breadboard", type=float, nargs=3, metavar=("L", "W", "H"),
                        help="Measured outside dimensions INCLUDING tabs and backing, in mm")
    parser.add_argument("--measured", action="store_true",
                        help="Use measured dimensions and the final pod_dock filename")
    args = parser.parse_args()
    if args.measured and args.breadboard is None:
        parser.error("--measured requires --breadboard L W H")
    if args.breadboard is None:
        args.breadboard = (48., 38., 11.) if args.profile == "mini" else (165., 55., 10.)
    if args.measured and args.profile == "mini":
        parser.error("Mini dimensions are a ruler-photo envelope; do not label them exact measurements.")
    mesh, data = make_mini(args) if args.profile == "mini" else make(args)
    root = Path(__file__).resolve().parent
    output = root / ("pod_dock.stl" if args.profile == "mini" or args.measured
                     else "pod_dock_DRAFT.stl")
    mesh.export(output)
    data["stl"] = output.name
    output.with_suffix(".json").write_text(json.dumps(data, indent=2) + "\n")
    preview(mesh, output, data)
    fit_sheet(data, output)
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
