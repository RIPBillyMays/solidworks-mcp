# Modified for SOLIDWORKS 2017 support (fork).
"""LIVE verification of the Phase 5 sketch fixes (#7, #11, #12, #13, #14, #15).

Run with SOLIDWORKS 2017 running and NO document open, and SW_MCP_OUTPUT_ROOT set to
<repo>\\sandbox\\fixes_probes.  Calls server.call_tool so dispatch and stamping run.
Creates scratch parts only; force-closes everything it made.  Never saves.
"""
from __future__ import annotations

import asyncio
import json
import math
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from solidworks_mcp import server  # noqa: E402
from solidworks_mcp.sw_core import (  # noqa: E402
    active_document, flag_methods, open_sketch_name, set_open_sketch_hint, sketch_point_objects, value,
)

OUT = ROOT / "sandbox" / "fixes_probes"
RESULTS: list[dict] = []
CREATED: list[str] = []


def call(name: str, args: dict | None = None) -> dict:
    content = asyncio.run(server.call_tool(name, args or {}))
    return json.loads(content[0].text)


def d(p: dict) -> dict:
    return p.get("data", {}) or {}


def record(finding: str, check: str, passed: bool, evidence: str) -> None:
    RESULTS.append({"finding": finding, "check": check, "result": "PASS" if passed else "FAIL", "evidence": evidence})
    print(f"[{'PASS' if passed else 'FAIL'}] {finding} | {check}: {evidence}", flush=True)


def info(msg: str) -> None:
    print("  .", msg, flush=True)


def new_part() -> str:
    p = call("create_new_document", {"kind": "part"})
    if not p.get("ok"):
        raise RuntimeError(f"create failed {p}")
    title = d(p)["document"]["title"]
    CREATED.append(title)
    return title


def close_part(title: str) -> None:
    call("close_document", {"title": title, "force": True})
    if title in CREATED:
        CREATED.remove(title)


def near(a: float, b: float, tol: float = 0.01) -> bool:
    return abs(a - b) <= tol


def vnear(v, w, tol=1e-3) -> bool:
    return v is not None and len(v) == len(w) and all(abs(a - b) <= tol for a, b in zip(v, w))


def segs(name: str | None = None) -> tuple[str, list[dict]]:
    p = call("list_sketch_segments", {"sketch_name": name} if name else {})
    return d(p).get("sketch", ""), d(p).get("segments", [])


def vol() -> float:
    p = call("get_mass_properties", {})
    return float(d(p).get("volume_mm3", 0.0)) if p.get("ok") else 0.0


def relation_info() -> tuple[int, int]:
    """(total relation count, Fixed relation count) of the open sketch."""
    _, doc = active_document()
    sketch = doc.SketchManager.ActiveSketch
    rm = value(sketch, "RelationManager")
    flag_methods(rm, "GetRelationsCount", "GetRelations")
    total = int(rm.GetRelationsCount(0))
    fixed = 0
    try:
        rels = rm.GetRelations(0)
        for r in (rels or []):
            try:
                if int(flag_methods(r, "GetRelationType").GetRelationType()) == 17:
                    fixed += 1
            except Exception:
                pass
    except Exception as exc:
        info(f"GetRelations failed {exc}")
    return total, fixed


def point_index(x_mm: float, y_mm: float) -> int | None:
    _, doc = active_document()
    for i, p in enumerate(sketch_point_objects(doc)):
        try:
            if abs(p.X * 1000 - x_mm) < 1e-3 and abs(p.Y * 1000 - y_mm) < 1e-3:
                return i
        except Exception:
            pass
    return None


