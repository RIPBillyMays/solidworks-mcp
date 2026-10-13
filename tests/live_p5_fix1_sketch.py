# Copyright 2026 JIALE LIU
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Modified for SOLIDWORKS 2017 support (fork).

"""LIVE check of Phase 5 fix #1 (exact sketch placement and verification).

Run only with SOLIDWORKS 2017 already running and NO other document open:

    .venv\\Scripts\\python.exe tests\\live_p5_fix1_sketch.py

It calls the public handlers directly (so the new code runs, not a stale MCP
server), creates scratch parts only, and force-closes every document it made.
Results are printed as a table and written to sandbox/fix1_probes/results.json.
"""

from __future__ import annotations

import json
import math
import sys
import traceback
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from solidworks_mcp.sw_core import active_document, sketch_segment_objects, value  # noqa: E402
from solidworks_mcp.sw_feature import boss_extrude  # noqa: E402
from solidworks_mcp.sw_file import close_document, create_new_document, list_open_documents  # noqa: E402
from solidworks_mcp.sw_inspect import get_mass_properties  # noqa: E402
from solidworks_mcp.sw_sketch import (  # noqa: E402
    add_dimension,
    close_sketch,
    create_sketch,
    draw_arc,
    draw_centerline,
    draw_circle,
    draw_line,
    draw_polygon,
    draw_polyline,
    draw_rectangle,
    get_sketch_status,
    list_sketch_segments,
)

OUT = ROOT / "sandbox" / "fix1_probes"
RESULTS: list[dict[str, Any]] = []
CREATED: list[str] = []
TOL_MM = 1e-3


def record(check: str, passed: bool, evidence: str) -> None:
    RESULTS.append({"check": check, "result": "PASS" if passed else "FAIL", "evidence": evidence})
    print(f"[{'PASS' if passed else 'FAIL'}] {check}: {evidence}", flush=True)


def new_part(sketch: str, plane: str = "front") -> None:
    payload = create_new_document({"kind": "part"})
    if not payload.get("ok"):
        raise RuntimeError(f"create_new_document failed: {payload}")
    CREATED.append(payload["data"]["document"]["title"] if "data" in payload else payload["document"]["title"])
    created = create_sketch({"plane": plane, "name": sketch})
    if not created.get("ok"):
        raise RuntimeError(f"create_sketch failed: {created}")


def data(payload: dict[str, Any]) -> dict[str, Any]:
    return payload.get("data", payload)


def segs() -> list[dict[str, Any]]:
    return data(list_sketch_segments({}))["segments"]


def sm_state() -> tuple[Any, Any]:
    _, doc = active_document()
    manager = doc.SketchManager
    return (bool(manager.AddToDB), bool(manager.DisplayWhenAdded))


def star(r_out: float, r_in: float, n: int = 10) -> list[tuple[float, float]]:
    pts = []
    for i in range(n):
        radius = r_out if i % 2 == 0 else r_in
        angle = math.radians(90 + i * 360.0 / n)
        pts.append((radius * math.cos(angle), radius * math.sin(angle)))
    return pts


def shoelace(pts: list[tuple[float, float]]) -> float:
    total = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def chain_lines(pts: list[tuple[float, float]], closed: bool) -> list[dict[str, Any]]:
    pairs = list(zip(pts, pts[1:])) + ([(pts[-1], pts[0])] if closed else [])
    return [
        draw_line({"x1_mm": a[0], "y1_mm": a[1], "x2_mm": b[0], "y2_mm": b[1]}) for a, b in pairs
    ]


def line_error(segment: dict[str, Any], a: tuple[float, float], b: tuple[float, float]) -> float:
    """Worst endpoint error (mm) with either orientation allowed."""
    s, e = segment["start_mm"], segment["end_mm"]
    straight = max(math.dist(s[:2], a), math.dist(e[:2], b))
    flipped = max(math.dist(s[:2], b), math.dist(e[:2], a))
    return min(straight, flipped)


def volume() -> float:
    return float(data(get_mass_properties({}))["volume_mm3"])


def extrude(sketch: str, depth: float) -> dict[str, Any]:
    return boss_extrude({"sketch_name": sketch, "depth_mm": depth, "name": sketch + "_Boss"})


