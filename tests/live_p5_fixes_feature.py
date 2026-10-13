# Modified for SOLIDWORKS 2017 support (fork).
"""LIVE verification of the Phase 5 feature fixes (#5 direction, #8 delete, #9 suppression, #17 fillets).

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


def sk_rect(plane: str, name: str, x1=0, y1=0, x2=20, y2=20, close=True) -> None:
    s = call("create_sketch", {"plane": plane, "name": name})
    if not s.get("ok"):
        raise RuntimeError(f"sketch failed {s}")
    r = call("draw_rectangle", {"x1_mm": x1, "y1_mm": y1, "x2_mm": x2, "y2_mm": y2})
    if not r.get("ok"):
        raise RuntimeError(f"rect failed {r}")
    if close:
        call("close_sketch", {})


def vol() -> float:
    p = call("get_mass_properties", {})
    return float(d(p).get("volume_mm3", 0.0)) if p.get("ok") else 0.0


def bbox() -> tuple[list[float], list[float]] | None:
    p = call("get_bounding_box", {})
    if not p.get("ok"):
        return None
    return d(p)["min_mm"], d(p)["max_mm"]


def near(a: float, b: float, tol: float = 0.01) -> bool:
    return abs(a - b) <= tol


def vec_near(v, w, tol=1e-3) -> bool:
    return v is not None and all(abs(a - b) <= tol for a, b in zip(v, w))


def bb_str(b) -> str:
    return "none" if b is None else f"{b[0]}..{b[1]}"


# ---------------------------------------------------------------- #5
def f5_front() -> None:
    F = "#5"
    t = new_part()
    sk_rect("front", "S1")
    b = call("boss_extrude", {"sketch_name": "S1", "depth_mm": 10, "direction": "+normal"})
    dd = d(b)
    bb = bbox()
    record(F, "Front boss +normal d10: bbox Z 0..10, vec [0,0,1], first-boss delta == volume 4000",
           bool(b.get("ok")) and bb is not None and near(bb[0][2], 0) and near(bb[1][2], 10)
           and vec_near(dd.get("direction_vector"), [0, 0, 1]) and dd.get("direction") == "+normal"
           and dd.get("volume_delta_mm3") is not None and near(dd["volume_delta_mm3"], 4000, 0.5)
           and near(vol(), 4000, 0.5),
           f"ok={b.get('ok')} dir={dd.get('direction')} vec={dd.get('direction_vector')} delta={dd.get('volume_delta_mm3')} "
           f"before={dd.get('volume_before_mm3')} after={dd.get('volume_after_mm3')} bboxZ={bb and (bb[0][2], bb[1][2])} vol={vol()}")
    # cut +normal, full profile, d3, from plane Z=0 toward +Z: removes Z 0..3 -> bbox Z 3..10, delta -1200
    sk_rect("front", "S2")
    c = call("cut_extrude", {"sketch_name": "S2", "depth_mm": 3, "direction": "+normal"})
    cd = d(c)
    bb = bbox()
    record(F, "Front cut +normal d3: bbox Z 3..10, delta -1200, vec [0,0,1], not auto-reversed",
           bool(c.get("ok")) and bb is not None and near(bb[0][2], 3) and near(bb[1][2], 10)
           and cd.get("volume_delta_mm3") is not None and near(cd["volume_delta_mm3"], -1200, 0.5)
           and vec_near(cd.get("direction_vector"), [0, 0, 1]) and cd.get("reversed_automatically") is False,
           f"ok={c.get('ok')} dir={cd.get('direction')} vec={cd.get('direction_vector')} delta={cd.get('volume_delta_mm3')} "
           f"auto={cd.get('reversed_automatically')} bboxZ={bb and (bb[0][2], bb[1][2])} msg={str(c.get('message'))[:90]}")
    # default cut (no direction): goes -Z first (empty), should retry +Z and report reversed_automatically
    sk_rect("front", "S3")
    c = call("cut_extrude", {"sketch_name": "S3", "depth_mm": 5})
    cd = d(c)
    bb = bbox()
    record(F, "default cut auto-reverses: reversed_automatically true, bbox Z 5..10, delta -800",
           bool(c.get("ok")) and cd.get("reversed_automatically") is True and bb is not None
           and near(bb[0][2], 5) and near(bb[1][2], 10) and cd.get("volume_delta_mm3") is not None
           and near(cd["volume_delta_mm3"], -800, 0.5),
           f"ok={c.get('ok')} auto={cd.get('reversed_automatically')} dir={cd.get('direction')} vec={cd.get('direction_vector')} "
           f"delta={cd.get('volume_delta_mm3')} bboxZ={bb and (bb[0][2], bb[1][2])}")
    close_part(t)

    # -normal boss
    t = new_part()
    sk_rect("front", "S1")
    b = call("boss_extrude", {"sketch_name": "S1", "depth_mm": 10, "direction": "-normal"})
    dd = d(b)
    bb = bbox()
    record(F, "Front boss -normal d10: bbox Z -10..0, vec [0,0,-1]",
           bool(b.get("ok")) and bb is not None and near(bb[0][2], -10) and near(bb[1][2], 0)
           and vec_near(dd.get("direction_vector"), [0, 0, -1]),
           f"ok={b.get('ok')} dir={dd.get('direction')} vec={dd.get('direction_vector')} bboxZ={bb and (bb[0][2], bb[1][2])}")
    # cut -normal d3: removes Z -3..0 -> bbox Z -10..-3
    sk_rect("front", "S2")
    c = call("cut_extrude", {"sketch_name": "S2", "depth_mm": 3, "direction": "-normal"})
    cd = d(c)
    bb = bbox()
    record(F, "Front cut -normal d3: bbox Z -10..-3, delta -1200, vec [0,0,-1]",
           bool(c.get("ok")) and bb is not None and near(bb[0][2], -10) and near(bb[1][2], -3)
           and cd.get("volume_delta_mm3") is not None and near(cd["volume_delta_mm3"], -1200, 0.5)
           and vec_near(cd.get("direction_vector"), [0, 0, -1]),
           f"ok={c.get('ok')} delta={cd.get('volume_delta_mm3')} vec={cd.get('direction_vector')} bboxZ={bb and (bb[0][2], bb[1][2])}")
    # explicit +normal cut where no material exists on +Z side: must fail and NOT retry
    sk_rect("front", "S3")
    v0 = vol()
    c = call("cut_extrude", {"sketch_name": "S3", "depth_mm": 3, "direction": "+normal"})
    cd = d(c)
    record(F, "explicit +normal cut with no material on +Z: ok false, not retried, volume unchanged",
           c.get("ok") is False and near(vol(), v0, 0.01) and not cd.get("reversed_automatically"),
           f"ok={c.get('ok')} auto={cd.get('reversed_automatically')} vol {v0}->{vol()} msg={str(c.get('message'))[:110]}")
    close_part(t)

    # mid_plane body both sides, then +normal / -normal cuts
    for dirn, lo, hi in (("+normal", -5, 0), ("-normal", 0, 5)):
        t = new_part()
        sk_rect("front", "S1")
        b = call("boss_extrude", {"sketch_name": "S1", "depth_mm": 10, "end_condition": "mid_plane"})
        bd = d(b)
        sym_ok = bd.get("direction") == "symmetric"
        sk_rect("front", "S2")
        c = call("cut_extrude", {"sketch_name": "S2", "depth_mm": 5, "direction": dirn})
        cd = d(c)
        bb = bbox()
        record(F, f"body on both sides, cut {dirn} d5: bbox Z {lo}..{hi}, delta -2000"
               + ("; mid_plane reports symmetric" if dirn == "+normal" else ""),
               bool(c.get("ok")) and bb is not None and near(bb[0][2], lo) and near(bb[1][2], hi)
               and cd.get("volume_delta_mm3") is not None and near(cd["volume_delta_mm3"], -2000, 0.5)
               and (sym_ok or dirn != "+normal"),
               f"boss.direction={bd.get('direction')} cut ok={c.get('ok')} delta={cd.get('volume_delta_mm3')} "
               f"bboxZ={bb and (bb[0][2], bb[1][2])}")
        close_part(t)


def f5_planes() -> None:
    F = "#5"
    # Top: normal +Y; Right: normal +X
    for plane, axis, label in (("top", 1, "Y"), ("right", 0, "X")):
        for dirn, sgn in (("+normal", 1), ("-normal", -1)):
            t = new_part()
            sk_rect(plane, "S1")
            b = call("boss_extrude", {"sketch_name": "S1", "depth_mm": 10, "direction": dirn})
            dd = d(b)
            bb = bbox()
            exp = [0, 0, 0]
            exp[axis] = sgn
            lo, hi = (0, 10) if sgn > 0 else (-10, 0)
            record(F, f"{plane} boss {dirn} d10: bbox {label} {lo}..{hi}, vec {exp}",
                   bool(b.get("ok")) and bb is not None and near(bb[0][axis], lo) and near(bb[1][axis], hi)
                   and vec_near(dd.get("direction_vector"), exp),
                   f"ok={b.get('ok')} vec={dd.get('direction_vector')} bbox{label}={bb and (bb[0][axis], bb[1][axis])}")
            close_part(t)


def f5_conflict() -> None:
    F = "#5"
    t = new_part()
    sk_rect("front", "S1", close=False)
    r = call("boss_extrude", {"sketch_name": "S1", "depth_mm": 10, "direction": "+normal", "reverse": False})
    v = vol()
    record(F, "direction + reverse (even false) rejected, nothing built",
           r.get("ok") is False and v == 0.0, f"ok={r.get('ok')} vol={v} msg={str(r.get('message'))[:120]}")
    r = call("boss_extrude", {"sketch_name": "S1", "depth_mm": 10, "reverse": True})
    bb = bbox()
    record(F, "reverse alone still works (boss reverse=true -> -Z)",
           bool(r.get("ok")) and bb is not None and near(bb[0][2], -10) and near(bb[1][2], 0),
           f"ok={r.get('ok')} dir={d(r).get('direction')} bboxZ={bb and (bb[0][2], bb[1][2])}")
    close_part(t)


# ---------------------------------------------------------------- #8
def f8() -> None:
    F = "#8"
    t = new_part()
    sk_rect("front", "Base")
    call("boss_extrude", {"sketch_name": "Base", "depth_mm": 10, "name": "BaseBoss"})
    for nm in ("Keep", "Target"):
        s = call("create_sketch", {"plane": "front", "name": nm})
        call("draw_circle", {"x_mm": 10, "y_mm": 10, "radius_mm": 3 if nm == "Keep" else 2})
        call("close_sketch", {})
    before = [f["name"] for f in d(call("list_features", {}))["features"]]
    sel = call("select_entity", {"type": "SKETCH", "name": "Keep"})
    info(f"stale select Keep: ok={sel.get('ok')}")
    r = call("delete_feature", {"feature_names": ["Target"]})
    rd = d(r)
    after = [f["name"] for f in d(call("list_features", {}))["features"]]
    record(F, "stale selection on Keep; delete_feature(Target) deletes only Target",
           bool(r.get("ok")) and "Keep" in after and "Target" not in after
           and [n for n in before if n not in after] == ["Target"],
           f"ok={r.get('ok')} deleted={rd.get('deleted')} also={rd.get('also_deleted')} counts={rd.get('feature_count_before')}->{rd.get('feature_count_after')} "
           f"gone={[n for n in before if n not in after]}")
    # case-insensitive unique match
    r = call("delete_feature", {"feature_names": ["keep"]})
    after2 = [f["name"] for f in d(call("list_features", {}))["features"]]
    record(F, "loose name match 'keep' deletes Keep", bool(r.get("ok")) and "Keep" not in after2,
           f"ok={r.get('ok')} deleted={d(r).get('deleted')}")
    r = call("delete_feature", {"feature_names": ["NoSuchFeature"]})
    record(F, "unknown name refused", r.get("ok") is False, f"ok={r.get('ok')} msg={str(r.get('message'))[:90]}")
    # dependent delete: fillet child of BaseBoss
    e = d(call("list_edges", {"limit": 5})).get("edges", [])
    fr = call("fillet", {"radius_mm": 1, "selection": {"edges": [e[0]["index"]]}, "name": "FilletChild"}) if e else {}
    info(f"fillet child ok={fr.get('ok')}")
    v_before = vol()
    r = call("delete_feature", {"feature_names": ["BaseBoss"]})
    rd = d(r)
    names = [x["name"] for x in rd.get("deleted", [])]
    after3 = [f["name"] for f in d(call("list_features", {}))["features"]]
    record(F, "dependent case: deleting BaseBoss reports FilletChild under also_deleted",
           bool(r.get("ok")) and "FilletChild" in [x["name"] for x in rd.get("also_deleted", [])]
           and "BaseBoss" not in after3 and "FilletChild" not in after3 and vol() == 0.0,
           f"ok={r.get('ok')} deleted={names} also={[x['name'] for x in rd.get('also_deleted', [])]} vol {v_before}->{vol()} "
           f"remaining={after3}")
    close_part(t)


# ---------------------------------------------------------------- #9
def f9() -> None:
    from solidworks_mcp.sw_core import active_document
    from solidworks_mcp.sw_feature import _is_suppressed
    from solidworks_mcp.sw_core import find_feature

    F = "#9"
    t = new_part()
    sk_rect("front", "Base")
    call("boss_extrude", {"sketch_name": "Base", "depth_mm": 10, "name": "ParentBoss"})
    faces = d(call("list_faces", {"normal": [0, 0, 1], "min_area_mm2": 100})).get("faces", [])
    top = max(faces, key=lambda f: f["point_mm"][2]) if faces else None
    info(f"top face {top and (top['index'], top['point_mm'])}")
    s = call("create_sketch", {"face_index": top["index"], "name": "ChildSketch"})
    info(f"face sketch ok={s.get('ok')} axes x={d(s).get('sketch_x_axis')} y={d(s).get('sketch_y_axis')}")
    # centred on the face: model x 5..15; y 5..15
    call("draw_rectangle", {"x1_mm": 5, "y1_mm": 5, "x2_mm": 15, "y2_mm": 15})
    call("close_sketch", {})
    cb = call("boss_extrude", {"sketch_name": "ChildSketch", "depth_mm": 5, "name": "ChildBoss"})
    v_full = vol()
    info(f"child boss ok={cb.get('ok')} vol={v_full}")

    def state(name: str):
        _, doc = active_document()
        return _is_suppressed(doc, find_feature(doc, name))

    # suppress child, twice
    r1 = call("set_feature_suppression", {"feature_names": ["ChildBoss"], "suppressed": True})
    r2 = call("set_feature_suppression", {"feature_names": ["ChildBoss"], "suppressed": True})
    record(F, "suppress ChildBoss then again: second reports already:true, ok, state suppressed",
           bool(r1.get("ok")) and bool(r2.get("ok")) and d(r2).get("already") is True and not d(r1).get("already")
           and state("ChildBoss") is True and near(vol(), 4000, 0.5),
           f"r1 ok={r1.get('ok')} changed={d(r1).get('changed')} | r2 ok={r2.get('ok')} already={d(r2).get('already')} "
           f"in_state={d(r2).get('already_in_state')} state={state('ChildBoss')} vol={vol()}")
    r = call("set_feature_suppression", {"feature_names": ["ChildBoss"], "suppressed": False})
    record(F, "unsuppress ChildBoss restores volume 4500",
           bool(r.get("ok")) and state("ChildBoss") is False and near(vol(), v_full, 0.5),
           f"ok={r.get('ok')} changed={d(r).get('changed')} state={state('ChildBoss')} vol={vol()} (full {v_full})")
    # suppress parent -> children side effects
    r = call("set_feature_suppression", {"feature_names": ["ParentBoss"], "suppressed": True})
    rd = d(r)
    se = rd.get("side_effects")
    record(F, "suppress ParentBoss: side_effects lists children, final states correct",
           bool(r.get("ok")) and bool(se) and any("Child" in str(x) for x in se)
           and state("ParentBoss") is True and state("ChildBoss") is True,
           f"ok={r.get('ok')} changed={rd.get('changed')} side_effects={se} mismatched={rd.get('mismatched')} "
           f"parent={state('ParentBoss')} child={state('ChildBoss')} vol={vol()}")
    r = call("set_feature_suppression", {"feature_names": ["ParentBoss"], "suppressed": True})
    record(F, "suppress already-suppressed parent: already:true",
           bool(r.get("ok")) and d(r).get("already") is True, f"ok={r.get('ok')} already={d(r).get('already')} msg={str(r.get('message'))[:90]}")
    # SOLIDWORKS semantics (observed live): unsuppressing a parent does NOT unsuppress the children
    # that were suppressed along with it.  Expect parent False, child still True, volume 4000.
    r = call("set_feature_suppression", {"feature_names": ["ParentBoss"], "suppressed": False})
    record(F, "unsuppress parent: parent restored, children stay suppressed (SW semantics), no false side_effects",
           bool(r.get("ok")) and state("ParentBoss") is False and state("ChildBoss") is True and near(vol(), 4000, 0.5),
           f"ok={r.get('ok')} changed={d(r).get('changed')} side_effects={d(r).get('side_effects')} "
           f"parent={state('ParentBoss')} child={state('ChildBoss')} vol={vol()} msg={str(r.get('message'))[:140]}")
    r = call("set_feature_suppression", {"feature_names": ["ChildSketch", "ChildBoss"], "suppressed": False})
    record(F, "unsuppress ChildSketch+ChildBoss restores full volume 4500",
           bool(r.get("ok")) and state("ChildBoss") is False and near(vol(), v_full, 0.5),
           f"ok={r.get('ok')} changed={d(r).get('changed')} child={state('ChildBoss')} vol={vol()} (full {v_full})")
    close_part(t)


# ---------------------------------------------------------------- #17
def build_rounded_box() -> str:
    t = new_part()
    call("create_sketch", {"plane": "front", "name": "RB"})
    call("draw_rectangle", {"x1_mm": 0, "y1_mm": 0, "x2_mm": 40, "y2_mm": 30})
    f = call("sketch_fillet", {"radius_mm": 5, "corners": [{"x": 40, "y": 30}]})
    info(f"sketch_fillet ok={f.get('ok')} {str(f.get('message'))[:80]}")
    call("close_sketch", {})
    b = call("boss_extrude", {"sketch_name": "RB", "depth_mm": 10, "name": "RBBoss"})
    info(f"boss ok={b.get('ok')} vol={vol()}")
    return t


def top_edges() -> list[dict]:
    return d(call("list_edges", {"within_box": {"min": [-1, -1, 9.9], "max": [41, 31, 10.1]}})).get("edges", [])


def f17() -> None:
    F = "#17"
    t = build_rounded_box()
    v0 = vol()
    exp_v0 = 40 * 30 * 10 - (25 - math.pi * 25 / 4) * 10
    faces0 = d(call("list_faces", {}))
    n0 = faces0.get("total_faces")
    te = top_edges()
    info(f"v0={v0:.3f} expected={exp_v0:.3f}; top edges: " + "; ".join(
        f"{e['index']}:{e.get('curve_type')}:{e.get('length_mm')}" for e in te))
    # variable on multi-edge chain
    idx = [e["index"] for e in te if e.get("curve_type") in ("line", "circle")
           and (e["start_mm"][0] >= 34.9 or e["start_mm"][1] >= 24.9) and (e["end_mm"][0] >= 34.9 or e["end_mm"][1] >= 24.9)]
    chain = [e["index"] for e in te if e["end_mm"][0] > 34.9 and e["end_mm"][1] > 24.9 or e["start_mm"][0] > 34.9 and e["start_mm"][1] > 24.9]
    chain_idx = sorted(set(chain + [e["index"] for e in te if max(e["start_mm"][0], e["end_mm"][0]) > 39.9 or max(e["start_mm"][1], e["end_mm"][1]) > 29.9]))
    r = call("fillet_variant", {"type": "variable", "selection": {"edges": chain_idx}, "radius_mm": 1, "end_radius_mm": 3})
    record(F, f"variable fillet on multi-edge chain {chain_idx} refused clearly",
           r.get("ok") is False and near(vol(), v0, 0.01) and len(chain_idx) > 1,
           f"ok={r.get('ok')} vol={vol()} msg={str(r.get('message'))[:200]}")
    r = call("fillet_variant", {"type": "variable", "selection": {"edges": chain_idx[:1]}, "radius_mm": 1, "end_radius_mm": 3,
                                "vertex_radii": [1, 2]})
    record(F, "variable fillet with vertex_radii refused", r.get("ok") is False, f"ok={r.get('ok')} msg={str(r.get('message'))[:120]}")

    # constant fillet propagate=false on the x=40 straight edge (length 25)
    straight = [e for e in te if e.get("curve_type") == "line" and abs(e["start_mm"][0] - 40) < 0.01 and abs(e["end_mm"][0] - 40) < 0.01]
    if not straight:
        record(F, "locate x=40 top edge", False, f"top edges={te}")
        close_part(t)
        return
    e = straight[0]
    R = 2.0
    L = e["length_mm"]
    single_exp = L * R * R * (1 - math.pi / 4)
    r = call("fillet", {"radius_mm": R, "selection": {"edges": [e["index"]]}, "propagate": False, "name": "NoProp"})
    rd = d(r)
    v1 = vol()
    removed = v0 - v1
    faces1 = d(call("list_faces", {}))
    n1 = faces1.get("total_faces")
    new_faces = (n1 or 0) - (n0 or 0)
    surf = {}
    for f in faces1.get("faces", []):
        surf[f.get("surface_type")] = surf.get(f.get("surface_type"), 0) + 1
    # chain expectation: line 25 + arc (centre-line length at r5 corner ~ pi/2*(5)) + line 35
    chain_exp = (25 + 35 + math.pi / 2 * 5) * R * R * (1 - math.pi / 4)
    propagated = removed > single_exp * 1.5
    record(F, "fillet propagate=false on one edge of tangent chain: RECORDED (propagated?)",
           bool(r.get("ok")) and rd.get("fillet_options") == 2 and rd.get("propagate") is False,
           f"ok={r.get('ok')} options={rd.get('fillet_options')} propagate={rd.get('propagate')} removed={removed:.3f} "
           f"single_edge_expect={single_exp:.3f} full_chain_expect~{chain_exp:.3f} PROPAGATED={propagated} "
           f"faces {n0}->{n1} (+{new_faces}) surface types={surf}")
    new_idx = [f["index"] for f in faces1.get("faces", []) if f.get("surface_type") in ("cylinder", "torus", "cone")]
    info("fillet feature faces: " + json.dumps(d(call("list_faces", {"feature": "NoProp"})).get("faces", [])
                                                 and [(f['index'], f.get('surface_type'), f.get('area_mm2')) for f in d(call('list_faces', {'feature': 'NoProp'}))['faces']]))
    close_part(t)

    # variable fillet on single edge, propagate=false
    t = build_rounded_box()
    v0 = vol()
    te = top_edges()
    straight = [e for e in te if e.get("curve_type") == "line" and abs(e["start_mm"][0] - 40) < 0.01 and abs(e["end_mm"][0] - 40) < 0.01]
    r = call("fillet_variant", {"type": "variable", "selection": {"edges": [straight[0]["index"]]},
                                "radius_mm": 1, "end_radius_mm": 3, "propagate": False, "name": "VarOne"})
    v1 = vol()
    est = L * (1 - math.pi / 4) * ((1 + 3 + 9) / 3)
    record(F, "variable fillet 1->3 on a single edge propagate=false builds (removal ~ estimate)",
           bool(r.get("ok")) and 0.5 * est < v0 - v1 < 1.5 * est,
           f"ok={r.get('ok')} removed={v0 - v1:.3f} est~{est:.3f} msg={str(r.get('message'))[:100]}")
    close_part(t)


def main() -> int:
    before = d(call("list_open_documents", {})).get("documents", [])
    if before:
        print("STOP: documents already open:", [x["title"] for x in before])
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        only = sys.argv[1:]
        for fn in (f5_front, f5_planes, f5_conflict, f8, f9, f17):
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
        (OUT / "results_feature.json").write_text(json.dumps(RESULTS, indent=2), encoding="utf-8")
    return 0 if all(r["result"] == "PASS" for r in RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