# ---------------------------------------------------------------- #7
def f7() -> None:
    F = "#7"
    t = new_part()
    for nm, kind in (("A1", "rect"), ("A2", "circle"), ("A3", "line")):
        call("create_sketch", {"plane": "front", "name": nm})
        if kind == "rect":
            call("draw_rectangle", {"x1_mm": 0, "y1_mm": 0, "x2_mm": 20, "y2_mm": 20})
        elif kind == "circle":
            call("draw_circle", {"x_mm": 50, "y_mm": 50, "radius_mm": 5})
        else:
            call("draw_line", {"x1_mm": 80, "y1_mm": 0, "x2_mm": 100, "y2_mm": 10})
        c = call("close_sketch", {})
        info(f"{nm} closed -> {d(c).get('sketch')}")
    expected_counts = {"A1": 4, "A2": 1, "A3": 1}
    for target in ("A1", "A2", "A1", "A3"):
        e = call("edit_sketch", {"sketch_name": target})
        n, sg = segs()
        # identity path alone: wipe the hint, ask the core directly
        set_open_sketch_hint("")
        try:
            _, doc = active_document()
            ident, _ = open_sketch_name(doc)
        except Exception as exc:
            ident = f"ERR {exc}"
        set_open_sketch_hint(target)
        c = call("close_sketch", {})
        record(F, f"edit_sketch {target}: list_sketch_segments, hint-free identity and close_sketch all name it",
               bool(e.get("ok")) and n == target and len(sg) == expected_counts[target]
               and ident == target and d(c).get("sketch") == target,
               f"list={n} ({len(sg)} segs, want {expected_counts[target]}) identity(no hint)={ident} close={d(c).get('sketch')}")
    close_part(t)


# ---------------------------------------------------------------- #11 / #12
def f11() -> None:
    F = "#11"
    t = new_part()
    call("create_sketch", {"plane": "front", "name": "R"})
    call("draw_rectangle", {"x1_mm": 0, "y1_mm": 0, "x2_mm": 40, "y2_mm": 20})
    _, s0 = segs()
    r = call("sketch_fillet", {"radius_mm": 3, "corners": [{"x": 40, "y": 20}, {"x": 0, "y": 0}]})
    n, sg = segs()
    arcs = [s for s in sg if s["type"] == "arc"]
    lines = [s for s in sg if s["type"] == "line"]
    centres = sorted([tuple(a.get("center_mm", [])[:2]) for a in arcs])
    ok_geom = (len(arcs) == 2 and all(near(a.get("radius_mm", 0), 3, 0.001) for a in arcs)
               and len(centres) == 2 and vnear(list(centres[0]), [3, 3], 0.01) and vnear(list(centres[1]), [37, 17], 0.01))
    record(F, "rectangle 40x20, fillet 2 corners R3 by coordinate: 2 arcs R3 at (3,3),(37,17); 6 segments",
           bool(r.get("ok")) and len(s0) == 4 and len(sg) == 6 and ok_geom,
           f"ok={r.get('ok')} segs {len(s0)}->{len(sg)} arcs={len(arcs)} lines={len(lines)} centres={centres} "
           f"corners_done={d(r).get('filleted_corners_mm')} msg={str(r.get('message'))[:80]}")
    r2 = call("sketch_fillet", {"radius_mm": 3, "corners": [{"x": 40, "y": 20}]})
    n2, sg2 = segs()
    record(F, "repeat on the already-filleted corner (40,20) rejected, segment count unchanged",
           r2.get("ok") is False and len(sg2) == 6,
           f"ok={r2.get('ok')} segs={len(sg2)} msg={str(r2.get('message'))[:140]}")
    r3 = call("sketch_fillet", {"radius_mm": 3, "corners": [{"x": 5, "y": 5}]})
    record(F, "corner with no segment endpoint (5,5) rejected",
           r3.get("ok") is False and len(segs()[1]) == 6, f"ok={r3.get('ok')} msg={str(r3.get('message'))[:120]}")
    call("close_sketch", {})
    b = call("boss_extrude", {"sketch_name": "R", "depth_mm": 5})
    exp = (800 - 2 * 9 * (1 - math.pi / 4)) * 5
    record(F, "extruding the filleted sketch gives the measured volume",
           bool(b.get("ok")) and near(vol(), exp, 0.1), f"vol={vol():.3f} expected={exp:.3f}")
    close_part(t)