# --------------------------------------------------------------------------
def check1_state_restore() -> None:
    new_part("C1")
    before = sm_state()
    ok_all = True
    notes = [f"before AddToDB,Display={before}"]
    calls = [
        ("draw_line", draw_line, {"x1_mm": 0, "y1_mm": 0, "x2_mm": 10, "y2_mm": 0}),
        ("draw_circle", draw_circle, {"x_mm": 30, "y_mm": 30, "radius_mm": 5}),
        ("draw_rectangle", draw_rectangle, {"x1_mm": 50, "y1_mm": 50, "x2_mm": 60, "y2_mm": 55}),
        ("draw_polyline", draw_polyline, {"points": [{"x_mm": 70, "y_mm": 0}, {"x_mm": 80, "y_mm": 5}]}),
    ]
    for name, fn, args in calls:
        payload = fn(args)
        after = sm_state()
        good = after == before and bool(payload.get("ok"))
        ok_all &= good
        notes.append(f"{name} ok={payload.get('ok')} after={after}")
    record("1a state restored after successful draws", ok_all, "; ".join(notes))

    # Forced failure paths: zero-length line (reaches COM), and a raising call.
    fail_notes = []
    ok_fail = True
    try:
        payload = draw_line({"x1_mm": 5, "y1_mm": 5, "x2_mm": 5, "y2_mm": 5})
        fail_notes.append(f"zero-length line ok={payload.get('ok')} msg={str(payload.get('message'))[:80]}")
    except Exception as exc:  # restoration must hold even when Create* raises
        fail_notes.append(f"zero-length line raised {type(exc).__name__}")
    after = sm_state()
    ok_fail &= after == before
    fail_notes.append(f"after={after}")
    try:
        draw_circle({"x_mm": 0, "y_mm": 0, "radius_mm": 0})
        fail_notes.append("zero-radius circle returned")
    except Exception as exc:
        fail_notes.append(f"zero-radius circle raised {type(exc).__name__}")
    after = sm_state()
    ok_fail &= after == before
    fail_notes.append(f"after={after}")
    record("1b state restored after failing draws", ok_fail, "; ".join(fail_notes))
    close_sketch({})


def check2_crowded() -> None:
    new_part("C2", "right")
    pts = star(10, 4)
    returns = chain_lines(pts, True)
    stair = []
    x, y = 20.0, 0.0
    for _ in range(3):
        stair.append(((x, y), (x + 0.6, y)))
        x += 0.6
        stair.append(((x, y), (x, y + 0.6)))
        y += 0.6
    for a, b in stair:
        returns.append(draw_line({"x1_mm": a[0], "y1_mm": a[1], "x2_mm": b[0], "y2_mm": b[1]}))
    base = ((30.0, 20.0), (40.0, 20.0))
    near = ((35.0, 20.4), (35.0, 30.0))
    for a, b in (base, near):
        returns.append(draw_line({"x1_mm": a[0], "y1_mm": a[1], "x2_mm": b[0], "y2_mm": b[1]}))
    expected = list(zip(pts, pts[1:] + pts[:1])) + stair + [base, near]
    segments = segs()
    all_ok = all(r.get("ok") for r in returns)
    verified = all(data(r).get("verified", True) for r in returns)
    worst = 0.0
    bad = []
    if len(segments) != len(expected):
        bad.append(f"segment count {len(segments)} != {len(expected)}")
    else:
        for i, (seg, (a, b)) in enumerate(zip(segments, expected)):
            err = line_error(seg, a, b)
            worst = max(worst, err)
            if err > TOL_MM:
                bad.append(f"seg{i} err {err:.4f} mm")
    passed = all_ok and verified and not bad and worst <= TOL_MM
    record(
        "2 crowded sketch exact (star + staircase + 0.4 mm near-line)",
        passed,
        f"{len(expected)} lines, all ok={all_ok}, verified={verified}, worst endpoint err={worst:.2e} mm; {bad[:5]}",
    )
    close_sketch({})


def check3_arc_snap() -> None:
    new_part("C3", "right")
    first = draw_arc({"center_x_mm": 0, "center_y_mm": 0, "start_x_mm": 5, "start_y_mm": 0,
                      "end_x_mm": 0, "end_y_mm": 5, "direction": 1})
    second = draw_arc({"center_x_mm": 0.5, "center_y_mm": 0, "start_x_mm": 5.5, "start_y_mm": 0,
                       "end_x_mm": 0.5, "end_y_mm": 5, "direction": 1})
    segments = segs()
    centres = [s.get("center_mm") for s in segments]
    radii = [s.get("radius_mm") for s in segments]
    good = (
        len(segments) == 2
        and math.dist(centres[1][:2], (0.5, 0.0)) < TOL_MM
        and abs(radii[1] - 5.0) < TOL_MM
        and bool(first.get("ok")) and bool(second.get("ok"))
    )
    record(
        "3 arc centre 0.5 mm from existing arc centre",
        good,
        f"requested centre (0.5,0) R5; actual centre {centres[1]} R{radii[1]}; ok={first.get('ok')},{second.get('ok')}",
    )
    close_sketch({})


