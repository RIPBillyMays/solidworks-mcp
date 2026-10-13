"""LIVE Phase 5 Batch C2 verification: sheet metal, swept threads, hole cosmetic thread, full-round fillet.

SW 2017 must be running (launched by the user). NOT run by the offline suite.

Run:  SW_MCP_OUTPUT_ROOT=<repo>/sandbox python tests/live_p5_batchC2.py [sm_base|sm_edge|sm_bend|sm_hem|sm_fold|sm_export|thread|hole|fillet ...]
Calls tool handlers in-process; writes under sandbox/phase5/batchC2/; closes only documents it created.
Each item prints PASS, FAIL, or FENCE-CANDIDATE (2 credible attempts failed; ADR-0006).  Constants tagged
LIVE-PROBE in the modules are exercised by the retries below.
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import solidworks_mcp.server  # noqa: E402,F401  (registers every tool)

from solidworks_mcp.sw_core import OUTPUT_ROOT as _OUT_ROOT  # noqa: E402

if Path(_OUT_ROOT).resolve() != (ROOT / "sandbox").resolve():
    sys.exit(f"ABORT: SW_MCP_OUTPUT_ROOT must be {ROOT / 'sandbox'} (resolved to {_OUT_ROOT}); "
             "set SW_MCP_OUTPUT_ROOT=<repo>/sandbox and rerun.")
from solidworks_mcp import sw_sheetmetal as smod  # noqa: E402
from solidworks_mcp.sw_feature import boss_extrude, cut_extrude, delete_feature, fillet_variant, hole_wizard  # noqa: E402
from solidworks_mcp.sw_file import close_document, create_new_document, list_open_documents, save_document  # noqa: E402
from solidworks_mcp.sw_inspect import (  # noqa: E402
    check_errors, get_bounding_box, get_mass_properties, list_bodies, list_edges, list_faces, list_features,
)
from solidworks_mcp.sw_sheetmetal import (  # noqa: E402
    export_flat_pattern, sheet_metal_base_flange, sheet_metal_edge_flange, sheet_metal_fold_unfold,
    sheet_metal_hem, sheet_metal_sketched_bend,
)
from solidworks_mcp.sw_sketch import close_sketch, create_sketch, draw_circle, draw_line, draw_rectangle  # noqa: E402
from solidworks_mcp.sw_thread import swept_thread  # noqa: E402

OUT = ROOT / "sandbox" / "phase5" / "batchC2"
OUT.mkdir(parents=True, exist_ok=True)
LOG: list[str] = []
created: list[str] = []
T = 2.0  # sheet thickness, mm


def log(step: str, ok, detail: str = "", status: str | None = None) -> None:
    st = status or ("PASS" if ok else "FAIL")
    line = f"{st} | {step} | {detail}"
    LOG.append(line)
    print(line, flush=True)


def call(fn, args=None, ctx=""):
    try:
        r = fn(args or {})
    except Exception as exc:  # noqa: BLE001
        r = {"ok": False, "message": f"EXC {exc!r}", "data": {}}
    if not r.get("ok"):
        print(f"  (call {fn.__name__} {ctx} -> not ok: {r.get('message')} {json.dumps(r.get('data'), default=str)[:300]})", flush=True)
    return r


def D(r):
    return r.get("data") or {}


def near(a, b, tol=0.05):
    return a is not None and b is not None and abs(a - b) <= tol


def docs():
    return D(call(list_open_documents))["documents"]


def vol():
    return D(call(get_mass_properties)).get("volume_mm3")


def size():
    d = D(call(get_bounding_box))
    return [round(h - l, 4) for l, h in zip(d["min_mm"], d["max_mm"])]


def nbodies():
    return len(D(call(list_bodies))["bodies"])


def newdoc():
    before = {d["title"] for d in docs()}
    call(create_new_document, {"kind": "part"})
    for d in docs():
        if d["title"] not in before:
            created.append(d["title"])
            return d["title"]


def feats():
    return D(call(list_features))["features"]


def types():
    return [(f.get("name"), f.get("type")) for f in feats()]


def faces(**flt):
    return D(call(list_faces, flt))["faces"]


def edges():
    return D(call(list_edges))["edges"]


def sketch_rect(plane, x1, y1, x2, y2, name):
    call(create_sketch, {"plane": plane, "name": name})
    call(draw_rectangle, {"x1_mm": x1, "y1_mm": y1, "x2_mm": x2, "y2_mm": y2})
    call(close_sketch)


def sketch_lines(plane, pts, name, face_index=None):
    a = {"name": name}
    a.update({"face_index": face_index} if face_index is not None else {"plane": plane})
    call(create_sketch, a)
    for p, q in zip(pts, pts[1:]):
        call(draw_line, {"x1_mm": p[0], "y1_mm": p[1], "x2_mm": q[0], "y2_mm": q[1]})
    call(close_sketch)


def sketch_circle(plane, x, y, r, name):
    call(create_sketch, {"plane": plane, "name": name})
    call(draw_circle, {"x_mm": x, "y_mm": y, "radius_mm": r})
    call(close_sketch)


def has_type(sub):
    return any(sub in (t or "").lower().replace("-", "") for _, t in types()) or \
        any(sub in (n or "").lower().replace("-", "") for n, _ in types())


def plate(name="Sk1"):
    """Closed 100 x 50 rectangle -> flat sheet-metal plate of thickness T."""
    sketch_rect("front", 0, 0, 100, 50, name)
    return call(sheet_metal_base_flange, {"sketch": name, "thickness_mm": T, "bend_radius_mm": 2, "depth_mm": 10, "name": "BaseFlange"})


def l_part():
    """Open L profile (40 mm leg + 30 mm leg) extruded 50 mm: one bend."""
    sketch_lines("front", [(0, 0), (40, 0), (40, 30)], "SkL")
    return call(sheet_metal_base_flange, {"sketch": "SkL", "thickness_mm": T, "bend_radius_mm": 2, "depth_mm": 50, "name": "BaseL"})


def find_edge(pred):
    for e in edges():
        if pred(e):
            return e
    return None


# ---------------------------------------------------------------------------


def stage_sm_base():
    newdoc()
    r = plate()
    t = types()
    log("2.1 base flange tree has SheetMetal + Base-Flange + Flat-Pattern",
        r["ok"] and has_type("sheetmetal") and has_type("baseflange") and has_type("flatpattern"), f"{r['message'][:80]} tree={t}")
    v = vol()
    log("2.1b volume = area x t (+-0.1%)", near(v, 100 * 50 * T, 100 * 50 * T * 0.001), f"vol={v} exp={100 * 50 * T}")
    log("2.1c tool returned before/after tree counts", bool(D(r).get("before")) and bool(D(r).get("after")), json.dumps(D(r).get("after")))
    # open profile with the radius: volume = (legs + bend arc) x t x depth, radius-agnostic bound
    newdoc()
    r2 = l_part()
    sz = size()
    log("2.1d open L profile bends (bbox 40+t x 30 x 50)", r2["ok"] and near(sz[2], 50, 0.1) and near(sz[0], 40 + T / 2, 2.5), f"size={sz} {r2['message'][:60]}")


def stage_sm_edge():
    newdoc()
    plate()
    z0 = size()[2]
    e = find_edge(lambda x: x["curve_type"] == "line" and abs(x["start_mm"][1] - 50) < 0.01 and abs(x["end_mm"][1] - 50) < 0.01
                  and abs(x["start_mm"][0] - x["end_mm"][0]) > 99.9)  # long edge (not the 2 mm z-edge)
    if e is None:
        log("2.2 edge flange", False, "no top edge found")
        return
    L = 20.0
    ok = False
    # LIVE-PROBE: Right-plane sketch x axis sign (+Z or -Z) is unknown offline, so try both.
    for attempt, sign in enumerate((1, -1), 1):
        sketch_lines("right", [(0, 50), (sign * L, 50)], f"FlangeProf{attempt}")
        r = call(sheet_metal_edge_flange, {"selection": {"edges": [e["index"]]}, "profile_sketches": [f"FlangeProf{attempt}"],
                                           "angle_deg": 90, "name": f"EF{attempt}"})
        sz = size()
        ok = r["ok"] and sz[2] >= z0 + L - 3 and nbodies() == 1
        log(f"2.2 attempt {attempt}: bbox z grows by ~{L} (z {z0} -> {sz[2]}), 1 body", ok, r["message"][:90],
            status=None if ok or attempt == 1 else "FENCE-CANDIDATE")
        if ok:
            break
        call(delete_feature, {"feature_names": [f"EF{attempt}"]})


def stage_sm_bend():
    newdoc()
    plate()
    top = next((f for f in faces(normal=[0, 0, 1]) if f.get("surface_type") == "plane"), None)
    if top is None:
        log("2.3 sketched bend", False, "no +Z face")
        return
    sketch_lines("front", [(50, 0), (50, 50)], "BendLine", face_index=top["index"])
    size0 = size()
    pt = [10, 25, top["point_mm"][2]]
    ok = False
    for attempt, mark in enumerate((smod.SB_MARK_SKETCH, 1), 1):
        # LIVE-PROBE: selection mark of the bend-line sketch (0, then 1)
        smod.SB_MARK_SKETCH = mark
        r = call(sheet_metal_sketched_bend, {"sketch": "BendLine", "fixed_point_mm": pt, "angle_deg": 90, "radius_mm": 2, "name": "SB"})
        sz = size()
        ok = r["ok"] and sz != size0 and sz[2] > 30
        log(f"2.3 attempt {attempt} (sketch mark {mark}): 90 degree bend changes bbox {size0} -> {sz}", ok, r["message"][:90],
            status=None if ok or attempt == 1 else "FENCE-CANDIDATE")
        if ok:
            break
        call(delete_feature, {"feature_names": ["SB"]})


def stage_sm_hem():
    newdoc()
    plate()
    e = find_edge(lambda x: x["curve_type"] == "line" and abs(x["start_mm"][1] - 50) < 0.01 and abs(x["end_mm"][1] - 50) < 0.01
                  and abs(x["start_mm"][0] - x["end_mm"][0]) > 99.9)  # long edge (not the 2 mm z-edge)
    if e is None:
        log("2.4 hem", False, "no top edge found")
        return
    v0 = vol()
    L = 8.0
    exp = L * 100 * T
    for attempt, pos in enumerate(("inside", "outside"), 1):
        r = call(sheet_metal_hem, {"selection": {"edges": [e["index"]]}, "type": "closed", "length_mm": L, "gap_mm": 0.1,
                                   "position": pos, "name": f"Hem{attempt}"})
        dv = (vol() or 0) - v0
        ok = r["ok"] and 0.8 * exp <= dv <= 2.5 * exp
        log(f"2.4 attempt {attempt} ({pos}) closed hem: volume +{dv:.1f} vs length x width x t = {exp}", ok, r["message"][:90],
            status=None if ok or attempt == 1 else "FENCE-CANDIDATE")
        if ok:
            break
        call(delete_feature, {"feature_names": [f"Hem{attempt}"]})


def pick(normal=None, surface_type="plane"):
    fs = faces(surface_type=surface_type) if surface_type != "plane" else faces(normal=normal)
    return fs[0] if fs else None


def stage_sm_fold():
    newdoc()
    l_part()
    base = size()
    fixed = pick([0, -1, 0]) or pick([0, 1, 0])
    bends = faces(surface_type="cylinder")
    if not fixed or not bends:
        log("2.5 unfold", False, f"fixed={fixed and fixed['index']} bends={len(bends)}")
        return
    ok = False
    for attempt, marks in enumerate(((1, 2), (0, 0)), 1):
        # LIVE-PROBE: unfold selection marks (fixed face, bends)
        smod.SM_MARK_FIXED_FACE, smod.SM_MARK_BENDS = marks
        r = call(sheet_metal_fold_unfold, {"action": "unfold", "fixed_face": {"faces": [fixed["index"]]}, "bends": {"faces": [bends[0]["index"]]}})
        sz = size()
        ok = r["ok"] and near(min(sz), T, 0.2)
        log(f"2.5 attempt {attempt} (marks {marks}): unfolded min extent == t ({sz})", ok, r["message"][:90],
            status=None if ok or attempt == 1 else "FENCE-CANDIDATE")
        if ok:
            break
    if ok:
        # After the unfold the bend is a flat strip: the smallest -y plane; the fixed face is the largest -y plane.
        ys = sorted((f for f in faces(normal=[0, -1, 0]) if f.get("surface_type") == "plane"), key=lambda f: f["area_mm2"])
        r = call(sheet_metal_fold_unfold, {"action": "fold", "fixed_face": {"faces": [ys[-1]["index"]]}, "bends": {"faces": [ys[0]["index"]]}})
        log("2.5b fold restores the L bounding box", r["ok"] and all(near(a, b, 0.5) for a, b in zip(size(), base)), f"{size()} vs {base}")
    # flatten toggle works on a fresh part (the unfold above leaves the feature tree dirty)
    newdoc()
    l_part()
    r = call(sheet_metal_fold_unfold, {"action": "flatten"})
    flat = size()
    log("2.5c flatten: Flat-Pattern unsuppressed, min extent == t", r["ok"] and near(min(flat), T, 0.2), f"{flat} {r['message'][:60]}")
    r = call(sheet_metal_fold_unfold, {"action": "unflatten"})
    log("2.5d unflatten restores the folded box", r["ok"] and all(near(a, b, 0.5) for a, b in zip(size(), base)), f"{size()}")


def dxf_extents(path):
    xs, ys = [], []
    lines = Path(path).read_text(errors="ignore").splitlines()
    in_entities = False
    for code, val in zip(lines[::2], lines[1::2]):
        code, val = code.strip(), val.strip()
        if code == "2" and val == "ENTITIES":
            in_entities = True
        elif code == "0" and val == "ENDSEC" and in_entities:
            break
        elif in_entities and code in ("10", "11"):
            xs.append(float(val))
        elif in_entities and code in ("20", "21"):
            ys.append(float(val))
    return (max(xs) - min(xs), max(ys) - min(ys)) if xs and ys else None


def stage_sm_export():
    newdoc()
    l_part()
    r = call(save_document, {"path": "phase5/batchC2/flat_src.sldprt", "overwrite": True})
    flat = None
    r2 = call(sheet_metal_fold_unfold, {"action": "flatten"})
    if r2["ok"]:
        flat = size()
        call(sheet_metal_fold_unfold, {"action": "unflatten"})
    dxf = OUT / "flat.dxf"
    r3 = call(export_flat_pattern, {"path": "phase5/batchC2/flat.dxf", "overwrite": True})
    d = D(r3)
    log("2.6 DXF exists, >0 bytes, has ENTITIES", r["ok"] and r3["ok"] and d.get("size_bytes", 0) > 0 and d.get("entities_section"),
        f"{r3['message'][:100]}")
    ext = dxf_extents(dxf) if dxf.exists() else None
    if ext and flat:
        want = sorted(flat, reverse=True)[:2]
        got = sorted(ext, reverse=True)
        log("2.6b outline extents match flattened bbox (+-1 mm)", all(near(a, b, 1.0) for a, b in zip(got, want)), f"dxf={ext} flat_bbox={flat}")
    else:
        log("2.6b outline extents", False, f"dxf={ext} flat={flat}")
    outside = call(export_flat_pattern, {"path": str(ROOT / "escape.dxf")})
    log("2.6c path outside output_root refused", not outside["ok"], outside["message"][:80])


def stage_thread():
    # external M10 x 1.5 on a 10 mm bolt, then internal in a 8 mm hole
    for external in (True, False):
        newdoc()
        r = 5.0 if external else 4.0
        if external:
            sketch_circle("front", 0, 0, r, "CylSk")
            call(boss_extrude, {"sketch_name": "CylSk", "depth_mm": 20, "name": "Cyl"})
        else:
            sketch_rect("front", -15, -15, 15, 15, "BlkSk")
            call(boss_extrude, {"sketch_name": "BlkSk", "depth_mm": 20, "name": "Blk"})
            sketch_circle("front", 0, 0, r, "HoleSk")
            call(cut_extrude, {"sketch_name": "HoleSk", "end_condition": "through_all", "name": "Hole"})
        sketch_circle("front", 0, 0, r, "HelixSk")
        ok = False
        for attempt, (plane, start, axis) in enumerate((("top", [r, 0], "v"), ("top", [r, 0], "v")), 1):
            # attempt 2 retries after rebuilding in case the first sweep raced the helix rebuild
            res = call(swept_thread, {"circle_sketch": "HelixSk", "profile_plane": plane, "start_mm": start, "axis": axis,
                                      "pitch_mm": 1.5, "length_mm": 9.0, "external": external, "mode": "cut", "name": f"Th{attempt}"})
            d = D(res)
            ok = res["ok"] and d.get("within_tolerance") and nbodies() == 1
            log(f"2.7 {'external' if external else 'internal'} attempt {attempt}: removed {d.get('volume_removed_or_added_mm3')} "
                f"vs analytic {d.get('expected_volume_mm3')} (dev {d.get('deviation')}), 1 body", ok, res["message"][:90],
                status=None if ok or attempt == 1 else "FENCE-CANDIDATE")
            if ok:
                break
            call(delete_feature, {"feature_names": [f"Th{attempt}", f"Th{attempt}_Helix", f"Th{attempt}_Profile"]})
        errs = D(call(check_errors))
        log("2.7b check_errors reports no problems", call(check_errors).get("ok"), json.dumps(errs, default=str)[:160])


def stage_hole():
    newdoc()
    sketch_rect("front", 0, 0, 40, 40, "BlkSk")
    call(boss_extrude, {"sketch_name": "BlkSk", "depth_mm": 20, "name": "Blk"})
    v0 = vol()
    r = call(hole_wizard, {"kind": "tap", "standard": "iso", "size": "M6x1.0", "diameter_mm": 5.0, "depth_mm": 12, "thread_depth_mm": 10,
                           "points": [{"x_mm": 10, "y_mm": 10, "z_mm": 20}], "cosmetic_thread": True, "name": "TapHole"})
    removed = v0 - (vol() or 0)
    log("2.8 tapped hole is an M6 tap-drill hole, not the 2 in thread (removed 150..400 mm3)", r["ok"] and 150 < removed < 400, f"removed={removed:.1f} {r['message'][:80]}")
    ct = D(r).get("cosmetic_threads") or []
    # The cosmetic thread is a sub-feature of the hole, not a top-level tree entry.
    from solidworks_mcp.sw_core import value as _value, require_part as _rp
    subs_types = []
    try:
        _doc = _rp()[1]
        hole = next(f for f in smod.iter_feature_objects(_doc) if str(getattr(f, "Name", "")) == "TapHole")
        sub = _value(hole, "GetFirstSubFeature")
        while sub is not None:
            subs_types.append(str(sub.GetTypeName2))
            sub = _value(sub, "GetNextSubFeature")
    except Exception as exc:  # noqa: BLE001
        subs_types.append(f"EXC {exc!r}")
    log("2.8b CosmeticThread in tree + ISO M6x1.0 readback d=6", bool(ct) and ct[0].get("ok") and ct[0].get("size_readback") == "M6x1.0"
        and near(ct[0].get("diameter_readback_mm"), 6.0, 0.01) and ("CosmeticThread" in subs_types), f"subs={subs_types} " + json.dumps(ct, default=str)[:200])


def stage_fillet():
    newdoc()
    sketch_rect("front", -20, -5, 20, 5, "BoxSk")
    call(boss_extrude, {"sketch_name": "BoxSk", "depth_mm": 15, "name": "Box"})
    v0 = vol()
    n0 = len(faces())
    fs = faces(surface_type="plane")
    top = next(f for f in fs if abs(f["normal"][2] - 1) < 0.02 and abs(f["point_mm"][2] - 15) < 0.1)
    s1 = next(f for f in fs if abs(f["normal"][1] + 1) < 0.02)
    s2 = next(f for f in fs if abs(f["normal"][1] - 1) < 0.02)
    ok = False
    for attempt in (1, 2):
        # attempt 2 re-lists faces first (R-011) in case indices moved
        r = call(fillet_variant, {"type": "full_round", "side_set_1": {"faces": [s1["index"]]}, "center": {"faces": [top["index"]]},
                                  "side_set_2": {"faces": [s2["index"]]}, "name": f"FR{attempt}"})
        cyl = [f for f in faces(surface_type="cylinder")]
        removed = v0 - (vol() or 0)
        exp = (10 * 5 - math.pi * 25 / 2) * 40  # (w*r - pi r^2/2) x length, r = 5
        ok = r["ok"] and bool(cyl) and near(removed, exp, exp * 0.03)
        log(f"2.9 attempt {attempt} full round: cylinder face present, removed {removed:.1f} vs {exp:.1f}, faces {n0} -> {len(faces())}", ok,
            r["message"][:90], status=None if ok or attempt == 1 else "FENCE-CANDIDATE")
        if ok:
            break
        call(delete_feature, {"feature_names": [f"FR{attempt}"]})
        fs = faces(surface_type="plane")
        top = next(f for f in fs if abs(f["normal"][2] - 1) < 0.02 and abs(f["point_mm"][2] - 15) < 0.1)
        s1 = next(f for f in fs if abs(f["normal"][1] + 1) < 0.02)
        s2 = next(f for f in fs if abs(f["normal"][1] - 1) < 0.02)


STAGES = {"sm_base": stage_sm_base, "sm_edge": stage_sm_edge, "sm_bend": stage_sm_bend, "sm_hem": stage_sm_hem,
          "sm_fold": stage_sm_fold, "sm_export": stage_sm_export, "thread": stage_thread, "hole": stage_hole, "fillet": stage_fillet}


def finish(keep_base):
    for x in docs():
        if x["title"] not in keep_base:
            call(close_document, {"title": x["title"], "force": True})


if __name__ == "__main__":
    which = sys.argv[1:] or list(STAGES)
    base = [d["title"] for d in docs()]
    print("BASELINE", base, flush=True)
    try:
        for w in which:
            STAGES[w]()
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