def f12() -> None:
    F = "#12"
    t = new_part()
    call("create_sketch", {"plane": "front", "name": "O"})
    call("draw_rectangle", {"x1_mm": 0, "y1_mm": 0, "x2_mm": 20, "y2_mm": 20})
    _, s0 = segs()
    r = call("sketch_offset", {"distance_mm": 2, "selection": {"sketch_segments": [0]}, "chain": True,
                               "construct_original": True})
    n, sg = segs()
    orig = [s for s in sg if near(s.get("length_mm", 0), 20, 0.01)]
    other = [s for s in sg if not near(s.get("length_mm", 0), 20, 0.01)]
    record(F, "offset rect by 2 with construct_original: 4 sources construction, 4 offset lines not",
           bool(r.get("ok")) and len(s0) == 4 and len(sg) == 8 and len(orig) == 4 and all(s["construction"] for s in orig)
           and len(other) == 4 and not any(s["construction"] for s in other),
           f"ok={r.get('ok')} segs {len(s0)}->{len(sg)} flagged={d(r).get('construction_flagged')} "
           f"orig(len20) construction={[s['construction'] for s in orig]} offset lens={[s.get('length_mm') for s in other]} "
           f"offset construction={[s['construction'] for s in other]} msg={str(r.get('message'))[:80]}")
    call("close_sketch", {})
    close_part(t)


# ---------------------------------------------------------------- #13
def f13() -> None:
    F = "#13"
    t = new_part()
    call("create_sketch", {"plane": "front", "name": "D"})
    call("draw_line", {"x1_mm": 0, "y1_mm": 0, "x2_mm": 30, "y2_mm": 10})   # seg 0: anchor=start
    call("draw_line", {"x1_mm": 0, "y1_mm": 50, "x2_mm": 30, "y2_mm": 60})  # seg 1: anchor=end
    call("draw_line", {"x1_mm": 0, "y1_mm": 100, "x2_mm": 30, "y2_mm": 110})  # seg 2: user Fixed on start, anchor=start
    call("draw_line", {"x1_mm": 0, "y1_mm": 150, "x2_mm": 30, "y2_mm": 150})  # seg 3: gives the sketch a pre-existing relation
    hr = call("add_relation", {"relation": "horizontal", "selection": {"sketch_segments": [3]}})
    base_total, base_fixed = relation_info()
    info(f"baseline relations total={base_total} fixed={base_fixed} horizontal ok={hr.get('ok')}")
    record(F, "R2 setup: sketch already has relations before the first anchored dimension", base_total >= 1, f"total={base_total}")

    # NOTE: a plain driving dimension on a line adds one relation of its own (GetRelationType 1) to
    # GetRelationsCount, so the total is expected to rise by 1; the temp Fixed (type 17) must not remain.
    r = call("add_dimension", {"selection": {"sketch_segments": [0]}, "value_mm": 50, "anchor": "start"})
    _, sg = segs()
    s, e = sg[0]["start_mm"], sg[0]["end_mm"]
    tot, fx = relation_info()
    record(F, "anchor=start geometry: start stays (0,0), end moves, length 50",
           bool(r.get("ok")) and vnear(s[:2], [0, 0], 0.005) and near(sg[0]["length_mm"], 50, 0.01)
           and not vnear(e[:2], [30, 10], 0.01),
           f"ok={r.get('ok')} start={s[:2]} end={e[:2]} len={sg[0]['length_mm']}")
    record(F, "anchor=start: no temporary Fixed (type 17) relation remains",
           fx == base_fixed, f"relations total {base_total}->{tot} (dimension adds its own type-1 relation) fixed {base_fixed}->{fx}")
    record(F, "anchor=start: result reports anchor_relation_removed true and no warning in message",
           d(r).get("anchor_relation_removed") is True and "Warning" not in str(r.get("message")),
           f"removed={d(r).get('anchor_relation_removed')} ambiguous={d(r).get('anchor_relation_ambiguous')} msg={str(r.get('message'))[:200]}")

    base_total, base_fixed = relation_info()
    r = call("add_dimension", {"selection": {"sketch_segments": [1]}, "value_mm": 50, "anchor": "end"})
    _, sg = segs()
    s, e = sg[1]["start_mm"], sg[1]["end_mm"]
    tot, fx = relation_info()
    record(F, "anchor=end geometry (2nd anchored call in the sketch): end stays (30,60), start moves, length 50",
           bool(r.get("ok")) and vnear(e[:2], [30, 60], 0.005) and near(sg[1]["length_mm"], 50, 0.01)
           and not vnear(s[:2], [0, 50], 0.01),
           f"ok={r.get('ok')} start={s[:2]} end={e[:2]} len={sg[1]['length_mm']}")
    record(F, "anchor=end: no temporary Fixed (type 17) relation remains",
           fx == base_fixed, f"relations total {base_total}->{tot} fixed {base_fixed}->{fx} removed={d(r).get('anchor_relation_removed')} "
           f"ambiguous={d(r).get('anchor_relation_ambiguous')}")

    # user Fixed on the start point of segment 2, then anchor=start on the same point
    pi = point_index(0, 100)
    info(f"point index of (0,100) = {pi}")
    if pi is None:
        record(F, "user Fixed relation survives", False, "could not locate sketch point (0,100)")
    else:
        ur = call("add_relation", {"relation": "fixed", "selection": {"sketch_points": [pi]}})
        base_total, base_fixed = relation_info()
        info(f"user fixed ok={ur.get('ok')} relations total={base_total} fixed={base_fixed}")
        r = call("add_dimension", {"selection": {"sketch_segments": [2]}, "value_mm": 40, "anchor": "start"})
        _, sg = segs()
        s, e = sg[2]["start_mm"], sg[2]["end_mm"]
        tot, fx = relation_info()
        record(F, "pre-existing user Fixed on the anchor point survives (Fixed count unchanged; total +1 for the dimension's own relation)",
               bool(ur.get("ok")) and base_fixed >= 1 and fx == base_fixed and tot == base_total + 1,
               f"relations {base_total}->{tot} (+1 = the dimension's own type-1 relation) fixed {base_fixed}->{fx}")
        record(F, "anchor=start on an already-Fixed point still applies the dimension (length 40, start kept), anchor_already_fixed true",
               bool(r.get("ok")) and vnear(s[:2], [0, 100], 0.005) and near(sg[2]["length_mm"], 40, 0.01)
               and d(r).get("anchor_already_fixed") is True and "Warning" not in str(r.get("message")),
               f"dim ok={r.get('ok')} start={s[:2]} len={sg[2]['length_mm']} removed={d(r).get('anchor_relation_removed')} "
               f"msg={str(r.get('message'))[:160]}")
    call("close_sketch", {})
    close_part(t)