def check4_star_polyline() -> None:
    new_part("C4")
    pts = star(10, 4)
    payload = draw_polyline({"points": [{"x_mm": x, "y_mm": y} for x, y in pts], "closed": True})
    status = data(get_sketch_status({}))["sketch_status"]
    segments = segs()
    pairs = list(zip(pts, pts[1:] + pts[:1]))
    worst = max((line_error(s, a, b) for s, (a, b) in zip(segments, pairs)), default=99.0)
    close_sketch({})
    ext = extrude("C4", 5)
    vol = volume() if ext.get("ok") else float("nan")
    expected = shoelace(pts) * 5
    good = (
        bool(payload.get("ok")) and len(segments) == 10 and worst <= TOL_MM and bool(ext.get("ok"))
        and math.isclose(vol, expected, rel_tol=1e-4)
    )
    record(
        "4 closed draw_polyline star -> extrude",
        good,
        f"polyline ok={payload.get('ok')} verified={data(payload).get('verified')} segs={len(segments)} "
        f"worst err={worst:.2e} mm; sketch_status={status}; extrude ok={ext.get('ok')} "
        f"msg={str(ext.get('message'))[:80]}; volume actual={vol:.4f} expected={expected:.4f}",
    )


def check5_rect_lines() -> None:
    new_part("C5")
    corners = [(0, 0), (20, 0), (20, 10), (0, 10)]
    returns = chain_lines([(float(x), float(y)) for x, y in corners], True)
    status = data(get_sketch_status({}))["sketch_status"]
    close_sketch({})
    ext = extrude("C5", 5)
    vol = volume() if ext.get("ok") else float("nan")
    good = all(r.get("ok") for r in returns) and bool(ext.get("ok")) and math.isclose(vol, 1000.0, rel_tol=1e-4)
    record(
        "5 four draw_line calls -> 20x10 rectangle -> extrude 5",
        good,
        f"line ok={[r.get('ok') for r in returns]}; sketch_status={status}; extrude ok={ext.get('ok')} "
        f"msg={str(ext.get('message'))[:80]}; volume actual={vol:.4f} expected=1000",
    )


def arc_geometry(index: int) -> dict[str, Any]:
    _, doc = active_document()
    seg = sketch_segment_objects(doc)[index]
    center = value(seg, "GetCenterPoint2")
    start = value(seg, "GetStartPoint2")
    end = value(seg, "GetEndPoint2")
    try:
        rotation = int(value(seg, "GetRotationDir"))
    except Exception:
        rotation = None
    cx, cy = float(center.X), float(center.Y)
    a0 = math.atan2(float(start.Y) - cy, float(start.X) - cx)
    a1 = math.atan2(float(end.Y) - cy, float(end.X) - cx)
    # GetRotationDir: 1 = counter-clockwise start -> end, -1 = clockwise start -> end.
    # (SOLIDWORKS 2017 does NOT swap start/end for a clockwise request.)
    sign = -1 if rotation == -1 else 1
    sweep = ((a1 - a0) * sign) % (2 * math.pi)
    mid = a0 + sign * sweep / 2
    return {
        "rotation_dir": rotation,
        "sweep_deg": round(math.degrees(sweep), 4),
        "mid_deg": round(math.degrees(math.atan2(math.sin(mid), math.cos(mid))), 4),
        "start_mm": [round(float(start.X) * 1000, 4), round(float(start.Y) * 1000, 4)],
        "end_mm": [round(float(end.X) * 1000, 4), round(float(end.Y) * 1000, 4)],
    }


def check6_arc_direction() -> None:
    new_part("C6")
    ccw = draw_arc({"center_x_mm": 0, "center_y_mm": 0, "start_x_mm": 10, "start_y_mm": 0,
                    "end_x_mm": 0, "end_y_mm": 10, "direction": 1})
    cw = draw_arc({"center_x_mm": 40, "center_y_mm": 0, "start_x_mm": 50, "start_y_mm": 0,
                   "end_x_mm": 40, "end_y_mm": -10, "direction": -1})
    g_ccw, g_cw = arc_geometry(0), arc_geometry(1)
    good_ccw = bool(ccw.get("ok")) and abs(g_ccw["sweep_deg"] - 90) < 0.01 and abs(g_ccw["mid_deg"] - 45) < 0.01
    good_cw = bool(cw.get("ok")) and abs(g_cw["sweep_deg"] - 90) < 0.01 and abs(g_cw["mid_deg"] + 45) < 0.01
    record(
        "6 draw_arc direction=1 and -1",
        good_ccw and good_cw,
        f"dir=1 ok={ccw.get('ok')} actual={data(ccw).get('actual')} geom={g_ccw} (expect sweep 90, mid 45); "
        f"dir=-1 ok={cw.get('ok')} msg={str(cw.get('message'))[:100]} actual={data(cw).get('actual')} geom={g_cw} "
        f"(expect sweep 90 along rotation_dir, mid -45). GetRotationDir returned {g_ccw['rotation_dir']} for dir=1 and "
        f"{g_cw['rotation_dir']} for dir=-1",
    )
    close_sketch({})


