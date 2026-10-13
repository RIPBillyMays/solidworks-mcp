"""LIVE Phase 5 Batch C1 verification: assembly mates, component patterns, mirror, sub-assembly.

SW 2017 must be running, launched by the user.  Strictly serial, one agent at a time (ADR-0003/0005).

Run:  SW_MCP_OUTPUT_ROOT=<repo>\\sandbox python tests/live_p5_batchC1.py [limit|gear|rack|screw|cam|hinge|slot|path|sym|width|
                                                                      materef|linear|circular|derived|mirror|subasm ...]
Calls tool handlers in-process; builds its own fixtures under sandbox\\phase5\\batchC1\\; closes only docs it created.
Prints PASS / FAIL / FENCE-CANDIDATE per item.  FENCE-CANDIDATE = the create call was refused, returned nothing or
changed nothing (ADR-0006 criterion b, first attempt); try the alternative LIVE_PROBE value once more, then fence.

Nothing here is verified yet: every LIVE_PROBE_* constant in sw_mates_adv.py / sw_asm_pattern.py is a first guess.
The probe helper `try_probe` flips one constant and retries, logging which value worked.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import solidworks_mcp.server  # noqa: E402,F401  (registers every tool)

from solidworks_mcp.sw_core import OUTPUT_ROOT as _OUT_ROOT  # noqa: E402

if Path(_OUT_ROOT).resolve() != (ROOT / "sandbox").resolve():
    sys.exit(f"ABORT: SW_MCP_OUTPUT_ROOT must be {ROOT / 'sandbox'} (resolved to {_OUT_ROOT}); "
             "set SW_MCP_OUTPUT_ROOT=<repo>\sandbox and rerun.")
from solidworks_mcp import sw_asm_pattern, sw_mates_adv  # noqa: E402
from solidworks_mcp.sw_assembly import (  # noqa: E402
    add_mate, delete_mate, insert_component, list_components, list_mates, move_component, rotate_component,
    set_component_fixed,
)
from solidworks_mcp.sw_asm_pattern import (  # noqa: E402
    circular_component_pattern, create_subassembly, linear_component_pattern, mirror_components,
    pattern_driven_component_pattern,
)
from solidworks_mcp.sw_mates_adv import add_mate_reference  # noqa: E402
from solidworks_mcp.sw_feature import boss_extrude, cut_extrude, linear_pattern  # noqa: E402
from solidworks_mcp.sw_file import (  # noqa: E402
    close_document, create_new_document, list_open_documents, save_document,
)
from solidworks_mcp.sw_inspect import list_edges, list_faces, list_features  # noqa: E402
from solidworks_mcp.sw_sketch import (  # noqa: E402
    close_sketch, create_sketch, draw_circle, draw_rectangle, draw_slot,
)

OUT = ROOT / "sandbox" / "phase5" / "batchC1"
PARTS = OUT / "parts"
PARTS.mkdir(parents=True, exist_ok=True)
LOG: list[str] = []
created: list[str] = []
PF: dict[str, list[dict]] = {}   # part name -> faces at build time (index order == component face order)
PE: dict[str, list[dict]] = {}   # part name -> edges at build time
PATH: dict[str, Path] = {}


# ---------------------------------------------------------------- helpers
def log(step: str, ok, detail: str = "", status: str | None = None, fence: bool = False) -> None:
    st = status or ("PASS" if ok else ("FENCE-CANDIDATE" if fence else "FAIL"))
    line = f"{st} | {step} | {detail}"
    LOG.append(line)
    print(line, flush=True)


def call(fn, args=None, ctx=""):
    try:
        r = fn(args or {})
    except Exception as exc:  # noqa: BLE001
        r = {"ok": False, "message": f"EXC {exc!r}", "data": {}}
    if not r.get("ok"):
        print(f"  (call {fn.__name__} {ctx} -> not ok: {r.get('message')} "
              f"{json.dumps(r.get('data'), default=str)[:400]})", flush=True)
    return r


def D(r):
    return r.get("data") or {}


def near(a, b, tol=0.05):
    return a is not None and b is not None and abs(a - b) <= tol


def docs():
    return D(call(list_open_documents))["documents"]


def newdoc(kind):
    before = {d["title"] for d in docs()}
    call(create_new_document, {"kind": kind})
    for d in docs():
        if d["title"] not in before:
            created.append(d["title"])
            return d["title"]


def close_own(title):
    call(close_document, {"title": title, "force": True})
    if title in created:
        created.remove(title)


def sketch_rect(plane, x1, y1, x2, y2, name):
    call(create_sketch, {"plane": plane, "name": name})
    call(draw_rectangle, {"x1_mm": x1, "y1_mm": y1, "x2_mm": x2, "y2_mm": y2})
    call(close_sketch)


def sketch_circle(plane, x, y, r, name):
    call(create_sketch, {"plane": plane, "name": name})
    call(draw_circle, {"x_mm": x, "y_mm": y, "radius_mm": r})
    call(close_sketch)


def faces():
    return D(call(list_faces))["faces"]


def edges():
    return D(call(list_edges))["edges"]


def pick_face(normal, z=None, axis=2, tol=0.6, fs=None):
    for f in fs or faces():
        n = f.get("normal")
        if f.get("surface_type") != "plane" or not n:
            continue
        if abs(sum(a * b for a, b in zip(n, normal)) - 1) > 0.02:
            continue
        if z is not None and abs(f["point_mm"][axis] - z) > tol:
            continue
        return f
    return None


def save_part(name):
    p = PARTS / (name + ".sldprt")
    p.unlink(missing_ok=True)
    r = call(save_document, {"path": str(p)})
    PATH[name] = p
    return r["ok"] and p.exists() and p.stat().st_size > 0


def build_parts():
    """Plate 80x60x10, Block 20x20x10, Pin r5 h30, Shaft (collar r10 h5 + r5 to z=40), Disk r15 h10 with r5 bore,
    Rack 100x10x10, PlateH (Plate + hole r5 at x=-20 + linear pattern of 3 at 20 mm), SlotPlate (slot 30 long, 10 wide)."""
    ok = {}

    def done(name, title):
        PF[name], PE[name] = faces(), edges()
        ok[name] = save_part(name)
        close_own(title)

    t = newdoc("part"); sketch_rect("front", -40, -30, 40, 30, "S"); call(boss_extrude, {"sketch_name": "S", "depth_mm": 10, "name": "Pl"}); done("Plate", t)
    t = newdoc("part"); sketch_rect("front", -10, -10, 10, 10, "S"); call(boss_extrude, {"sketch_name": "S", "depth_mm": 10, "name": "Bl"}); done("Block", t)
    t = newdoc("part"); sketch_circle("front", 0, 0, 5, "S"); call(boss_extrude, {"sketch_name": "S", "depth_mm": 30, "name": "Pn"}); done("Pin", t)
    t = newdoc("part"); sketch_rect("front", -50, -5, 50, 5, "S"); call(boss_extrude, {"sketch_name": "S", "depth_mm": 10, "name": "Rk"}); done("Rack", t)
    # Shaft: collar then the upper shaft sketched on the collar top
    t = newdoc("part"); sketch_circle("front", 0, 0, 10, "S"); call(boss_extrude, {"sketch_name": "S", "depth_mm": 5, "name": "Col"})
    top = pick_face((0, 0, 1), 5)
    call(create_sketch, {"face_index": top["index"], "name": "S2"}); call(draw_circle, {"x_mm": 0, "y_mm": 0, "radius_mm": 5}); call(close_sketch)
    call(boss_extrude, {"sketch_name": "S2", "depth_mm": 35, "name": "Sh"}); done("Shaft", t)
    # Disk with bore
    t = newdoc("part"); sketch_circle("front", 0, 0, 15, "S"); call(boss_extrude, {"sketch_name": "S", "depth_mm": 10, "name": "Dk"})
    sketch_circle("front", 0, 0, 5, "SB"); call(cut_extrude, {"sketch_name": "SB", "end_condition": "through_all", "name": "Bore"}); done("Disk", t)
    # PlateH: hole + linear pattern of the hole feature
    t = newdoc("part"); sketch_rect("front", -40, -30, 40, 30, "S"); call(boss_extrude, {"sketch_name": "S", "depth_mm": 10, "name": "Pl"})
    sketch_circle("front", -20, 0, 5, "SH"); call(cut_extrude, {"sketch_name": "SH", "end_condition": "through_all", "name": "Hole1"})
    ex = next((e for e in edges() if e.get("curve_type") == "line" and abs(e["start_mm"][1] - e["end_mm"][1]) < 0.01
               and abs(e["start_mm"][2] - e["end_mm"][2]) < 0.01 and abs(e["start_mm"][0] - e["end_mm"][0]) > 1), None)
    if ex:
        call(linear_pattern, {"selection": {"features": ["Hole1"]}, "direction1_selection": {"edges": [ex["index"]]},
                              "count1": 3, "spacing1_mm": 20, "name": "LPat1"})
    done("PlateH", t)
    # SlotPlate
    t = newdoc("part"); sketch_rect("front", -40, -20, 40, 20, "S"); call(boss_extrude, {"sketch_name": "S", "depth_mm": 10, "name": "Sp"})
    call(create_sketch, {"plane": "front", "name": "SS"}); call(draw_slot, {"x1_mm": -15, "y1_mm": 0, "x2_mm": 15, "y2_mm": 0, "width_mm": 10}); call(close_sketch)
    call(cut_extrude, {"sketch_name": "SS", "end_condition": "through_all", "name": "SlotCut"}); done("SlotPlate", t)
    log("C1-0 fixture parts saved", all(ok.values()) and len(ok) == 8, str({k: (PATH[k].stat().st_size if PATH[k].exists() else None) for k in ok}))
    return all(ok.values())


def fidx(part, normal, axis=2, coord=None):
    f = pick_face(normal, coord, axis, fs=PF[part])
    return f["index"] if f else None


def cyl(part, which="outer"):
    """Index of a cylindrical face: 'outer' = largest area, 'inner' = smallest."""
    cs = sorted((f for f in PF[part] if f.get("surface_type") == "cylinder"), key=lambda f: f.get("area_mm2", 0))
    return (cs[-1] if which == "outer" else cs[0])["index"] if cs else None


def line_edge(part, axis):
    """First straight edge of a part parallel to the given axis (0/1/2)."""
    for e in PE[part]:
        if e.get("curve_type") != "line":
            continue
        d = [abs(a - b) for a, b in zip(e["start_mm"], e["end_mm"])]
        if d[axis] > 1 and all(d[i] < 0.01 for i in range(3) if i != axis):
            return e["index"]
    return None


def E(comp, part, face=None, edge=None, mark=0, role=None, plane=None):
    spec = {"component": comp}
    if face is not None:
        spec["face"] = face
    if edge is not None:
        spec["edge"] = edge
    if plane is not None:
        spec["plane"] = plane
    if mark:
        spec["mark"] = mark
    if role:
        spec["role"] = role
    return spec


def comps(top=False):
    return {c["name"]: c for c in D(call(list_components, {"top_level_only": top}))["components"]}


def mates():
    return D(call(list_mates))["mates"]


def zangle(c):
    """Rotation of a component about Z in degrees, from its column-major rotation matrix."""
    m = c["transform"]["rotation"]
    return math.degrees(math.atan2(m[1], m[0]))


def asm_with(**placements):
    """New assembly with the named parts inserted; returns (title, {key: component name})."""
    t = newdoc("assembly")
    names = {}
    for key, (part, xyz) in placements.items():
        r = call(insert_component, {"path": str(PATH[part]), "x_mm": xyz[0], "y_mm": xyz[1], "z_mm": xyz[2]})
        names[key] = D(r).get("component")
    return t, names


def try_probe(module, const, candidates, run):
    """Run `run()` once per candidate value of module.const until it returns ok; log which value worked."""
    original = getattr(module, const)
    for cand in candidates:
        setattr(module, const, cand)
        ok, detail = run()
        if ok:
            log(f"probe {const}={cand}", True, detail)
            return True
        log(f"probe {const}={cand}", False, detail, fence=True)
    setattr(module, const, original)
    return False


def mate_ok(r, type_code):
    d = D(r)
    return r["ok"] and d.get("built_type") == type_code


# ---------------------------------------------------------------- 1.1 limit mates
def stage_limit():
    t, n = asm_with(P=("Plate", (0, 0, 0)), P2=("Plate", (0, 0, 40)), K=("Block", (0, 0, 40)))
    call(set_component_fixed, {"component_names": [n["P"]], "fixed": True})
    P, P2, K = n["P"], n["P2"], n["K"]
    r = call(add_mate, {"mate_type": "coincident", "alignment": "anti_aligned",
                        "entities": [E(K, "Block", fidx("Block", (0, 0, -1), 2, 0)), E(P, "Plate", fidx("Plate", (0, 0, 1), 2, 10))]})
    r = call(add_mate, {"mate_type": "limit_distance", "distance_mm": 10, "min_distance_mm": 5, "max_distance_mm": 15,
                        "alignment": "aligned",
                        "entities": [E(K, "Block", fidx("Block", (1, 0, 0), 0, 10)), E(P, "Plate", fidx("Plate", (1, 0, 0), 0, 40))]})
    bx = comps()[K]["origin_mm"][0]
    log("1.1a limit_distance alias (batch A path)", mate_ok(r, 5) and 15 - 0.05 <= bx <= 25 + 0.05,
        f"{r['message']} built={D(r).get('built_type')} x={bx} counts mates {D(r).get('mate_count_before')}->{D(r).get('mate_count_after')}")
    call(move_component, {"component": K, "x_mm": 60})
    bx2 = comps()[K]["origin_mm"][0]
    log("1.1b drag past max: stays within [15,25]", 15 - 0.05 <= bx2 <= 25 + 0.05, f"x after move={bx2}")
    call(move_component, {"component": K, "x_mm": -80})
    bx3 = comps()[K]["origin_mm"][0]
    log("1.1c drag past min: stays within [15,25]", 15 - 0.05 <= bx3 <= 25 + 0.05, f"x after move={bx3}")
    r = call(add_mate, {"mate_type": "coincident", "alignment": "aligned",
                        "entities": [E(P2, "Plate", fidx("Plate", (0, -1, 0), 1, -30)), E(P, "Plate", fidx("Plate", (0, -1, 0), 1, -30))]})
    r = call(add_mate, {"mate_type": "limit_angle", "angle_deg": 30, "min_angle_deg": 10, "max_angle_deg": 50,
                        "entities": [E(P2, "Plate", fidx("Plate", (0, 0, 1), 2, 10)), E(P, "Plate", fidx("Plate", (0, 0, 1), 2, 10))]})
    a = abs(zangle(comps()[P2]))
    ang = None
    m = comps()[P2]["transform"]["rotation"]
    ang = math.degrees(math.acos(max(-1, min(1, m[8]))))
    log("1.1d limit_angle value 30 within [10,50]", mate_ok(r, 6) and 10 - 0.1 <= min(ang, 180 - ang) <= 50 + 0.1,
        f"{r['message']} built={D(r).get('built_type')} top-normal tilt={ang:.2f} deg")
    close_own(t)


# ---------------------------------------------------------------- 1.2 gear, 1.3 rack-pinion, 1.4 screw
def two_disks():
    t, n = asm_with(SA=("Shaft", (0, 0, 0)), SB=("Shaft", (50, 0, 0)), DA=("Disk", (0, 0, 20)), DB=("Disk", (50, 0, 20)))
    call(set_component_fixed, {"component_names": [n["SA"], n["SB"]], "fixed": True})
    for s, d in (("SA", "DA"), ("SB", "DB")):
        call(add_mate, {"mate_type": "concentric", "entities": [E(n[d], "Disk", cyl("Disk", "inner")), E(n[s], "Shaft", cyl("Shaft", "inner"))]})
    return t, n


def stage_gear():
    t, n = two_disks()
    for num, den, rev in ((1, 1, False), (3, 2, False)):
        r = call(add_mate, {"mate_type": "gear", "ratio_num": num, "ratio_den": den, "reverse": rev,
                            "entities": [E(n["DA"], "Disk", cyl("Disk", "outer")), E(n["DB"], "Disk", cyl("Disk", "outer"))]})
        a0, b0 = zangle(comps()[n["DA"]]), zangle(comps()[n["DB"]])
        call(rotate_component, {"component": n["DA"], "axis": "z", "angle_deg": 90})
        a1, b1 = zangle(comps()[n["DA"]]), zangle(comps()[n["DB"]])
        db = (b1 - b0 + 180) % 360 - 180
        want = 90 * num / den * (1 if rev else -1)  # gears counter-rotate unless reversed
        log(f"1.2 gear {num}:{den} rotate A 90 -> B {want:+.1f} (or magnitude)", mate_ok(r, 10) and (near(db, want, 0.5) or near(abs(db), abs(want), 0.5)),
            f"{r['message']} built={D(r).get('built_type')} dB={db:.2f} dA={(a1 - a0):.2f} probes={D(r).get('live_probe')}", fence=True)
        if D(r).get("mate"):
            call(delete_mate, {"mate_name": D(r)["mate"]})
    close_own(t)


def stage_rack():
    t, n = asm_with(P=("Plate", (0, 0, 0)), SA=("Shaft", (0, 0, 10)), DA=("Disk", (0, 0, 20)), R=("Rack", (0, 25, 20)))
    call(set_component_fixed, {"component_names": [n["P"], n["SA"]], "fixed": True})
    call(add_mate, {"mate_type": "concentric", "entities": [E(n["DA"], "Disk", cyl("Disk", "inner")), E(n["SA"], "Shaft", cyl("Shaft", "inner"))]})
    # keep the rack on a plane parallel to the plate top so only sliding along X remains
    call(add_mate, {"mate_type": "coincident", "alignment": "anti_aligned",
                    "entities": [E(n["R"], "Rack", fidx("Rack", (0, 0, -1), 2, 0)), E(n["SA"], "Shaft", fidx("Shaft", (0, 0, 1), 2, 5))]})
    per_rev = math.pi * 30.0  # pinion pitch circle = outer cylinder r15
    r = call(add_mate, {"mate_type": "rack_pinion", "distance_per_rev_mm": per_rev,
                        "entities": [E(n["R"], "Rack", edge=line_edge("Rack", 0)), E(n["DA"], "Disk", cyl("Disk", "outer"))]})
    x0 = comps()[n["R"]]["origin_mm"][0]
    call(rotate_component, {"component": n["DA"], "axis": "z", "angle_deg": 360})
    dx = comps()[n["R"]]["origin_mm"][0] - x0
    log("1.3 rack_pinion: pinion 360 deg -> rack travel = distance_per_rev", mate_ok(r, 13) and near(abs(dx), per_rev, 0.01),
        f"{r['message']} built={D(r).get('built_type')} travel={dx:.4f} want={per_rev:.4f} probes={D(r).get('live_probe')}", fence=True)
    close_own(t)


def stage_screw():
    t, n = asm_with(SA=("Shaft", (0, 0, 0)), DA=("Disk", (0, 0, 20)))
    call(set_component_fixed, {"component_names": [n["SA"]], "fixed": True})
    call(add_mate, {"mate_type": "concentric", "entities": [E(n["DA"], "Disk", cyl("Disk", "inner")), E(n["SA"], "Shaft", cyl("Shaft", "inner"))]})
    r = call(add_mate, {"mate_type": "screw", "pitch_mm": 2.0,
                        "entities": [E(n["DA"], "Disk", cyl("Disk", "inner")), E(n["SA"], "Shaft", cyl("Shaft", "inner"))]})
    z0 = comps()[n["DA"]]["origin_mm"][2]
    call(rotate_component, {"component": n["DA"], "axis": "z", "angle_deg": 360})
    dz = comps()[n["DA"]]["origin_mm"][2] - z0
    log("1.4 screw: 360 deg -> axial travel = pitch", mate_ok(r, 17) and near(abs(dz), 2.0, 0.01),
        f"{r['message']} built={D(r).get('built_type')} dz={dz:.4f} probes={D(r).get('live_probe')}", fence=True)
    close_own(t)


# ---------------------------------------------------------------- 1.5 cam, 1.6 hinge, 1.7 slot, 1.8 path
def stage_cam():
    t, n = two_disks()
    r = call(add_mate, {"mate_type": "cam", "entities": [
        E(n["DA"], "Disk", cyl("Disk", "outer"), role="cam"), E(n["DB"], "Disk", cyl("Disk", "outer"), role="follower")]})
    ms = [m for m in mates() if m.get("mate_type") == "type_9"]
    log("1.5 cam mate created and listed as type 9", mate_ok(r, 9) and bool(ms),
        f"{r['message']} built={D(r).get('built_type')} listed={[m['name'] for m in ms]} probes={D(r).get('live_probe')}", fence=True)
    close_own(t)


def stage_hinge():
    t, n = asm_with(SA=("Shaft", (0, 0, 0)), DA=("Disk", (0, 0, 20)))
    call(set_component_fixed, {"component_names": [n["SA"]], "fixed": True})
    r = call(add_mate, {"mate_type": "hinge", "entities": [
        E(n["DA"], "Disk", cyl("Disk", "inner"), role="concentric"), E(n["SA"], "Shaft", cyl("Shaft", "inner"), role="concentric"),
        E(n["DA"], "Disk", fidx("Disk", (0, 0, -1), 2, 0), role="coincident"), E(n["SA"], "Shaft", fidx("Shaft", (0, 0, 1), 2, 5), role="coincident")]})
    z0 = comps()[n["DA"]]["origin_mm"]
    call(rotate_component, {"component": n["DA"], "axis": "z", "angle_deg": 45})
    z1 = comps()[n["DA"]]["origin_mm"]
    call(move_component, {"component": n["DA"], "z_mm": 15})
    z2 = comps()[n["DA"]]["origin_mm"]
    log("1.6 hinge: only rotation remains (rotates, axial move is pulled back)", mate_ok(r, 22) and near(z2[2], z0[2], 0.05),
        f"{r['message']} built={D(r).get('built_type')} origin {z0}->{z1}->{z2} probes={D(r).get('live_probe')}", fence=True)
    close_own(t)


def stage_slot():
    t, n = asm_with(S=("SlotPlate", (0, 0, 0)), N=("Pin", (0, 0, 10)))
    call(set_component_fixed, {"component_names": [n["S"]], "fixed": True})
    slot_face = cyl("SlotPlate", "inner")
    for constraint, extra, want_x in (("center", {}, 0.0), ("free", {}, None), ("distance", {"distance_mm": 5}, None), ("percent", {"slot_percent": 25}, None)):
        r = call(add_mate, {"mate_type": "slot", "slot_constraint": constraint, **extra,
                            "entities": [E(n["N"], "Pin", cyl("Pin", "outer")), E(n["S"], "SlotPlate", slot_face)]})
        x = comps()[n["N"]]["origin_mm"][0]
        ok = mate_ok(r, 21) and (want_x is None or near(x, want_x, 0.05))
        log(f"1.7 slot constraint={constraint}: pin x={x:.3f} (center expects 0)", ok,
            f"{r['message']} built={D(r).get('built_type')} probes={D(r).get('live_probe')}", fence=True)
        if D(r).get("mate"):
            call(delete_mate, {"mate_name": D(r)["mate"]})
    close_own(t)


def stage_path():
    t, n = asm_with(P=("Plate", (0, 0, 0)), K=("Block", (0, 0, 40)))
    call(set_component_fixed, {"component_names": [n["P"]], "fixed": True})
    r = call(add_mate, {"mate_type": "path", "entities": [
        E(n["K"], "Block", edge=line_edge("Block", 0), role="point"), E(n["P"], "Plate", edge=line_edge("Plate", 0), role="path")]})
    log("1.8 path mate (expected fence: needs CreateMateData)", mate_ok(r, 15), f"{r['message']} built={D(r).get('built_type')}", fence=True)
    close_own(t)


# ---------------------------------------------------------------- 1.9 symmetric / width
def stage_sym():
    t, n = asm_with(P=("Plate", (0, 0, 0)), A=("Block", (50, 0, 10)), B=("Block", (-20, 0, 10)))
    call(set_component_fixed, {"component_names": [n["P"], n["A"]], "fixed": True})
    r = call(add_mate, {"mate_type": "symmetric", "entities": [
        E(n["P"], "Plate", plane="Right Plane", role="symmetry_plane"),
        E(n["A"], "Block", fidx("Block", (-1, 0, 0), 0, -10), role="entity"), E(n["B"], "Block", fidx("Block", (1, 0, 0), 0, 10), role="entity")]})
    ax, bx = comps()[n["A"]]["origin_mm"][0], comps()[n["B"]]["origin_mm"][0]
    log("1.9a symmetric about plate Right Plane: offsets equal", mate_ok(r, 8) and near(ax, -bx, 0.01),
        f"{r['message']} built={D(r).get('built_type')} A.x={ax} B.x={bx} probes={D(r).get('live_probe')}", fence=True)
    close_own(t)


def stage_width():
    t, n = asm_with(P=("Plate", (0, 0, 0)), K=("Block", (0, 0, 10)))
    call(set_component_fixed, {"component_names": [n["P"]], "fixed": True})
    call(add_mate, {"mate_type": "coincident", "alignment": "anti_aligned",
                    "entities": [E(n["K"], "Block", fidx("Block", (0, 0, -1), 2, 0)), E(n["P"], "Plate", fidx("Plate", (0, 0, 1), 2, 10))]})
    ents = [E(n["P"], "Plate", fidx("Plate", (-1, 0, 0), 0, -40), mark=1), E(n["P"], "Plate", fidx("Plate", (1, 0, 0), 0, 40), mark=1),
            E(n["K"], "Block", fidx("Block", (-1, 0, 0), 0, -10), mark=2), E(n["K"], "Block", fidx("Block", (1, 0, 0), 0, 10), mark=2)]
    for pct in (25, 75):
        r = call(add_mate, {"mate_type": "width", "width_option": "percent", "width_percent": pct, "entities": ents})
        x = comps()[n["K"]]["origin_mm"][0]
        # plate faces at +-40 (gap 80), tab 20 wide: tab centre travels from -30 to +30
        h_travel = -30 + pct / 100 * 60
        h_gap = -40 + pct / 100 * 80
        log(f"1.9b width percent={pct}: tab x={x:.3f} (travel-based {h_travel:.2f} / gap-based {h_gap:.2f})",
            mate_ok(r, 11) and (near(x, h_travel, 0.05) or near(x, h_gap, 0.05)),
            f"{r['message']} built={D(r).get('built_type')} probes={D(r).get('live_probe')}", fence=True)
        if D(r).get("mate"):
            call(delete_mate, {"mate_name": D(r)["mate"]})
    close_own(t)


# ---------------------------------------------------------------- 1.10 mate reference
def stage_materef():
    t = newdoc("part")
    sketch_rect("front", -10, -10, 10, 10, "S")
    call(boss_extrude, {"sketch_name": "S", "depth_mm": 10, "name": "Bl"})
    top = pick_face((0, 0, 1), 10)
    r = call(add_mate_reference, {"name": "MRef", "references": [{"face": top["index"], "type": "coincident", "alignment": "anti_aligned"}]})
    feats = D(call(list_features))["features"]
    mrefs = [f for f in feats if "MateReference" in f["type"] or "PosGroupFolder" in f["type"]]
    d = D(r)
    log("1.10 add_mate_reference: MateReference feature appears in the tree", r["ok"] and bool(mrefs) and d.get("mate_references_after", 0) > d.get("mate_references_before", 0),
        f"{r['message']} {json.dumps(d, default=str)[:260]} tree={[f['name'] for f in feats][-3:]}", fence=True)
    r2 = call(add_mate_reference, {"references": [{"face": 99999}]})
    log("1.10b bad index refused cleanly", not r2["ok"], r2["message"][:90])
    close_own(t)


# ---------------------------------------------------------------- 1.11 / 1.12 patterns
def stage_linear():
    t, n = asm_with(P=("Plate", (0, 0, 0)), K=("Block", (-30, 0, 10)))
    call(set_component_fixed, {"component_names": [n["P"], n["K"]], "fixed": True})
    n0 = len(comps(top=True))
    r = call(linear_component_pattern, {"components": [n["K"]], "direction": E(n["P"], "Plate", edge=line_edge("Plate", 0)),
                                        "spacing_mm": 30, "count": 3, "name": "LCP1"})
    d = D(r)
    xs = sorted(c["origin_mm"][0] for c in comps(top=True).values() if c["name"].startswith(n["K"].split("-")[0]))
    gaps = [round(b - a, 3) for a, b in zip(xs, xs[1:])]
    log("1.11 linear_component_pattern 3 x 30 mm: count and spacing", r["ok"] and len(comps(top=True)) == n0 + 2 and gaps and all(near(g, 30, 0.01) for g in gaps),
        f"{r['message']} xs={xs} gaps={gaps} feature={d.get('feature')}:{d.get('feature_type')} probes={d.get('live_probe')}", fence=True)
    close_own(t)


def stage_circular():
    t, n = asm_with(S=("Shaft", (0, 0, 0)), K=("Block", (40, 0, 0)))
    call(set_component_fixed, {"component_names": [n["S"]], "fixed": True})
    r = call(circular_component_pattern, {"components": [n["K"]], "axis": E(n["S"], "Shaft", cyl("Shaft", "outer")),
                                          "count": 4, "angle_deg": 360, "equal_spacing": True, "name": "CCP1"})
    d = D(r)
    pts = [c["origin_mm"] for c in comps(top=True).values() if c["name"].startswith(n["K"].split("-")[0])]
    radii = [round(math.hypot(p[0], p[1]), 3) for p in pts]
    angs = sorted(round(math.degrees(math.atan2(p[1], p[0])) % 360, 2) for p in pts)
    log("1.12 circular_component_pattern 4 over 360: radius constant, 90 deg steps", r["ok"] and len(pts) == 4 and all(near(x, 40, 0.05) for x in radii)
        and all(near((b - a), 90, 0.05) for a, b in zip(angs, angs[1:])),
        f"{r['message']} radii={radii} angles={angs} probes={d.get('live_probe')}", fence=True)
    close_own(t)


def stage_derived():
    t, n = asm_with(P=("PlateH", (0, 0, 0)), N=("Pin", (-20, 0, 10)))
    call(set_component_fixed, {"component_names": [n["P"]], "fixed": True})
    n0 = len(comps(top=True))
    hole = cyl("PlateH", "inner")
    call(add_mate, {"mate_type": "concentric", "entities": [E(n["N"], "Pin", cyl("Pin", "outer")), E(n["P"], "PlateH", hole)]})
    r = call(pattern_driven_component_pattern, {"components": [n["N"]], "driving_feature": "LPat1", "driving_component": n["P"],
                                                "expected_new_components": 2})
    log("1.13 pattern_driven_component_pattern follows the 3-hole pattern", r["ok"] and len(comps(top=True)) == n0 + 2,
        f"{r['message']} top-level {n0}->{len(comps(top=True))} probes={D(r).get('live_probe')}", fence=True)
    close_own(t)


# ---------------------------------------------------------------- 1.14 mirror
def stage_mirror():
    t, n = asm_with(P=("Plate", (0, 0, 0)), K=("Block", (30, 10, 10)))
    call(set_component_fixed, {"component_names": [n["P"], n["K"]], "fixed": True})
    before = comps(top=True)
    r = call(mirror_components, {"components": [n["K"]], "plane": "right"})
    after = comps(top=True)
    new = [c for k, c in after.items() if k not in before]
    src_x = before[n["K"]]["origin_mm"][0]
    log("1.14 mirror_components across Right Plane: +1 component, x = -x", r["ok"] and len(new) == 1 and near(new[0]["origin_mm"][0], -src_x, 0.05),
        f"{r['message']} new={[(c['name'], c['origin_mm']) for c in new]} src x={src_x} probes={D(r).get('live_probe')}", fence=True)
    close_own(t)


# ---------------------------------------------------------------- 1.15 sub-assembly
def stage_subasm():
    for mode in ("virtual", "file"):
        t, n = asm_with(P=("Plate", (0, 0, 0)), A=("Block", (0, 0, 40)), B=("Block", (50, 0, 40)))
        call(set_component_fixed, {"component_names": [n["P"]], "fixed": True})
        call(add_mate, {"mate_type": "coincident", "alignment": "anti_aligned",
                        "entities": [E(n["A"], "Block", fidx("Block", (0, 0, -1), 2, 0)), E(n["P"], "Plate", fidx("Plate", (0, 0, 1), 2, 10))]})
        call(add_mate, {"mate_type": "coincident", "alignment": "anti_aligned",
                        "entities": [E(n["B"], "Block", fidx("Block", (0, 0, -1), 2, 0)), E(n["P"], "Plate", fidx("Plate", (0, 0, 1), 2, 10))]})
        top0, mates0 = len(comps(top=True)), len(mates())
        name = f"Grp_{mode}"
        if mode == "file":
            (OUT / f"{name}.SLDASM").unlink(missing_ok=True)
        r = call(create_subassembly, {"components": [n["A"], n["B"]], "name": name, "mode": mode})
        d = D(r)
        top1 = len(comps(top=True))
        log(f"1.15 create_subassembly mode={mode}: holds 2 comps, top level {top0}->{top0 - 1}, mates intact",
            r["ok"] and top1 == top0 - 1 and len(d.get("children", [])) >= 2 and len(mates()) >= mates0 - 2,
            f"{r['message']} top {top0}->{top1} children={d.get('children')} mates {mates0}->{len(mates())} path={d.get('path')}", fence=True)
        close_own(t)


STAGES = {"limit": stage_limit, "gear": stage_gear, "rack": stage_rack, "screw": stage_screw, "cam": stage_cam, "hinge": stage_hinge,
          "slot": stage_slot, "path": stage_path, "sym": stage_sym, "width": stage_width, "materef": stage_materef,
          "linear": stage_linear, "circular": stage_circular, "derived": stage_derived, "mirror": stage_mirror, "subasm": stage_subasm}


def finish(keep_base):
    for x in docs():
        if x["title"] not in keep_base:
            call(close_document, {"title": x["title"], "force": True})


if __name__ == "__main__":
    which = sys.argv[1:] or list(STAGES)
    base = [d["title"] for d in docs()]
    print("BASELINE", base, flush=True)
    try:
        if build_parts():
            for w in which:
                STAGES[w]()
        else:
            log("fixture build", False, "one or more parts failed to save; aborting (is SW_MCP_OUTPUT_ROOT the sandbox?)")
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        log("EXCEPTION", False, repr(exc))
    finally:
        finish(base)
        now = [d["title"] for d in docs()]
        log("final docs == baseline", now == base, f"{now} vs {base}")
        with open(OUT / "live_log.txt", "a", encoding="utf-8") as fh:
            fh.write("\n".join(LOG) + "\n")