# ---------------------------------------------------------------- #14
def seg_count() -> int:
    return len(segs()[1])


def f14() -> None:
    F = "#14"
    t = new_part()
    call("create_sketch", {"plane": "front", "name": "U"})
    call("draw_line", {"x1_mm": 0, "y1_mm": 0, "x2_mm": 10, "y2_mm": 0})      # 0
    call("draw_line", {"x1_mm": 0, "y1_mm": 5, "x2_mm": 10, "y2_mm": 5})      # 1
    s0 = seg_count()
    u = call("undo", {})
    s1 = seg_count()
    txt = json.dumps(u)
    record(F, "R2 undo inside a sketch: result carries the delete_sketch_segment hint (and does not claim removal)",
           "delete_sketch_segment" in txt and s1 == s0,
           f"ok={u.get('ok')} segs {s0}->{s1} msg={str(u.get('message'))[:220]}")

    # delete by index
    r = call("delete_sketch_segment", {"index": 1})
    record(F, "R2 delete_sketch_segment by index 1: ok, count 2->1",
           bool(r.get("ok")) and seg_count() == 1 and d(r).get("segments_before") == 2 and d(r).get("segments_after") == 1,
           f"ok={r.get('ok')} before={d(r).get('segments_before')} after={d(r).get('segments_after')} deleted={d(r).get('deleted')} msg={str(r.get('message'))[:100]}")
    # out of range
    r = call("delete_sketch_segment", {"index": 9})
    record(F, "R2 delete_sketch_segment out-of-range index refused, count unchanged",
           r.get("ok") is False and seg_count() == 1, f"ok={r.get('ok')} msg={str(r.get('message'))[:100]}")
    # neither / both
    r = call("delete_sketch_segment", {})
    r2 = call("delete_sketch_segment", {"index": 0, "point": {"x_mm": 5, "y_mm": 0}})
    record(F, "R2 delete_sketch_segment needs exactly one of index/point",
           r.get("ok") is False and r2.get("ok") is False and seg_count() == 1, f"{r.get('message')!r} / {r2.get('message')!r}")

    # by point on a line: add two more lines, delete the remaining one by point
    call("draw_line", {"x1_mm": 0, "y1_mm": 30, "x2_mm": 20, "y2_mm": 30})
    n = seg_count()
    r = call("delete_sketch_segment", {"point": {"x_mm": 10, "y_mm": 30.1}})
    _, sg = segs()
    gone = not any(abs(x.get("start_mm", [0, 0])[1] - 30) < 0.01 and abs(x.get("end_mm", [0, 0])[1] - 30) < 0.01 for x in sg)
    record(F, "R2 delete by point on a line (mid, 0.1 mm off): that line gone, count -1",
           bool(r.get("ok")) and seg_count() == n - 1 and gone,
           f"ok={r.get('ok')} count {n}->{seg_count()} line y=30 gone={gone} msg={str(r.get('message'))[:100]}")
    # point not near anything
    r = call("delete_sketch_segment", {"point": {"x_mm": 500, "y_mm": 500}})
    record(F, "R2 delete by point far from everything refused", r.get("ok") is False and seg_count() == n - 1,
           f"ok={r.get('ok')} msg={str(r.get('message'))[:100]}")

    # CCW arc: centre (100,0) radius 10, from (110,0) to (100,10)  (90 deg CCW; midpoint at 45 deg)
    c45 = 10 * math.cos(math.radians(45))
    a1 = call("draw_arc", {"center_x_mm": 100, "center_y_mm": 0, "start_x_mm": 110, "start_y_mm": 0,
                           "end_x_mm": 100, "end_y_mm": 10, "direction": 1})
    n = seg_count()
    r = call("delete_sketch_segment", {"point": {"x_mm": 100 + c45, "y_mm": c45}})
    record(F, "R2 delete by point on the CCW arc midpoint: ok, count -1",
           bool(a1.get("ok")) and bool(r.get("ok")) and seg_count() == n - 1,
           f"arc ok={a1.get('ok')} del ok={r.get('ok')} count {n}->{seg_count()} deleted={d(r).get('deleted')} msg={str(r.get('message'))[:120]}")

    # CW arc (direction -1): centre (200,0) radius 10, from (210,0) to (200,-10): 90 deg clockwise, midpoint at -45 deg
    a2 = call("draw_arc", {"center_x_mm": 200, "center_y_mm": 0, "start_x_mm": 210, "start_y_mm": 0,
                           "end_x_mm": 200, "end_y_mm": -10, "direction": -1})
    n = seg_count()
    _, sg = segs()
    info(f"CW arc created ok={a2.get('ok')} segs={[ (x['type'], x.get('start_mm'), x.get('end_mm')) for x in sg if x['type']=='arc']}")
    # the OPPOSITE 270-degree side of the circle (point at +135 deg) is NOT on the arc; must not delete
    r_off = call("delete_sketch_segment", {"point": {"x_mm": 200 - c45, "y_mm": c45}})
    record(F, "R2 CW arc: a point on the circle but NOT on the arc (135 deg) is refused",
           r_off.get("ok") is False and seg_count() == n,
           f"ok={r_off.get('ok')} count={seg_count()} msg={str(r_off.get('message'))[:120]}")
    r = call("delete_sketch_segment", {"point": {"x_mm": 200 + c45, "y_mm": -c45}})
    record(F, "R2 delete by point on the CW (direction=-1) arc midpoint: ok, count -1",
           bool(a2.get("ok")) and bool(r.get("ok")) and seg_count() == n - 1,
           f"arc ok={a2.get('ok')} del ok={r.get('ok')} count {n}->{seg_count()} deleted={d(r).get('deleted')} msg={str(r.get('message'))[:120]}")

    # ambiguous: two lines meeting at a corner
    call("draw_line", {"x1_mm": 300, "y1_mm": 0, "x2_mm": 320, "y2_mm": 0})
    call("draw_line", {"x1_mm": 320, "y1_mm": 0, "x2_mm": 320, "y2_mm": 20})
    n = seg_count()
    r = call("delete_sketch_segment", {"point": {"x_mm": 320, "y_mm": 0}})
    record(F, "R2 ambiguous point at a shared corner refused with candidates, nothing deleted",
           r.get("ok") is False and seg_count() == n and len(d(r).get("candidates", [])) == 2,
           f"ok={r.get('ok')} candidates={d(r).get('candidates')} count={seg_count()} msg={str(r.get('message'))[:100]}")
    # refuses with no sketch open
    call("close_sketch", {})
    r = call("delete_sketch_segment", {"index": 0})
    record(F, "R2 delete_sketch_segment with no sketch open refused", r.get("ok") is False, f"msg={str(r.get('message'))[:100]}")
    close_part(t)