def check7_8_construction_dimension() -> None:
    new_part("C7")
    pts = [(0.0, 0.0), (20.0, 0.0), (20.0, 10.0), (0.0, 10.0)]
    payload = draw_polyline({"points": [{"x_mm": x, "y_mm": y} for x, y in pts], "construction": True})
    segments = segs()
    flags = [s["construction"] for s in segments]
    record(
        "7 draw_polyline construction=true",
        bool(payload.get("ok")) and len(segments) == 3 and all(flags),
        f"ok={payload.get('ok')} msg={str(payload.get('message'))[:80]}; segments={len(segments)} construction flags={flags}",
    )
    close_sketch({})

    # 8: dimension on a (non-construction) polyline segment, new sketch in a fresh part.
    new_part("C8")
    payload = draw_polyline({"points": [{"x_mm": 0, "y_mm": 0}, {"x_mm": 20, "y_mm": 0}, {"x_mm": 20, "y_mm": 10}]})
    before = segs()
    try:
        dim = add_dimension({"selection": {"sketch_segments": [0]}, "value_mm": 25, "kind": "horizontal",
                             "place_x_mm": 10, "place_y_mm": -5})
    except Exception as exc:
        dim = {"ok": False, "message": f"raised {type(exc).__name__}: {exc}"}
    after = segs()
    length = after[0].get("length_mm") if after else None
    good = bool(payload.get("ok")) and bool(dim.get("ok")) and length is not None and abs(length - 25) < TOL_MM
    record(
        "8 add_dimension on polyline segment",
        good,
        f"polyline ok={payload.get('ok')}; add_dimension ok={dim.get('ok')} applied={data(dim).get('applied')} "
        f"msg={str(dim.get('message'))[:80]}; segment0 length before={before[0].get('length_mm')} after={length} (requested 25)",
    )
    close_sketch({})


def check9_others() -> None:
    new_part("C9")
    calls = {
        "draw_rectangle": (draw_rectangle, {"x1_mm": 0, "y1_mm": 0, "x2_mm": 30, "y2_mm": 20}),
        "draw_polygon": (draw_polygon, {"center_x_mm": 60, "center_y_mm": 0, "point_x_mm": 70, "point_y_mm": 0, "sides": 6}),
        "draw_centerline": (draw_centerline, {"x1_mm": -10, "y1_mm": -30, "x2_mm": 80, "y2_mm": -30}),
        "draw_circle": (draw_circle, {"x_mm": 20, "y_mm": 60, "radius_mm": 8}),
    }
    good = True
    notes = []
    for name, (fn, args) in calls.items():
        payload = fn(args)
        verified = data(payload).get("verified")
        good &= bool(payload.get("ok")) and verified is True
        notes.append(f"{name} ok={payload.get('ok')} verified={verified} msg={str(payload.get('message'))[:60]}")
    record("9 rectangle/polygon/centerline/circle verified", good, "; ".join(notes))
    close_sketch({})


def main() -> int:
    before = data(list_open_documents({}))["documents"]
    if before:
        print("STOP: documents already open, touching nothing:", [d["title"] for d in before])
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    checks = [
        check1_state_restore, check2_crowded, check3_arc_snap, check4_star_polyline,
        check5_rect_lines, check6_arc_direction, check7_8_construction_dimension, check9_others,
    ]
    try:
        for fn in checks:
            try:
                fn()
            except Exception as exc:
                record(fn.__name__, False, f"EXCEPTION {type(exc).__name__}: {exc}")
                traceback.print_exc()
    finally:
        for title in reversed(CREATED):
            try:
                closed = close_document({"title": title, "force": True})
                print(f"closed {title}: {closed.get('ok')}")
            except Exception as exc:
                print(f"could not close {title}: {exc}")
        left = data(list_open_documents({}))["documents"]
        print("documents left open:", [d["title"] for d in left])
        (OUT / "results.json").write_text(json.dumps(RESULTS, indent=2), encoding="utf-8")
    return 0 if all(r["result"] == "PASS" for r in RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