# ---------------------------------------------------------------- #15
def f15() -> None:
    F = "#15"
    cases = (
        ("front", [1, 0, 0], [0, 1, 0], [0, 0, 1], ("x", 10, 12), ("y", 0, 2), ("z", 0, 1)),
        ("top", [1, 0, 0], [0, 0, -1], [0, 1, 0], ("x", 10, 12), ("z", -2, 0), ("y", 0, 1)),
        ("right", [0, 0, -1], [0, 1, 0], [1, 0, 0], ("z", -12, -10), ("y", 0, 2), ("x", 0, 1)),
    )
    for plane, ex, ey, en, bx, by, bz in cases:
        t = new_part()
        s = call("create_sketch", {"plane": plane, "name": "AX"})
        sd = d(s)
        ax_ok = vnear(sd.get("sketch_x_axis"), ex) and vnear(sd.get("sketch_y_axis"), ey) and vnear(sd.get("normal"), en)
        call("draw_point", {"x_mm": 10, "y_mm": 0})
        call("draw_rectangle", {"x1_mm": 10, "y1_mm": 0, "x2_mm": 12, "y2_mm": 2})
        call("close_sketch", {})
        b = call("boss_extrude", {"sketch_name": "AX", "depth_mm": 1, "direction": "+normal"})
        bb = d(call("get_bounding_box", {}))
        lo, hi = bb.get("min_mm", [0, 0, 0]), bb.get("max_mm", [0, 0, 0])
        idx = {"x": 0, "y": 1, "z": 2}
        meas_ok = all(near(lo[idx[a]], l, 0.01) and near(hi[idx[a]], h, 0.01) for a, l, h in (bx, by, bz))
        record(F, f"{plane}: reported axes match expected; sketch (10,0)..(12,2) measured in model space",
               bool(s.get("ok")) and ax_ok and bool(b.get("ok")) and meas_ok,
               f"x={sd.get('sketch_x_axis')} y={sd.get('sketch_y_axis')} n={sd.get('normal')} origin={sd.get('origin')} "
               f"bbox min={lo} max={hi} expected {bx},{by},{bz}")
        if plane == "front":
            # sketch on a face whose normal is -Z (bottom face at z=0)
            faces = d(call("list_faces", {"normal": [0, 0, -1]})).get("faces", [])
            if faces:
                s2 = call("create_sketch", {"face_index": faces[0]["index"], "name": "BotFace"})
                sd2 = d(s2)
                n2 = sd2.get("normal")
                x2, y2 = sd2.get("sketch_x_axis"), sd2.get("sketch_y_axis")
                cross = None
                if x2 and y2:
                    cross = [x2[1]*y2[2]-x2[2]*y2[1], x2[2]*y2[0]-x2[0]*y2[2], x2[0]*y2[1]-x2[1]*y2[0]]
                record(F, "sketch on a -Z-facing face: normal [0,0,-1] and x cross y == normal",
                       bool(s2.get("ok")) and vnear(n2, [0, 0, -1]) and cross is not None and vnear(cross, [0, 0, -1]),
                       f"x={x2} y={y2} normal={n2} x_cross_y={cross} origin={sd2.get('origin')}")
                call("close_sketch", {})
            else:
                record(F, "sketch on -Z face", False, "no -Z face found")
        close_part(t)


# ---------------------------------------------------------------- Revision 3: arc delete by point
def f16() -> None:
    F = "R3"
    t = new_part()
    call("create_sketch", {"plane": "front", "name": "ARC3"})
    c45 = 10 * math.cos(math.radians(45))
    cases = (
        ("CW", -1, 200, (210, 0), (200, -10), (200 + c45, -c45), (200 - c45, c45)),
        ("CCW", 1, 100, (110, 0), (100, 10), (100 + c45, c45), (100 - c45, -c45)),
    )
    for label, direction, cx, st, en, mid, off in cases:
        # check 2 first on a fresh arc: point on circle but off the arc is refused
        a = call("draw_arc", {"center_x_mm": cx, "center_y_mm": 0, "start_x_mm": st[0], "start_y_mm": st[1],
                              "end_x_mm": en[0], "end_y_mm": en[1], "direction": direction})
        n = seg_count()
        r = call("delete_sketch_segment", {"point": {"x_mm": off[0], "y_mm": off[1]}})
        record(F, f"{label} arc: point on circle but OFF the arc refused, count unchanged",
               bool(a.get("ok")) and r.get("ok") is False and seg_count() == n,
               f"arc ok={a.get('ok')} del ok={r.get('ok')} count {n}->{seg_count()} msg={str(r.get('message'))[:120]}")
        r = call("delete_sketch_segment", {"point": {"x_mm": mid[0], "y_mm": mid[1]}})
        record(F, f"{label} arc: true midpoint deletes it, count -1",
               bool(r.get("ok")) and seg_count() == n - 1,
               f"del ok={r.get('ok')} count {n}->{seg_count()} deleted={d(r).get('deleted')} msg={str(r.get('message'))[:120]}")
        # second fresh arc of the same direction: repeat the midpoint delete (check 1 on a second arc)
        a = call("draw_arc", {"center_x_mm": cx + 500, "center_y_mm": 0, "start_x_mm": st[0] + 500, "start_y_mm": st[1],
                              "end_x_mm": en[0] + 500, "end_y_mm": en[1], "direction": direction})
        n = seg_count()
        r = call("delete_sketch_segment", {"point": {"x_mm": mid[0] + 500, "y_mm": mid[1]}})
        record(F, f"{label} arc (repeat): midpoint deletes it, count -1",
               bool(a.get("ok")) and bool(r.get("ok")) and seg_count() == n - 1,
               f"del ok={r.get('ok')} count {n}->{seg_count()} msg={str(r.get('message'))[:120]}")
    call("close_sketch", {})
    close_part(t)


def main() -> int:
    before = d(call("list_open_documents", {})).get("documents", [])
    if before:
        print("STOP: documents already open:", [x["title"] for x in before])
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        only = sys.argv[1:]
        for fn in (f7, f11, f12, f13, f14, f15, f16):
            if only and fn.__name__ not in only:
                continue
            try:
                fn()
            except Exception as exc:
                record(fn.__name__, "script", False, f"EXCEPTION {type(exc).__name__}: {exc}")
                traceback.print_exc()
    finally:
        for t in reversed(list(CREATED)):
            try:
                print("closed", t, call("close_document", {"title": t, "force": True}).get("ok"))
            except Exception as exc:
                print("close fail", t, exc)
        left = d(call("list_open_documents", {})).get("documents", [])
        print("documents left:", [x["title"] for x in left])
        (OUT / "results_sketch.json").write_text(json.dumps(RESULTS, indent=2), encoding="utf-8")
    return 0 if all(r["result"] == "PASS" for r in RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
